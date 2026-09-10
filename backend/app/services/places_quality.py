"""Clasificacion y control de calidad de los lugares de OpenStreetMap.

Los datos crudos de OSM traen ruido que arruinaria un itinerario. En la muestra
de El Salvador aparecieron nombres inutiles ("Mirador", "El Museo"), duplicados
("Cascadas de Huizucar" dos veces) y cosas que no son destinos ("Letrero de
Sonsonate", "Deslave de las Colinas 2001").

Un itinerario que recomiende "visita Mirador" no sirve. Este modulo decide que
entra al catalogo y por que, y deja registrado el motivo de cada descarte para
poder medir y afinar el filtro despues.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.models import Category

# Etiqueta de OSM -> categoria propia. El orden importa: la primera que
# coincide gana, asi que lo mas especifico va primero.
TAG_RULES: list[tuple[str, tuple[str, ...], Category]] = [
    ("tourism", ("viewpoint",), Category.viewpoint),
    ("tourism", ("museum", "gallery", "artwork"), Category.culture),
    ("tourism", ("attraction", "theme_park", "zoo", "aquarium"), Category.attraction),
    ("tourism", ("hotel", "hostel", "guest_house", "resort"), Category.lodging),
    ("historic", (), Category.culture),
    (
        "amenity",
        ("restaurant", "cafe", "bar", "fast_food", "ice_cream", "marketplace", "pub"),
        Category.food,
    ),
    ("amenity", ("theatre", "arts_centre"), Category.culture),
    ("natural", ("beach", "volcano", "peak", "spring", "cave_entrance"), Category.nature),
    ("waterway", ("waterfall",), Category.nature),
    ("leisure", ("park", "nature_reserve", "garden"), Category.nature),
    # **El centro comercial entra para poder salir de el, no para visitarlo.**
    # "Salgo desde Metrocentro Santa Ana" es una forma normalisima de decir de
    # donde arranca el dia, y sin esta regla el catalogo no tenia ni uno: la
    # consulta de Overpass pedia turismo, comida, naturaleza, historico,
    # cultura y edificios de hotel, y nada de comercio.
    #
    # Cae en atraccion y su subcategoria no esta en SUBCATEGORY_APPEAL, asi
    # que hereda DEFAULT_APPEAL —0.25— y queda por debajo de MIN_APPEAL, que
    # es 0.45: el motor no lo elige nunca como destino. La busqueda por nombre
    # si lo encuentra, que es exactamente lo que hace falta. Es la misma
    # asimetria que ya tienen los comedores y los hoteles.
    ("shop", ("mall",), Category.attraction),
]

# Nombres genericos que no identifican nada. Alguien que lee "visita Mirador"
# no sabe adonde ir.
GENERIC_NAMES = {
    "mirador",
    "miradores",
    "cascada",
    "cascadas",
    "museo",
    "el museo",
    "parque",
    "el parque",
    "playa",
    "la playa",
    "iglesia",
    "la iglesia",
    "restaurante",
    "cafe",
    "cafeteria",
    "hotel",
    "comedor",
    "pupuseria",
    "tienda",
    "bar",
    "mercado",
    "el mercado",
    "rio",
    "el rio",
    "puente",
    "escuela",
    "plaza",
    "la plaza",
    "cancha",
    "volcan",
    "el volcan",
    "panoramico",
    "vista",
    "lago",
    "laguna",
    "salto",
    "poza",
    "finca",
    "piscina",
    "piscinas",
    "la piscina",
    "balneario",
    "cerro",
    "el cerro",
    "cueva",
    "la cueva",
    "ruinas",
    "monumento",
    "parroquia",
    "ermita",
    "gasolinera",
    "cementerio",
    "estadio",
    "turicentro",
}

# Patrones que describen señalizacion o hitos, no destinos.
NOT_A_DESTINATION = re.compile(
    r"^(letrero|rotulo|señal|senal|hito|monolito|km\s|kilometro|deslave|"
    r"derrumbe|acceso|entrada a|desvio)\b",
    re.IGNORECASE,
)

# En OpenStreetMap pasa seguido que alguien usa "name" como campo libre y le
# mete el horario o una descripcion. Un itinerario que diga "visita Feria
# Gastronomica sabado y domingo 0800 a 1700" se delata solo.
#
# Se detecta por el horario y no por el largo: hay nombres legitimos igual de
# largos ("Finca y Mirador La Providencia de Concepcion de Ataco") y contar
# palabras los tiraria junto con la basura.
CLOCK_TIME = re.compile(r"\d{1,2}:\d{2}")

# "0800 a 1700", "0900-1600".
HOUR_RANGE = re.compile(r"\b\d{3,4}\s*(?:a|-|hasta)\s*\d{3,4}\b", re.IGNORECASE)

WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
WEEKDAY_PATTERN = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b", re.IGNORECASE)

# Numero suelto de tres o cuatro cifras, que junto a un dia es una hora.
BARE_HOUR = re.compile(r"\b\d{3,4}\b")


def looks_like_schedule(name: str) -> bool:
    """Si el nombre es en realidad un horario y no un nombre.

    **Un dia de la semana suelto no alcanza como evidencia.** La primera
    version rechazaba cualquier nombre que contuviera uno, y en un pais
    catolico eso se lleva medio santoral por delante: "Hostal Villa Santo
    Domingo" y "Cerro Santo Domingo" son lugares reales. Lo detecto la corrida
    en seco del reetiquetado, que es para lo que existe.

    Hace falta una hora explicita, o dos dias distintos, o un dia acompanado
    de un numero que parezca hora.
    """
    if CLOCK_TIME.search(name) or HOUR_RANGE.search(name):
        return True

    dias = {d.lower() for d in WEEKDAY_PATTERN.findall(name)}
    if len(dias) >= 2:
        return True

    return bool(dias) and bool(BARE_HOUR.search(name))


MIN_NAME_LENGTH = 4


@dataclass(frozen=True)
class Verdict:
    """Resultado de evaluar un lugar."""

    accepted: bool
    category: Category | None = None
    subcategory: str | None = None
    score: float = 0.0
    reason: str | None = None


def _deaccent(text: str) -> str:
    """Sin acentos y en minusculas, pero conservando la puntuacion.

    normalize() tambien quita la puntuacion, que para comparar nombres esta
    bien y para detectar horarios no: sin los dos puntos, "8:00" deja de
    parecer una hora.
    """
    descompuesto = unicodedata.normalize("NFKD", text)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).lower()


def normalize(text: str) -> str:
    """Minusculas sin acentos ni puntuacion, con espacios colapsados.

    Colapsar los espacios importa: quitar la puntuacion de "Cafe, S.A." deja
    huecos dobles, y sin normalizarlos dos escrituras del mismo nombre no
    coinciden.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    sin_puntuacion = re.sub(r"[^a-z0-9\s]+", " ", stripped.lower())
    return re.sub(r"\s+", " ", sin_puntuacion).strip()


