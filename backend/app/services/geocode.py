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

import re
import unicodedata
from dataclasses import dataclass, field, replace

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.places import (
    PlaceHit,
    pick_unambiguous,
    rank_suggestions,
    search_by_name,
    search_contained_by_name,
)


@dataclass(frozen=True)
class ZonePhoto:
    """Una foto libre de la zona, con lo que su licencia obliga a mostrar.

    `author` y `license` no son opcionales ni decorativos: las imagenes son de
    Wikimedia Commons y sus licencias exigen credito. Guardarlos juntos evita
    que se pueda usar la foto sin la atribucion por descuido.
    """

    file: str
    author: str
    license: str
    page: str


@dataclass(frozen=True)
class Zone:
    """Una zona turistica con su centro y su radio util."""

    key: str
    name: str
    lat: float
    lon: float
    radius_m: int
    aliases: tuple[str, ...] = field(default=())
    photo: ZonePhoto | None = None


# Se resolvieron una vez contra Wikidata (P18) y Wikimedia Commons, y quedan
# fijas. No se consultan en tiempo de ejecucion a proposito: son veinte valores
# que no cambian, y una peticion por itinerario a un tercero solo agrega una
# forma nueva de fallar. Dos zonas se quedaron sin foto libre y eso es correcto:
# la interfaz omite la imagen en vez de inventarla.
#
# P18 en vez de la imagen destacada del articulo: la del articulo sale del
# infobox y a veces es el mapa de situacion del pais. Juayua caia justo en ese
# caso.
FOTOS: dict[str, ZonePhoto] = {
    "san-salvador": ZonePhoto(
        file="World_Trade_Center_San_Salvador.jpg",
        author="JMRAFFi",
        license="CC BY-SA 4.0",
        page="https://commons.wikimedia.org/wiki/File:World_Trade_Center_San_Salvador.jpg",
    ),
    "santa-ana": ZonePhoto(
        file="ES_Santa_Ana_06_2011_2543.jpg",
        author="Mariordo  (Mario Roberto Durán Ortiz)",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:ES_Santa_Ana_06_2011_2543.jpg",
    ),
    "ataco": ZonePhoto(
        file="DESDE_EL_MIRADOR_DE_LA_CRUZ_EN_ATACO,_AHUACHAPAN_-_panoramio.jpg",
        author="feinteriano",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:DESDE_EL_MIRADOR_DE_LA_CRUZ_EN_ATACO,_AHUACHAPAN_-_panoramio.jpg",
    ),
    "juayua": ZonePhoto(
        file="PANORAMICA_PLAZA_CENTRAL_JUAYUA_1.jpg",
        author="ClauH0288",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:PANORAMICA_PLAZA_CENTRAL_JUAYUA_1.jpg",
    ),
    "apaneca": ZonePhoto(
        file="Apaneca_-_panoramio.jpg",
        author="Roberto Alas",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Apaneca_-_panoramio.jpg",
    ),
    "nahuizalco": ZonePhoto(
        file="Iglesia_San_Juan_Bautista_Nahuizalco.JPG",
        author="Efegé",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Iglesia_San_Juan_Bautista_Nahuizalco.JPG",
    ),
    "suchitoto": ZonePhoto(
        file="Iglesia_De_Suchitoto..JPG",
        author="ElmerGuevara",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Iglesia_De_Suchitoto..JPG",
    ),
    "sonsonate": ZonePhoto(
        file="Catedral_de_Sonsonate.jpg",
        author="Stvn87",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Catedral_de_Sonsonate.jpg",
    ),
    "ahuachapan": ZonePhoto(
        file="Ahuachapan_Parroquia_Nuestra_Señora_de_la_Asuncion.jpg",
        author="YessicaGuerra19",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Ahuachapan_Parroquia_Nuestra_Se%C3%B1ora_de_la_Asuncion.jpg",
    ),
    "la-libertad": ZonePhoto(
        file="MALECON_DEL_PUERTO_DE_LA_LIBERTAD._-_panoramio.jpg",
        author="feinteriano",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:MALECON_DEL_PUERTO_DE_LA_LIBERTAD._-_panoramio.jpg",
    ),
    "el-zonte": ZonePhoto(
        file="El_Zonte_(01.2011)_-_panoramio.jpg",
        author="Martin Haeusler",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:El_Zonte_(01.2011)_-_panoramio.jpg",
    ),
    "san-miguel": ZonePhoto(
        file="San_Miguel_El_Salvador.png",
        author="House1090",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:San_Miguel_El_Salvador.png",
    ),
    "metapan": ZonePhoto(
        file="Iglesia_Colonial_Metapan.jpg",
        author="Alex Martínez",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Iglesia_Colonial_Metapan.jpg",
    ),
    "la-palma": ZonePhoto(
        file="Entrada_de_La_Palma.JPG",
        author="Beatriz Fortinez",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Entrada_de_La_Palma.JPG",
    ),
    "alegria": ZonePhoto(
        file="Alegría,_El_Salvador,_Iglesia_(12-2010)_-_panoramio.jpg",
        author="Martin Haeusler",
        license="CC BY-SA 3.0",
        page="https://commons.wikimedia.org/wiki/File:Alegr%C3%ADa,_El_Salvador,_Iglesia_(12-2010)_-_panoramio.jpg",
    ),
    "perquin": ZonePhoto(
        file="A_street_view-PICT0024.jpg",
        author="Jose Huwaidi",
        license="CC BY-SA 4.0",
        page="https://commons.wikimedia.org/wiki/File:A_street_view-PICT0024.jpg",
    ),
    "coatepeque": ZonePhoto(
        file="Coatepeque_Vista1.jpg",
        author="JMRAFFi",
        license="CC BY 4.0",
        page="https://commons.wikimedia.org/wiki/File:Coatepeque_Vista1.jpg",
    ),
    "cerro-verde": ZonePhoto(
        file="Cerro_Verde_from_Santa_Ana_Volcano.jpg",
        author="Dead.rabbit",
        license="CC BY-SA 4.0",
        page="https://commons.wikimedia.org/wiki/File:Cerro_Verde_from_Santa_Ana_Volcano.jpg",
    ),
}


