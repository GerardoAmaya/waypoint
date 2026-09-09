"""De un nombre de lugar a un punto en el mapa.

El catalogo son puntos de interes, no un nomenclator: buscar "Ataco" contra
nombres de POIs devuelve la iglesia de Ataco o nada, pero no el pueblo. Y
Nominatim quedo descartado desde el `PLAN.md` porque limita a una peticion por
segundo y bloquea por IP, asi que la aplicacion no lo consulta en vivo.

La salida es una lista curada de las zonas donde de verdad caen los
itinerarios. Son pocas y no se mueven. Es la misma lista que usa el
precalentado de cache, y eso no es casualidad: **una zona que vale la pena
precalentar es una zona a la que la gente pide ir.**

Cuando el usuario nombra un lugar puntual y no una zona ("Volcan de Izalco"),
se cae a la busqueda por nombre sobre el catalogo, que tolera errores de
escritura con trigramas.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.places import PlaceHit, search_by_name


@dataclass(frozen=True)
class Zone:
    """Una zona turistica con su centro y su radio util."""

    key: str
    name: str
    lat: float
    lon: float
    radius_m: int
    aliases: tuple[str, ...] = field(default=())


# Las coordenadas se comprueban contra el catalogo en los tests: una zona cuyo
# punto este mal no va a tener lugares alrededor y el test lo canta. Es mas
# fiable que revisarlas a ojo en un mapa.
ZONES: tuple[Zone, ...] = (
    Zone("san-salvador", "San Salvador", 13.6929, -89.2182, 15_000, ("capital",)),
    Zone("santa-ana", "Santa Ana", 13.9942, -89.5597, 25_000),
    Zone(
        "ataco",
        "Concepcion de Ataco",
        13.8697,
        -89.8467,
        20_000,
        ("ruta de las flores", "ruta de la flores", "las flores"),
    ),
    Zone("juayua", "Juayua", 13.8414, -89.7461, 12_000),
    Zone("apaneca", "Apaneca", 13.8547, -89.8036, 12_000),
    Zone("nahuizalco", "Nahuizalco", 13.7789, -89.7375, 10_000),
    Zone("suchitoto", "Suchitoto", 13.9356, -89.0272, 15_000),
    Zone("sonsonate", "Sonsonate", 13.7189, -89.7242, 15_000),
    Zone("ahuachapan", "Ahuachapan", 13.9214, -89.8450, 15_000),
    Zone(
        "la-libertad",
        "La Libertad",
        13.4883,
        -89.3222,
        20_000,
        ("puerto de la libertad",),
    ),
    Zone("el-tunco", "Playa El Tunco", 13.4936, -89.3819, 15_000, ("el tunco", "tunco")),
    Zone("el-zonte", "Playa El Zonte", 13.4936, -89.4400, 12_000, ("el zonte",)),
    Zone("costa-del-sol", "Costa del Sol", 13.3167, -88.9167, 20_000),
    Zone("san-miguel", "San Miguel", 13.4833, -88.1833, 20_000),
    Zone("metapan", "Metapan", 14.3333, -89.4500, 25_000),
    Zone("la-palma", "La Palma", 14.3167, -89.1667, 15_000),
    Zone("alegria", "Alegria", 13.5069, -88.4897, 12_000),
    Zone("perquin", "Perquin", 13.9564, -88.1583, 15_000),
    Zone(
        "coatepeque",
        "Lago de Coatepeque",
        13.8667,
        -89.5500,
        15_000,
        ("coatepeque", "lago coatepeque"),
    ),
    Zone(
        "cerro-verde",
        "Cerro Verde",
        13.8258,
        -89.6314,
        18_000,
        ("volcan de izalco", "izalco", "santa ana volcan"),
    ),
)


@dataclass
class ResolvedArea:
    """Donde centrar la busqueda, y de donde salio ese punto."""

    name: str
    lat: float
    lon: float
    radius_m: int
    # "zone" si vino del nomenclator, "catalog" si de la busqueda por nombre.
    source: str


def _normalize(texto: str) -> str:
    """Sin acentos, sin mayusculas y sin espacios de sobra.

    La gente escribe "Ahuachapan" y "Ahuachapán", y en el chat casi siempre lo
    primero.
    """
    sin_acentos = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(c for c in sin_acentos if not unicodedata.combining(c))
    return " ".join(sin_acentos.lower().split())


def find_zone(texto: str) -> Zone | None:
    """La zona que corresponde al texto, si alguna.

    Primero coincidencia exacta y despues por contencion, para que "quiero ir
    a Suchitoto" encuentre Suchitoto sin que haya que limpiar la frase antes.
    Entre varias contenidas gana la de nombre mas largo: "playa el tunco" es
    mas especifico que "tunco" y describe mejor lo que se pidio.
    """
    objetivo = _normalize(texto)
    if not objetivo:
        return None

    candidatas: list[tuple[int, Zone]] = []

    for zona in ZONES:
        for nombre in (zona.name, zona.key.replace("-", " "), *zona.aliases):
            normalizado = _normalize(nombre)
            if not normalizado:
                continue
            if objetivo == normalizado:
                return zona
            if normalizado in objetivo:
                candidatas.append((len(normalizado), zona))

    if not candidatas:
        return None
    return max(candidatas, key=lambda par: par[0])[1]


# Un centro de viaje tiene que ser un destino. Un restaurante o un hotel se
# llaman como el lugar donde estan —"Pizza Hut La Gran Via"— y con busqueda por
# trigramas ganan facil, pero nadie planea tres dias alrededor de una pizzeria.
CATEGORIAS_NO_ANCLABLES = {"food", "lodging"}

# La busqueda por nombre tolera errores de escritura, y esa tolerancia con un
# umbral bajo convierte cualquier frase en un lugar. Para anclar un viaje entero
# se pide mas parecido que para buscar un punto en el mapa.
MIN_SIMILARITY_ANCLA = 0.45


def resolve_area(
    db: Session, texto: str, *, default_radius_m: int = 15_000
) -> ResolvedArea | None:
    """Convierte lo que dijo el usuario en un centro de busqueda.

    El nomenclator manda sobre el catalogo. Si alguien dice "Santa Ana" quiere
    la ciudad, no el primer POI que se llame parecido, y con trigramas eso
    podria ser cualquier cosa.

    **Del catalogo solo se aceptan destinos.** Un pedido de "cerca de La Gran
    Via" llego a centrar un viaje de tres dias en un Pizza Hut: el local se
    llama como la zona, gano la busqueda por nombre, y el itinerario salio
    titulado con una pizzeria. Los negocios de comida y los hoteles se llaman
    como el sitio donde estan, asi que son justo los peores candidatos a ancla
    aunque sean los que mejor coinciden.

    Cuando no queda nada aceptable se devuelve None, y quien llama enumera las
    zonas que si conoce. Decir "no conozco esa zona" es mejor que elegir mal.
    """
    zona = find_zone(texto)
    if zona is not None:
        return ResolvedArea(
            name=zona.name,
            lat=zona.lat,
            lon=zona.lon,
            radius_m=zona.radius_m,
            source="zone",
        )

    hits: list[PlaceHit] = search_by_name(
        db, texto, limit=8, min_similarity=MIN_SIMILARITY_ANCLA
    )
    anclables = [h for h in hits if h.category not in CATEGORIAS_NO_ANCLABLES]
    if not anclables:
        return None

    lugar = anclables[0]
    return ResolvedArea(
        name=lugar.name,
        lat=lugar.lat,
        lon=lugar.lon,
        radius_m=default_radius_m,
        source="catalog",
    )


def zone_names() -> list[str]:
    """Los nombres que el modelo puede usar. Va dentro del prompt."""
    return [z.name for z in ZONES]
