"""Carga el nomenclator: departamentos, municipios, distritos, pueblos y barrios.

    python -m scripts.load_gazetteer            # descarga y guarda
    python -m scripts.load_gazetteer --dry-run  # solo dice que haria

**Por que hace falta un nomenclator y no alcanza el catalogo.** El catalogo son
puntos de interes: volcanes, museos, comedores. "Mejicanos" no es ninguno de
esos —lo unico llamado Mejicanos en el catalogo son cuatro puestos de comida— y
por eso "vivo en Mejicanos" no resolvia nada. Un nombre de lugar y un punto de
interes son cosas distintas.

Antes de esto el proyecto conocia veinte zonas escritas a mano en Python. Con el
nomenclator conoce los nombres que OSM tiene para el pais entero.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.models import PlaceName

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("load_gazetteer")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="SV"][admin_level=2]->.sv;
(
  relation["boundary"="administrative"]["admin_level"~"^(4|6|8)$"]["name"](area.sv);
);
out tags bb;
(
  node["place"~"^(city|town|village|suburb|neighbourhood)$"]["name"](area.sv);
);
out tags center;
"""

# Radio por tipo para los lugares que OSM publica como un punto suelto, sin
# limite del que sacar el tamano. Salen de lo que mide cada cosa en el pais: un
# barrio de San Salvador se recorre a pie, una aldea tiene su vecindario a unos
# kilometros.
RADIO_POR_TIPO_KM = {
    "city": 12.0,
    "town": 8.0,
    "village": 5.0,
    "suburb": 5.0,
    "neighbourhood": 3.0,
}

# Recorte del radio que sale del recuadro. El minimo evita que un municipio
# diminuto no encuentre nada; el maximo evita que un departamento entero mande
# a buscar candidatos a cincuenta kilometros.
RADIO_MIN_KM = 3.0
RADIO_MAX_KM = 35.0

# Debajo de esto el nombre no sirve para armar un dia: se guarda marcado para
# poder medir el filtro, pero no se ofrece. Cuatro es el minimo con el que un
# dia tiene forma de dia.
MIN_DESTINOS = 4


@dataclass
class Candidato:
    osm_type: str
    osm_id: int
    name: str
    kind: str
    lat: float
    lon: float
    radius_m: int


def _radio_del_recuadro_km(bounds: dict) -> float:
    """La mitad de la diagonal del recuadro, en kilometros.

    Es la aproximacion honesta: el limite real es un polinomio con cientos de
    vertices, y para decidir en que radio buscar candidatos la diagonal del
    recuadro alcanza. Guardar el polinomio entero solo para eso seria pagar
    mucho por una precision que nadie usa.
    """
    lat_media = math.radians((bounds["maxlat"] + bounds["minlat"]) / 2)
    alto = (bounds["maxlat"] - bounds["minlat"]) * 110.574
    ancho = (bounds["maxlon"] - bounds["minlon"]) * 111.320 * math.cos(lat_media)
    return math.hypot(alto, ancho) / 2


def parse_elements(elementos: list[dict]) -> list[Candidato]:
    """Convierte la respuesta de Overpass en candidatos con su radio."""
    salida: list[Candidato] = []

    for elemento in elementos:
        tags = elemento.get("tags") or {}
        nombre = (tags.get("name") or "").strip()
        if not nombre:
            continue

        nivel = tags.get("admin_level")
        # El pais entero no es un nombre util para centrar una busqueda.
        if nivel == "2":
            continue

        if elemento.get("bounds"):
            recuadro = elemento["bounds"]
            lat = (recuadro["maxlat"] + recuadro["minlat"]) / 2
            lon = (recuadro["maxlon"] + recuadro["minlon"]) / 2
            radio = _radio_del_recuadro_km(recuadro)
            kind = f"admin{nivel}"
        else:
            centro = elemento.get("center") or elemento
            lat, lon = centro.get("lat"), centro.get("lon")
            if lat is None or lon is None:
                continue
            kind = tags.get("place") or ""
            radio = RADIO_POR_TIPO_KM.get(kind, 5.0)

        if not kind:
            continue

        radio = max(RADIO_MIN_KM, min(RADIO_MAX_KM, radio))
        salida.append(
            Candidato(
                osm_type=elemento["type"],
                osm_id=elemento["id"],
                name=nombre,
                kind=kind,
                lat=lat,
                lon=lon,
                radius_m=int(radio * 1000),
            )
        )

    return salida


# Espera entre reintentos. Overpass es un servidor publico y bajo carga corta
# con 429 o 504; insistir sin esperar solo empeora la cola de todos.
PAUSE_SECONDS = 8.0