# Las coordenadas se comprueban contra el catalogo en los tests: una zona cuyo
# punto este mal no va a tener lugares alrededor y el test lo canta. Es mas
# fiable que revisarlas a ojo en un mapa.
_ZONAS_SIN_FOTO: tuple[Zone, ...] = (
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


# La foto se engancha por clave en vez de escribirse dentro de cada Zone: la
# lista de zonas se lee de un tirón y las fotos se resolvieron aparte.
ZONES: tuple[Zone, ...] = tuple(replace(z, photo=FOTOS.get(z.key)) for z in _ZONAS_SIN_FOTO)


@dataclass
class ResolvedArea:
    """Donde centrar la busqueda, y de donde salio ese punto."""

    name: str
    lat: float
    lon: float
    radius_m: int
    # "zone" si salio de las zonas curadas, "gazetteer" si del nomenclator de
    # OSM, "catalog" si de buscar un punto de interes por nombre.
    source: str
    # Solo las zonas del nomenclator tienen foto. Un ancla que salio del
    # catalogo es un lugar suelto y no una zona con identidad propia.
    photo: ZonePhoto | None = None


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

# Lo mismo para el nomenclator, pero medido: hay dos mil seiscientos nombres, y
# con umbral bajo cualquier palabra encuentra un barrio.
#
# El valor sale de mirar los dos extremos sobre los nombres cargados:
#
#     "Megicanos" -> "Mejicanos"     0.538   <- hay que aceptarlo
#     "volcan"    -> "Volcancillo"   0.462   <- hay que rechazarlo
#     "playa"     -> "Playa El Cuco" 0.429   <- hay que rechazarlo
#
# 0.50 cae en ese hueco: acepta el error de escritura plausible y deja fuera
# las palabras genericas que se parecen a un topominmo por casualidad. El
# margen contra "volcan" es de cuatro centesimas, asi que si se agregan
# nombres al nomenclator conviene volver a medir estos tres casos.
MIN_SIMILARITY_NOMENCLATOR = 0.50

# Cuando un nombre existe en varios niveles a la vez —"San Salvador" es
# departamento, municipio y ciudad— gana el mas especifico. El numero es el
# rango: mas bajo es mas especifico.
#
# Es lo que la gente quiere decir: quien nombra "San Salvador" piensa en la
# ciudad y no en los cuarenta kilometros de radio del departamento, y quien
# quiere el departamento entero lo dice de otra forma. Entre iguales gana el
# que tiene mas destinos cerca, que es el que mas probablemente sea el que
# nombraron.
ORDEN_NOMENCLATOR = {
    "neighbourhood": 0,
    "suburb": 1,
    "admin8": 2,
    "village": 3,
    "town": 4,
    "city": 5,
    "admin6": 6,
    "admin4": 7,
}


def find_place_name(db: Session, texto: str) -> ResolvedArea | None:
    """Busca el texto en el nomenclator de nombres de lugar.

    Tabla propia y no `places`: un nombre de lugar y un punto de interes son
    cosas distintas, y meter dos mil seiscientos nombres de barrio a competir
    por trigramas con los nombres de negocios haria peor las dos busquedas.

    El radio sale del nomenclator y no de un valor por defecto: un departamento
    y un barrio no se recorren igual.
    """
    # El orden de especificidad se arma desde la constante de Python para que
    # no haya dos listas que mantener sincronizadas.
    casos = " ".join(
        f"WHEN '{kind}' THEN {rango}" for kind, rango in ORDEN_NOMENCLATOR.items()
    )

    fila = db.execute(
        text(f"""
            SELECT name, kind, lat, lon, radius_m,
                   similarity(name, :texto) AS parecido,
                   CASE kind {casos} ELSE 99 END AS especificidad
            FROM place_names
            WHERE is_active
              AND similarity(name, :texto) >= :minimo
            ORDER BY parecido DESC, especificidad ASC, destinations_nearby DESC
            LIMIT 1
        """),
        {"texto": texto, "minimo": MIN_SIMILARITY_NOMENCLATOR},
    ).first()

    if fila is None:
        return None

    return ResolvedArea(
        name=fila.name,
        lat=fila.lat,
        lon=fila.lon,
        radius_m=fila.radius_m,
        source="gazetteer",
    )


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
            photo=zona.photo,
        )

    # El nomenclator va antes que el catalogo: "Mejicanos" es un lugar donde
    # la gente vive, y lo unico que el catalogo tiene con ese nombre son cuatro
    # puestos de comida. Preguntar primero por nombres de lugar y despues por
    # puntos de interes es el orden que responde lo que se pregunto.
    del_nomenclator = find_place_name(db, texto)
    if del_nomenclator is not None:
        return del_nomenclator

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


