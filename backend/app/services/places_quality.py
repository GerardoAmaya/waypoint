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
}

# Patrones que describen señalizacion o hitos, no destinos.
NOT_A_DESTINATION = re.compile(
    r"^(letrero|rotulo|señal|senal|hito|monolito|km\s|kilometro|deslave|"
    r"derrumbe|acceso|entrada a|desvio)\b",
    re.IGNORECASE,
)

MIN_NAME_LENGTH = 4


@dataclass(frozen=True)
class Verdict:
    """Resultado de evaluar un lugar."""

    accepted: bool
    category: Category | None = None
    subcategory: str | None = None
    score: float = 0.0
    reason: str | None = None


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


def classify(tags: dict) -> tuple[Category, str] | None:
    """Determina la categoria a partir de las etiquetas de OSM."""
    for key, values, category in TAG_RULES:
        raw = tags.get(key)
        if raw is None:
            continue
        # Una regla sin valores acepta cualquier valor de esa clave.
        if not values or raw in values:
            return category, raw
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