# Palabras que en el nombre delatan un alojamiento de verdad.
#
# Hacen falta porque `building=hotel` describe el EDIFICIO y no el negocio, y
# eso lo vuelve una etiqueta de poca precision: dentro de un complejo hotelero
# hay varios edificios marcados asi —torres, lobbies, el centro de
# convenciones— y encima aparece mal puesta en cosas que no son hoteles.
#
# Medido sobre El Salvador: de 17 objetos con `building=hotel`, nombre y sin
# etiqueta `tourism`, solo 8 son hoteles. Los otros son "Torre 3", "Lobby 2",
# "Discoteca Ixchel" y una "Emergencia Unidad Medica". Ningun filtro de nombres
# generico los agarra: no son nombres genericos, son etiquetas equivocadas.
LODGING_NAME = re.compile(
    r"\b(hotel|hostal|hostel|posada|motel|suites?|resort|lodge|inn|"
    r"albergue|caba[nñ]as?)\b",
    re.IGNORECASE,
)

# Etiquetas de edificio que valen como alojamiento SOLO si el nombre lo
# confirma. Es un canje explicito: se pierde algun hotel cuyo nombre no lleve
# la palabra —"Courtyard by Marriott" es el caso real— a cambio de no meter una
# discoteca y una sala de emergencias en la lista de alojamientos.
BUILDING_LODGING = ("hotel", "hostel", "motel")


def classify(tags: dict) -> tuple[Category, str] | None:
    """Determina la categoria a partir de las etiquetas de OSM."""
    for key, values, category in TAG_RULES:
        raw = tags.get(key)
        if raw is None:
            continue
        # Una regla sin valores acepta cualquier valor de esa clave.
        if not values or raw in values:
            return category, raw

    # El edificio, solo con el nombre de su parte. Va al final para que una
    # etiqueta `tourism` explicita siempre gane: quien la puso sabia mas.
    edificio = tags.get("building")
    if edificio in BUILDING_LODGING and LODGING_NAME.search(tags.get("name") or ""):
        return Category.lodging, f"building:{edificio}"

    return None


def score_quality(tags: dict, category: Category) -> float:
    """Puntua cuanta informacion util trae el lugar, de 0 a 1.

    No mide si el lugar es bueno, mide si el registro sirve para armar un
    itinerario. Un museo con horarios y sitio web es mas util que uno que solo
    tiene nombre.
    """
    score = 0.4  # base: tiene nombre y categoria valida

    if tags.get("opening_hours"):
        score += 0.15
    if tags.get("website") or tags.get("contact:website"):
        score += 0.10
    if tags.get("phone") or tags.get("contact:phone"):
        score += 0.05
    if tags.get("description") or tags.get("wikipedia") or tags.get("wikidata"):
        score += 0.15
    if tags.get("addr:city") or tags.get("addr:street"):
        score += 0.10

    if category is Category.food and tags.get("cuisine"):
        score += 0.05

    return round(min(score, 1.0), 3)


def evaluate(tags: dict) -> Verdict:
    """Decide si un lugar entra al catalogo.

    Cada rechazo lleva un motivo con nombre, para que el reporte de carga diga
    que se descarto y por que en vez de un total sin explicacion.
    """
    name = (tags.get("name") or "").strip()

    if not name:
        return Verdict(False, reason="sin_nombre")

    if len(name) < MIN_NAME_LENGTH:
        return Verdict(False, reason="nombre_muy_corto")

    normalized = normalize(name)

    if normalized in GENERIC_NAMES:
        return Verdict(False, reason="nombre_generico")

    if NOT_A_DESTINATION.match(name):
        return Verdict(False, reason="no_es_destino")

    # Se comprueba sobre el nombre sin acentos pero CON puntuacion. normalize()
    # borra los dos puntos, y sin ellos "8:00" queda como "8 00" y deja de
    # parecer una hora.
    if looks_like_schedule(_deaccent(name)):
        return Verdict(False, reason="nombre_es_horario")

    # Un nombre sin ninguna letra ("2001", "km 45") no identifica un lugar.
    if not re.search(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]", name):
        return Verdict(False, reason="nombre_sin_letras")

    classified = classify(tags)
    if classified is None:
        return Verdict(False, reason="categoria_no_soportada")

    category, subcategory = classified
    return Verdict(
        accepted=True,
        category=category,
        subcategory=subcategory,
        score=score_quality(tags, category),
    )