# Parecido minimo para el punto de partida. Mas exigente que para el area:
# equivocar el area da un itinerario en otra ciudad y se nota; equivocar el
# punto de partida da un itinerario que empieza donde el usuario no esta, y eso
# se descubre estando ahi.
#
# El caso que lo justifica es real: "Hotel Barcelo" no esta en el catalogo, y
# con umbral bajo la busqueda difusa devuelve "Hotel La Parcela", que es otro
# sitio a veinte kilometros.
MIN_SIMILARITY_PARTIDA = 0.60


@dataclass
class LugarBuscado:
    """El resultado de buscar un lugar por su nombre.

    Lleva las sugerencias ademas del hallazgo porque **"no lo encontre" a secas
    era un callejon sin salida**. El caso real: alguien escribio "Multiplaza
    San Salvador", el catalogo tiene "Centro Comercial Multiplaza" —activo, a
    dos kilometros de donde esa persona creia—, y la respuesta fue que probara
    con el nombre como aparece en el mapa. No hay forma de adivinar cual es ese
    nombre desde fuera.

    Sugerir no es sustituir: se sigue sin empezar el dia en un lugar que nadie
    nombro, pero ahora se dice cual podria ser.
    """

    hit: PlaceHit | None = None
    sugerencias: list[PlaceHit] = field(default_factory=list)


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()


def _sin_el_nombre_de_la_zona(texto: str) -> str | None:
    """La consulta sin el nombre de zona que la acompaña, o None si no lleva.

    "Multiplaza San Salvador" es un lugar mas una ciudad, y la ciudad ya es un
    concepto aparte en este sistema. Como texto para buscar un nombre propio,
    sobra: los tokens de la ciudad se llevan la busqueda difusa hacia cualquier
    cosa que tambien se llame asi.

    **Es el ultimo recurso y no el primero, y hay dos motivos medidos.**
    "Metrocentro Santa Ana" existe tal cual en el catalogo y recortarlo lo
    volveria ambiguo entre tres Metrocentros; y "Volcan de Santa Ana" recortado
    queda en "volcan de", que se parece igual al Volcan de Izalco. Por eso solo
    se prueba cuando la busqueda de la frase entera ya no encontro nada.
    """
    base = _sin_tildes(texto)
    for zona in sorted(zone_names(), key=len, reverse=True):
        nombre = _sin_tildes(zona)
        if nombre in base and len(base) > len(nombre) + 2:
            recorte = re.sub(r"\s+", " ", base.replace(nombre, " ")).strip(" ,.-")
            if len(recorte) >= 4:
                return recorte
    return None