def fetch() -> list[dict]:
    """Descarga el nomenclator, con reintentos ante corte por carga.

    Los 504 pasan de verdad: esta consulta pide tres mil elementos de una vez y
    el servidor publico se corta cuando esta ocupado. Sin reintentos, cargar el
    nomenclator es una tirada de dados.
    """
    # Overpass rechaza con 406 a quien no se identifica: el User-Agent por
    # defecto de la libreria no le sirve.
    with httpx.Client(
        timeout=300,
        headers={"User-Agent": "Waypoint/0.1 (proyecto de portafolio)"},
    ) as cliente:
        for intento in range(1, 5):
            logger.info("consultando Overpass (intento %d)", intento)
            try:
                respuesta = cliente.post(OVERPASS_URL, data={"data": QUERY})
            except httpx.RequestError as exc:
                logger.warning("  error de red (%s)", exc)
                time.sleep(PAUSE_SECONDS * intento)
                continue

            if respuesta.status_code == 200:
                return respuesta.json().get("elements") or []

            if respuesta.status_code in (429, 504):
                espera = PAUSE_SECONDS * intento * 2
                logger.warning("  HTTP %s, esperando %.0fs", respuesta.status_code, espera)
                time.sleep(espera)
                continue

            respuesta.raise_for_status()

    raise RuntimeError("Overpass no respondio despues de cuatro intentos")


def count_destinations(db, candidatos: list[Candidato]) -> dict[tuple[str, int], int]:
    """Destinos del catalogo dentro del radio de cada candidato.

    Una sola consulta para los tres mil: pasarlos como JSON y unir contra
    places es mucho mas rapido que tres mil ST_DWithin sueltos.

    No cuenta comida: un barrio con veinte pupuserias y ningun destino no da
    para un dia, y contarlas lo haria pasar el filtro.
    """
    datos = [
        {"t": c.osm_type, "i": c.osm_id, "lat": c.lat, "lon": c.lon, "r": c.radius_m}
        for c in candidatos
    ]

    filas = db.execute(
        text("""
            WITH c AS (
              SELECT (x->>'t') AS osm_type, (x->>'i')::bigint AS osm_id,
                     (x->>'lat')::float AS lat, (x->>'lon')::float AS lon,
                     (x->>'r')::int AS radio
              FROM jsonb_array_elements(CAST(:datos AS jsonb)) AS x
            )
            SELECT c.osm_type, c.osm_id, count(p.id) AS destinos
            FROM c
            LEFT JOIN places p
              ON p.is_active
             AND p.category <> 'food'
             AND ST_DWithin(
                   p.geom,
                   ST_SetSRID(ST_MakePoint(c.lon, c.lat), 4326)::geography,
                   c.radio
                 )
            GROUP BY c.osm_type, c.osm_id
        """),
        {"datos": json.dumps(datos)},
    ).all()

    return {(f.osm_type, f.osm_id): f.destinos for f in filas}


def persist(db, candidatos: list[Candidato], destinos: dict) -> tuple[int, int]:
    """Guarda o actualiza. Devuelve (activos, marcados)."""
    valores = []
    activos = marcados = 0

    for c in candidatos:
        cerca = destinos.get((c.osm_type, c.osm_id), 0)
        pobre = cerca < MIN_DESTINOS
        if pobre:
            marcados += 1
        else:
            activos += 1
        valores.append(
            {
                "osm_type": c.osm_type,
                "osm_id": c.osm_id,
                "name": c.name,
                "kind": c.kind,
                "lat": c.lat,
                "lon": c.lon,
                "geom": f"SRID=4326;POINT({c.lon} {c.lat})",
                "radius_m": c.radius_m,
                "destinations_nearby": cerca,
                "is_active": not pobre,
                "rejected_reason": "pocos_destinos" if pobre else None,
            }
        )

    if valores:
        sentencia = insert(PlaceName).values(valores)
        db.execute(
            sentencia.on_conflict_do_update(
                index_elements=["osm_type", "osm_id"],
                set_={
                    campo: getattr(sentencia.excluded, campo)
                    for campo in (
                        "name",
                        "kind",
                        "lat",
                        "lon",
                        "geom",
                        "radius_m",
                        "destinations_nearby",
                        "is_active",
                        "rejected_reason",
                    )
                },
            )
        )
        db.commit()

    return activos, marcados


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="no escribe nada")
    args = parser.parse_args()

    candidatos = parse_elements(fetch())
    logger.info("candidatos con nombre: %d", len(candidatos))

    por_tipo: dict[str, int] = {}
    for c in candidatos:
        por_tipo[c.kind] = por_tipo.get(c.kind, 0) + 1
    for kind, cuantos in sorted(por_tipo.items(), key=lambda kv: -kv[1]):
        logger.info("  %-16s %5d", kind, cuantos)

    db = SessionLocal()
    try:
        destinos = count_destinations(db, candidatos)
        pobres = sum(
            1 for c in candidatos if destinos.get((c.osm_type, c.osm_id), 0) < MIN_DESTINOS
        )
        logger.info(
            "con menos de %d destinos cerca: %d de %d",
            MIN_DESTINOS,
            pobres,
            len(candidatos),
        )

        if args.dry_run:
            logger.info("--dry-run: no se escribio nada")
            return 0

        activos, marcados = persist(db, candidatos, destinos)
        logger.info("guardados: %d activos, %d marcados", activos, marcados)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
