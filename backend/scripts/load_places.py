#!/usr/bin/env python3
"""Descarga el catalogo de lugares de El Salvador desde OpenStreetMap.

Se corre una vez, no en cada peticion. Overpass limita el uso y Nominatim
bloquea por IP a mas de una peticion por segundo; consultar en vivo seria
chocar contra ese limite en cada visita. El catalogo entero de El Salvador cabe
en la base, asi que lo bajamos una vez y la aplicacion consulta su propia copia.

Uso:
    python -m scripts.load_places
    python -m scripts.load_places --dry-run
    python -m scripts.load_places --dedupe-only
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import Place  # noqa: E402
from app.services.places_quality import evaluate  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("load_places")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass pide moderacion y corta las consultas largas. Partimos por familia
# de etiquetas en vez de pedir todo junto: cada consulta es mas liviana y si
# una falla no se pierde el resto.
QUERY_GROUPS: dict[str, str] = {
    "turismo": """
        node["tourism"]["name"](area.sv);
        way["tourism"]["name"](area.sv);
    """,
    "comida": """
        node["amenity"~"restaurant|cafe|bar|fast_food|ice_cream|marketplace|pub"]["name"](area.sv);
        way["amenity"~"restaurant|cafe|marketplace"]["name"](area.sv);
    """,
    "naturaleza": """
        node["natural"~"beach|volcano|peak|spring|cave_entrance"]["name"](area.sv);
        way["natural"~"beach|volcano|peak"]["name"](area.sv);
        node["waterway"="waterfall"]["name"](area.sv);
        way["leisure"~"park|nature_reserve|garden"]["name"](area.sv);
        node["leisure"~"park|nature_reserve|garden"]["name"](area.sv);
    """,
    "historico": """
        node["historic"]["name"](area.sv);
        way["historic"]["name"](area.sv);
    """,
    "cultura": """
        node["amenity"~"theatre|arts_centre"]["name"](area.sv);
    """,
}

# Pausa entre consultas. Overpass no publica un limite fijo pero corta a quien
# insiste; esperar es mas barato que que nos bloqueen a mitad de la carga.
PAUSE_SECONDS = 8.0

# Dos lugares con nombres parecidos a menos de esta distancia son el mismo.
# 150 m: lo suficiente para unir "Cascadas de Huizucar" duplicada, sin fundir
# dos restaurantes distintos de la misma cuadra.
DUPLICATE_RADIUS_M = 150
NAME_SIMILARITY = 0.55


def build_query(cuerpo: str) -> str:
    return f"""
