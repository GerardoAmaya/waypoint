#!/usr/bin/env python3
"""Descarga el catalogo de lugares de El Salvador desde OpenStreetMap.

Se corre una vez, no en cada peticion. Overpass limita el uso y Nominatim
bloquea por IP a mas de una peticion por segundo; consultar en vivo seria
chocar contra ese limite en cada visita. El catalogo entero de El Salvador cabe
en la base, asi que lo bajamos una vez y la aplicacion consulta su propia copia.

Uso:
    python -m scripts.load_places
    python -m scripts.load_places --dry-run
    python -m scripts.load_places --dedupe-only   # tambien reagrupa

Las dos pasadas de limpieza van juntas y en orden: primero `deduplicate()`
descarta las filas sobrantes, y despues `group_same_places()` agrupa las que
quedan y son el mismo sitio con nombres distintos. Las dos se recalculan
enteras en cada corrida, asi que el resultado depende del catalogo de hoy y no
del orden historico de las cargas.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import unicodedata
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
    # El edificio del hotel, para los que nadie etiqueto como tourism. El Hotel
    # Barcelo de San Salvador es asi: existe en OSM solo con building=hotel, y
    # por eso no estaba en el catalogo. places_quality exige que el nombre
    # confirme que es alojamiento antes de aceptarlo, porque esta etiqueta la
    # llevan tambien las torres y los lobbies del mismo complejo.
    # Solo para partir de ellos: ver la regla de shop=mall en places_quality.
    # Trae ruido —hay tiendas de barrio etiquetadas como mall— y no importa,
    # porque nada de esto llega a ser un destino.
    "centros_comerciales": """
        node["shop"="mall"]["name"](area.sv);
        way["shop"="mall"]["name"](area.sv);
    """,
    "edificios_alojamiento": """
        node["building"~"hotel|hostel|motel"]["name"](area.sv);
        way["building"~"hotel|hostel|motel"]["name"](area.sv);
    """,
}

# Pausa entre consultas. Overpass no publica un limite fijo pero corta a quien
# insiste; esperar es mas barato que que nos bloqueen a mitad de la carga.
PAUSE_SECONDS = 8.0

# Radio de deduplicacion segun el tipo de lugar. Para un negocio urbano, 150 m
# distingue bien dos locales de la misma cuadra. Para un mirador en la cresta
# de un volcan no alcanza: dos personas marcan el mismo punto con trescientos
# metros de diferencia sin equivocarse ninguna.
URBAN_RADIUS_M = 150
OUTDOOR_RADIUS_M = 500
OUTDOOR_CATEGORIES = ("nature", "viewpoint")

NAME_SIMILARITY = 0.55

# --------------------------------------------------------------------------
# Agrupar lo que es el mismo sitio
# --------------------------------------------------------------------------

# Hasta donde se consideran dos filas el mismo sitio.
#
# Es el triple del radio de deduplicacion de exteriores, y puede serlo porque
# **esto no borra nada**: agrupar de mas cuesta un candidato en un itinerario,
# y deduplicar de mas borra un lugar del catalogo. Los errores no pesan igual,
# asi que los umbrales tampoco.
#
# Mil quinientos cubre el caso que lo motivo —"Parque Nacional El Imposible" y
# "Parque El Imposible", a 1.173 m— con margen.
SAME_PLACE_RADIUS_M = 1500

# Palabras que no distinguen nada y no cuentan para comparar nombres.
PALABRAS_VACIAS = frozenset({"el", "la", "los", "las", "de", "del", "y", "e", "a", "al"})

# Que tan rara tiene que ser una palabra para considerarla distintiva.
#
# **Es una fraccion del catalogo y no un numero fijo, para que escale.** Con
# 5.786 lugares da 6, y ahi la separacion es limpia: "imposible" aparece en 2
# lugares y "caulotal" en 2, mientras "hostel" esta en 19, "comercial" en 52,
# "pollo" en 154 y "cerro" en 766. Si el catalogo crece al doble, el umbral
# crece con el.
#
# Hace falta porque la contencion de palabras sola no alcanza: "Hostel" esta
# contenido en "Casa Frolaz Hostel" y son dos sitios distintos. Lo que delata
# al parque del ejemplo no es que un nombre contenga al otro, sino que
# comparten una palabra que casi no aparece en ningun otro lado.
PROPORCION_PALABRA_RARA = 0.001
MINIMO_PALABRA_RARA = 3


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


def download(dry_run: bool, solo: str | None = None) -> list[dict]:
    """Baja los grupos de la consulta, o uno solo si se pide.

    `solo` existe para agregar una categoria nueva sin repetir la carga
    entera: son ocho consultas con ocho segundos de pausa entre cada una, y
    Overpass corta a quien insiste —contesta 429— asi que repetirla por una
    etiqueta nueva es gastar su paciencia y la nuestra.
    """
    elementos: list[dict] = []
    grupos = {solo: QUERY_GROUPS[solo]} if solo else QUERY_GROUPS
    with httpx.Client(
        headers={"User-Agent": "Waypoint/0.1 (proyecto de portafolio)"}
    ) as client:
        for indice, (nombre, cuerpo) in enumerate(grupos.items()):
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
                     AND ST_DWithin(
                             a.geom, b.geom,
                             CASE WHEN a.category::text = ANY(:exteriores)
                                  THEN :radio_exterior ELSE :radio_urbano END
                         )
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
            {
                "radio_urbano": URBAN_RADIUS_M,
                "radio_exterior": OUTDOOR_RADIUS_M,
                "exteriores": list(OUTDOOR_CATEGORIES),
                "umbral": NAME_SIMILARITY,
            },
        )
        db.commit()
        return resultado.rowcount or 0
    finally:
        db.close()


def _palabras_significativas(nombre: str) -> set[str]:
    """Las palabras de un nombre que sirven para compararlo con otro.

    Sin tildes ni mayusculas porque OpenStreetMap las pone a voluntad, y sin
    articulos ni preposiciones porque no distinguen nada: "Cerro Nubes" y
    "Cerro de Nubes" son el mismo cerro.
    """
    plano = "".join(
        c
        for c in unicodedata.normalize("NFD", nombre.casefold())
        if unicodedata.category(c) != "Mn"
    )
    limpio = "".join(c if c.isalnum() else " " for c in plano)
    return {p for p in limpio.split() if p and p not in PALABRAS_VACIAS}


def _frecuencia_de_palabras(nombres: list[str]) -> Counter:
    """En cuantos lugares aparece cada palabra. Ver PROPORCION_PALABRA_RARA."""
    return Counter(
        palabra for nombre in nombres for palabra in _palabras_significativas(nombre)
    )


def _es_el_mismo_sitio(nombre_a: str, nombre_b: str, frecuencia: Counter, raras: int) -> bool:
    """Si dos nombres cercanos describen el mismo sitio.

    Dos condiciones, y cada una ataja un fallo que la otra deja pasar.

    **Uno tiene que contener al otro, palabra por palabra.** Es lo que separa
    "Parque El Imposible" dentro de "Parque Nacional El Imposible" de
    "Bahia Dorada" contra "Bahia Del Sol", que son dos playas distintas. El
    parecido de trigramas no sirve para esto y se midio: el caso bueno saca
    0,69 y los falsos positivos sacan 0,73 y 0,77, o sea que quedan por encima.

    **Y tienen que compartir una palabra rara.** Sin esto, "Hostel" dentro de
    "Casa Frolaz Hostel" pasaria el primer filtro, igual que "La Pizzeria"
    dentro de "Pizzeria Da Mario". Lo que delata al parque del ejemplo es que
    "imposible" aparece en dos lugares de todo el catalogo.
    """
    palabras_a = _palabras_significativas(nombre_a)
    palabras_b = _palabras_significativas(nombre_b)

    if not palabras_a or not palabras_b or palabras_a == palabras_b:
        # Los nombres identicos los agrupa el motor por su cuenta, y ahi la
        # regla es otra: dos "Pizza Hut" a cuarenta kilometros tambien sobran
        # en un mismo viaje, aunque no sean el mismo sitio.
        return False

    if not (palabras_a <= palabras_b or palabras_b <= palabras_a):
        return False

    corto = palabras_a if len(palabras_a) <= len(palabras_b) else palabras_b
    return any(frecuencia[palabra] <= raras for palabra in corto)


def group_same_places() -> int:
    """Agrupa las filas que son el mismo sitio. Devuelve cuantas quedaron agrupadas.

    **No desactiva nada.** A diferencia de deduplicate(), las dos filas siguen
    activas: cada una tiene su nombre, su categoria y su punto, y las dos
    sirven para buscar o para dibujar. Lo unico que se evita es que un mismo
    itinerario las visite a las dos.

    El fallo que lo motivo: tres dias por la Ruta de las Flores metian "Parque
    Nacional El Imposible" y "Parque El Imposible" el mismo dia, con el
    almuerzo en medio. El dia gastaba 34 de sus 47 kilometros en ir a comer y
    volver al mismo parque.

    Se recalcula entero en cada corrida, igual que la deduplicacion: asi el
    resultado depende del catalogo de hoy y no del orden historico de las
    cargas.
    """
    db = SessionLocal()
    try:
        db.execute(text("UPDATE places SET same_place_as = NULL"))

        filas = db.execute(
            text("SELECT id, name, quality_score FROM places WHERE is_active")
        ).all()
        if not filas:
            db.commit()
            return 0

        frecuencia = _frecuencia_de_palabras([f.name for f in filas])
        raras = max(MINIMO_PALABRA_RARA, round(len(filas) * PROPORCION_PALABRA_RARA))

        # La cercania la resuelve PostGIS, que es lo suyo; la comparacion de
        # nombres se hace aqui porque en SQL seria ilegible.
        cercanos = db.execute(
            text("""
                SELECT a.id AS id_a, a.name AS nombre_a,
                       b.id AS id_b, b.name AS nombre_b
                FROM places a
                JOIN places b
                  ON a.id < b.id
                 AND a.is_active AND b.is_active
                 AND ST_DWithin(a.geom, b.geom, :radio)
            """),
            {"radio": SAME_PLACE_RADIUS_M},
        ).all()

        # Union-find: la relacion tiene que ser transitiva. "El Cafetalon",
        # "Parque El Cafetalon" y "Jugos El Cafetalon" salen como tres pares
        # sueltos y son un solo sitio.
        padre: dict = {}

        def raiz(x):
            padre.setdefault(x, x)
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x

        def unir(x, y):
            rx, ry = raiz(x), raiz(y)
            if rx != ry:
                padre[rx] = ry

        for par in cercanos:
            if _es_el_mismo_sitio(par.nombre_a, par.nombre_b, frecuencia, raras):
                unir(par.id_a, par.id_b)

        if not padre:
            db.commit()
            return 0

        grupos: dict = {}
        for identificador in padre:
            grupos.setdefault(raiz(identificador), []).append(identificador)

        calidad = {f.id: (f.quality_score or 0.0, str(f.id)) for f in filas}
        agrupados = 0
        for miembros in grupos.values():
            if len(miembros) < 2:
                continue
            # El representante es el de mejor calidad, con el identificador de
            # desempate para que dos corridas den lo mismo.
            representante = max(miembros, key=lambda m: calidad.get(m, (0.0, "")))
            # **El representante se apunta a si mismo, no se queda en NULL.**
            # Dejarlo en NULL como hace duplicate_of parecia natural y rompia
            # la regla que esta columna existe para alimentar: el motor agrupa
            # por `same_place_as`, asi que el miembro daba "grupo:<id>" y el
            # representante daba su nombre, y no coincidian nunca. Con el
            # autoapuntado, NULL queda reservado para "no pertenece a ningun
            # grupo", que es lo unico que hace falta distinguir.
            for miembro in miembros:
                db.execute(
                    text("UPDATE places SET same_place_as = :rep WHERE id = :id"),
                    {"rep": representante, "id": miembro},
                )
                agrupados += 1

        db.commit()
        return agrupados
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
    parser.add_argument(
        "--dedupe-only",
        action="store_true",
        help="Sin descargar: solo deduplicar y reagrupar lo que ya esta en la base",
    )
    parser.add_argument(
        "--group",
        choices=sorted(QUERY_GROUPS),
        help="Bajar un solo grupo. Para agregar una categoria nueva sin repetir "
        "la carga entera, que son ocho consultas y una pausa de 8 s entre cada una.",
    )
    args = parser.parse_args()

    if not args.dedupe_only:
        inicio = time.time()
        elementos = download(args.dry_run, args.group)
        logger.info("%s elementos descargados en %.0fs", len(elementos), time.time() - inicio)

        if not elementos:
            sys.exit("No se descargo nada. Revisa la conexion o reintenta mas tarde.")

        conteo = persist(elementos)
        logger.info("Guardados: %s", dict(conteo))

    duplicados = deduplicate()
    logger.info("%s marcados como duplicados", duplicados)

    # Despues de deduplicar: los duplicados ya estan fuera, asi que los grupos
    # se arman solo sobre lo que de verdad sigue en el catalogo.
    agrupados = group_same_places()
    logger.info("%s agrupados como el mismo sitio", agrupados)

    report()


if __name__ == "__main__":
    main()