def buscar_lugar(db: Session, texto: str) -> LugarBuscado:
    """Busca un lugar por su nombre, en cuatro pasadas de menos a mas permisiva.

    1. La busqueda de siempre, por parecido de la cadena entera. Lo que hoy
       funciona sigue exactamente igual.
    2. El nombre contenido dentro de otro mas largo: "Multiplaza" dentro de
       "Centro Comercial Multiplaza". Solo si hay un ganador claro.
    3. Lo mismo quitando el nombre de la zona, que es el ultimo recurso porque
       recortar puede empeorar la busqueda. Ver _sin_el_nombre_de_la_zona.
    4. Nada, pero con sugerencias para que quien pregunta pueda corregir.

    **Cada pasada es mas permisiva y ninguna decide sin margen.** Un nombre
    generico como "Museo" empata con veinte lugares, y ahi no se elige: se
    sugiere.
    """
    hits = search_by_name(db, texto, limit=5, min_similarity=MIN_SIMILARITY_PARTIDA)
    if hits:
        return LugarBuscado(hit=hits[0])

    candidatos = search_contained_by_name(db, texto, limit=5)
    elegido = pick_unambiguous(candidatos, db, texto)
    if elegido is not None:
        return LugarBuscado(hit=elegido)

    recorte = _sin_el_nombre_de_la_zona(texto)
    del_recorte: list[PlaceHit] = []
    if recorte:
        del_recorte = search_contained_by_name(db, recorte, limit=5)
        elegido = pick_unambiguous(del_recorte, db, recorte)
        if elegido is not None:
            return LugarBuscado(hit=elegido)

    # **Las sugerencias salen de las dos busquedas, y las del recorte primero.**
    # A quien escribia "Metrocentro San Salvador" se le ofrecian los
    # Metrocentros de San Miguel y Santa Ana, que son los que se parecen a la
    # frase entera, y no el "Metrocentro" a secas que es el de San Salvador y
    # el que estaba buscando.
    vistos: set = set()
    sugerencias: list[PlaceHit] = []
    for candidato in [*del_recorte, *candidatos]:
        if candidato.id not in vistos:
            vistos.add(candidato.id)
            sugerencias.append(candidato)

    ordenadas = rank_suggestions(db, recorte or texto, sugerencias)
    return LugarBuscado(sugerencias=ordenadas[:3])


def resolve_start_place(db: Session, texto: str) -> PlaceHit | None:
    """El lugar del que sale el dia, buscado por nombre en el catalogo.

    **Aca si valen los comedores y los hoteles**, al contrario que para centrar
    la busqueda. Un Pizza Hut no sirve para decidir en que zona viajar —los
    negocios se llaman como el sitio donde estan y ganan la busqueda difusa sin
    merecerlo— pero es perfectamente valido como punto de partida: es donde la
    persona esta. Son dos papeles distintos del mismo dato.

    Devuelve None cuando no hay nada lo bastante parecido, y quien llama tiene
    que decirlo. Arrancar el dia en un sitio que el usuario no nombro es peor
    que admitir que no se encontro. Para el detalle de las sugerencias,
    buscar_lugar().
    """
    return buscar_lugar(db, texto).hit


def resolve_must_visit(db: Session, texto: str) -> PlaceHit | None:
    """Un lugar que la persona pidio visitar, buscado por nombre.

    Mismo criterio que el punto de partida y por el mismo motivo: con umbral
    bajo, "Jardin Botanico" trae cualquier jardin, y un itinerario que promete
    el lugar que pediste y te lleva a otro es peor que uno que admite no
    haberlo encontrado. Quien llama tiene que decir que no se encontro.
    """
    return buscar_lugar(db, texto).hit


def zone_names() -> list[str]:
    """Los nombres que el modelo puede usar. Va dentro del prompt."""
    return [z.name for z in ZONES]