[out:json][timeout:180];
area["ISO3166-1"="SV"][admin_level=2]->.sv;
(
{cuerpo}
);
out center tags;
"""


def fetch_group(client: httpx.Client, nombre: str, cuerpo: str) -> list[dict]:
    """Descarga un grupo, con reintentos ante corte por carga del servidor."""
    consulta = build_query(cuerpo)

    for intento in range(1, 4):
        try:
            respuesta = client.post(OVERPASS_URL, data={"data": consulta}, timeout=240)
        except httpx.RequestError as exc:
            logger.warning("  %s: error de red (%s), reintento %s", nombre, exc, intento)
            time.sleep(PAUSE_SECONDS * intento)
            continue

        if respuesta.status_code == 200:
            return respuesta.json().get("elements", [])

        # 429 y 504 son los cortes tipicos de Overpass bajo carga.
        if respuesta.status_code in (429, 504):
            espera = PAUSE_SECONDS * intento * 2
            logger.warning(
                "  %s: HTTP %s, esperando %.0fs", nombre, respuesta.status_code, espera
            )
            time.sleep(espera)
            continue

        logger.error("  %s: HTTP %s", nombre, respuesta.status_code)
        return []

    logger.error("  %s: se agotaron los reintentos", nombre)
    return []


def extract_point(elemento: dict) -> tuple[float, float] | None:
    """Devuelve (lat, lon). Las areas traen su centroide en 'center'."""
    if "lat" in elemento and "lon" in elemento:
        return elemento["lat"], elemento["lon"]
    centro = elemento.get("center")
    if centro:
        return centro["lat"], centro["lon"]
    return None


def download(dry_run: bool) -> list[dict]:
    elementos: list[dict] = []
    with httpx.Client(
        headers={"User-Agent": "Waypoint/0.1 (proyecto de portafolio)"}
    ) as client:
        for indice, (nombre, cuerpo) in enumerate(QUERY_GROUPS.items()):
            if indice:
                time.sleep(PAUSE_SECONDS)
            logger.info("Descargando %s...", nombre)
            grupo = fetch_group(client, nombre, cuerpo)
            logger.info("  %s elementos", len(grupo))
            elementos.extend(grupo)
            if dry_run and elementos:
                break
    return elementos


def persist(elementos: list[dict]) -> Counter:
    """Evalua cada elemento y lo guarda, aceptado o rechazado.

    Los rechazados se guardan marcados en vez de descartarse: sin ellos no se
    podria medir el filtro ni afinarlo sin volver a descargar todo.
    """
    conteo: Counter = Counter()
    db = SessionLocal()

    try:
        for elemento in elementos:
            etiquetas = elemento.get("tags") or {}
            punto = extract_point(elemento)

            if punto is None:
                conteo["sin_coordenadas"] += 1
                continue

            lat, lon = punto
            veredicto = evaluate(etiquetas)

            fila = {
                "osm_type": elemento["type"],
                "osm_id": elemento["id"],
                "name": (etiquetas.get("name") or "(sin nombre)")[:300],
                "category": veredicto.category.value if veredicto.category else "attraction",
                "subcategory": veredicto.subcategory,
                "geom": f"SRID=4326;POINT({lon} {lat})",
                "lat": lat,
                "lon": lon,
                "tags": etiquetas,
                "quality_score": veredicto.score,
                "is_active": veredicto.accepted,
                "rejected_reason": veredicto.reason,
            }

            # Recargar el catalogo actualiza en vez de duplicar.
            sentencia = insert(Place).values(**fila)
            sentencia = sentencia.on_conflict_do_update(
                constraint="uq_places_osm",
                set_={
                    k: sentencia.excluded[k]
                    for k in (
                        "name",
                        "category",
                        "subcategory",
                        "geom",
                        "lat",
                        "lon",
                        "tags",
                        "quality_score",
                        "is_active",
                        "rejected_reason",
                    )
                },
            )
            db.execute(sentencia)

            conteo["aceptados" if veredicto.accepted else veredicto.reason] += 1

        db.commit()
    finally:
        db.close()

    return conteo


def deduplicate() -> int:
    """Marca como duplicados los lugares con nombre parecido y muy cercanos.

    OpenStreetMap tiene el mismo sitio cargado varias veces: en la muestra
    aparecieron dos "Cascadas de Huizucar" y dos variantes del mirador del
    volcan de Izalco. Sin unirlos, un itinerario puede mandar al usuario dos
    veces al mismo lugar.

    Se usa similitud de trigramas mas cercania: el nombre solo fundiria dos
    "Parque Central" de municipios distintos, que son lugares diferentes.
    """
    db = SessionLocal()
    try:
        # Punto de partida limpio: la deduplicacion se recalcula entera en cada
        # corrida en vez de acumularse sobre el estado anterior.
        db.execute(
            text("""
                UPDATE places
                SET duplicate_of = NULL,
                    -- Solo se reactiva lo que estaba desactivado por duplicado.
                    -- Un lugar rechazado por el filtro de calidad sigue fuera.
                    is_active = CASE
                        WHEN rejected_reason IS NULL OR rejected_reason = 'duplicado'
                                THEN true
                        ELSE false
                    END,
                    rejected_reason = NULLIF(rejected_reason, 'duplicado')
                -- Mirar duplicate_of y no solo rejected_reason: una recarga previa
                -- pudo limpiar el motivo al reprocesar el lugar como aceptado,
                -- dejando duplicate_of huerfano y el registro activo a la vez.
                WHERE duplicate_of IS NOT NULL OR rejected_reason = 'duplicado'
            """)
        )

        resultado = db.execute(
            text("""
                WITH pares AS (
                    SELECT a.id AS perdedor, b.id AS ganador
                    FROM places a
                    JOIN places b
                      ON a.id <> b.id
                     AND a.is_active AND b.is_active
                     AND a.duplicate_of IS NULL AND b.duplicate_of IS NULL
                     AND ST_DWithin(a.geom, b.geom, :radio)
                     AND similarity(a.name, b.name) >= :umbral
                     -- El ganador es el que trae mas informacion; a igualdad,
                     -- el de id menor, para que el resultado sea estable.
                     AND (b.quality_score, b.id) > (a.quality_score, a.id)
                )
                UPDATE places
                SET duplicate_of = pares.ganador,
                    is_active = false,
                    rejected_reason = 'duplicado'
                FROM pares
                WHERE places.id = pares.perdedor
            """),
            {"radio": DUPLICATE_RADIUS_M, "umbral": NAME_SIMILARITY},
        )
        db.commit()
        return resultado.rowcount or 0
    finally:
        db.close()


def report() -> None:
    db = SessionLocal()
    try:
        activos = db.execute(text("SELECT COUNT(*) FROM places WHERE is_active")).scalar()
        total = db.execute(text("SELECT COUNT(*) FROM places")).scalar()

        print(f"\n{'=' * 52}")
        print(f"Catalogo: {activos} lugares utilizables de {total} descargados")
        print("=" * 52)

        print("\nPor categoria:")
        for categoria, n, media in db.execute(
            text("""
                SELECT category, COUNT(*), ROUND(AVG(quality_score)::numeric, 2)
                FROM places WHERE is_active
                GROUP BY category ORDER BY COUNT(*) DESC
            """)
        ):
            print(f"  {categoria:12} {n:5}   calidad media {media}")

        print("\nDescartados:")
        for motivo, n in db.execute(
            text("""
                SELECT rejected_reason, COUNT(*)
                FROM places WHERE NOT is_active
                GROUP BY rejected_reason ORDER BY COUNT(*) DESC
            """)
        ):
            print(f"  {motivo or '(sin motivo)':24} {n:5}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo el primer grupo")
    parser.add_argument("--dedupe-only", action="store_true", help="Sin descargar")
    args = parser.parse_args()

    if not args.dedupe_only:
        inicio = time.time()
        elementos = download(args.dry_run)
        logger.info("%s elementos descargados en %.0fs", len(elementos), time.time() - inicio)

        if not elementos:
            sys.exit("No se descargo nada. Revisa la conexion o reintenta mas tarde.")

        conteo = persist(elementos)
        logger.info("Guardados: %s", dict(conteo))

    duplicados = deduplicate()
    logger.info("%s marcados como duplicados", duplicados)

    report()


if __name__ == "__main__":
    main()
