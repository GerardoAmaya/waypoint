"""Consultas espaciales sobre el catalogo.

Todo el trabajo geografico se hace en SQL con PostGIS. Traer filas a Python
para calcular distancias obligaria a leer la tabla entera en cada consulta; con
el indice GiST, Postgres descarta casi todo antes de medir nada.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Category

# El alojamiento se excluye por defecto de las busquedas de destinos. Es el 9%
# del catalogo y responde a otra decision del viajero: donde dormir no compite
# con que visitar, y mezclarlos ensucia la seleccion del itinerario.
DEFAULT_EXCLUDED = (Category.lodging,)

MAX_LIMIT = 200
MAX_RADIUS_M = 100_000


@dataclass
class PlaceHit:
    id: uuid.UUID
    name: str
    category: str
    subcategory: str | None
    lat: float
    lon: float
    quality_score: float
    distance_m: float | None = None
    tags: dict | None = None


# Cocina en castellano. OSM la escribe en ingles y con guiones bajos, y
# "regional;pupusa" es un valor perfectamente valido: hay que partirlo.
_COCINAS = {
    "pupusa": "pupusas",
    "pupuseria": "pupusas",
    "regional": "comida típica",
    "local": "comida típica",
    "latin_american": "latinoamericana",
    "central_american": "centroamericana",
    "mexican": "mexicana",
    "italian": "italiana",
    "pizza": "pizza",
    "burger": "hamburguesas",
    "chicken": "pollo",
    "seafood": "mariscos",
    "fish": "pescado",
    "steak_house": "carnes",
    "barbecue": "parrilla",
    "grill": "parrilla",
    "chinese": "china",
    "japanese": "japonesa",
    "sushi": "sushi",
    "asian": "asiática",
    "american": "americana",
    "international": "internacional",
    "coffee_shop": "café",
    "cafe": "café",
    "bakery": "panadería",
    "ice_cream": "helados",
    "dessert": "postres",
    "sandwich": "sándwiches",
    "breakfast": "desayunos",
    "vegetarian": "vegetariana",
    "vegan": "vegana",
    "spanish": "española",
    "peruvian": "peruana",
    "argentinian": "argentina",
    "brazilian": "brasileña",
    "french": "francesa",
    "indian": "india",
    "thai": "tailandesa",
    "turkish": "turca",
    "greek": "griega",
}


# "regional" y "local" son ciertos y no dicen nada. Cuando vienen junto a algo
# concreto —y "regional;pupusa" es de los valores mas frecuentes del catalogo—
# manda lo concreto: "pupusas" ayuda a elegir donde almorzar y "comida tipica"
# no.
_COCINAS_GENERICAS = frozenset({"regional", "local"})


def cocina_legible(tags: dict | None) -> str | None:
    """La cocina de un comedor, en castellano y en una sola etiqueta.

    Solo traduce lo que conoce, en vez de mostrar el valor crudo de OSM: una
    etiqueta que diga "steak_house" delata la fuente y no ayuda a nadie.
    """
    if not tags:
        return None
    crudo = tags.get("cuisine")
    if not crudo:
        return None

    generica: str | None = None
    for parte in str(crudo).replace(",", ";").split(";"):
        clave = parte.strip().lower().replace(" ", "_")
        if clave not in _COCINAS:
            continue
        if clave in _COCINAS_GENERICAS:
            generica = generica or _COCINAS[clave]
        else:
            return _COCINAS[clave]
    return generica


def altitud_m(tags: dict | None) -> int | None:
    """La altitud en metros, si OSM la trae y es un numero creible.

    El valor de `ele` es texto libre: llega "1965", "1965 m" y alguna vez algo
    que no es un numero. El punto mas alto de El Salvador son 2.730 m, asi que
    cualquier cosa por encima es un error de captura y no un dato.
    """
    if not tags:
        return None
    crudo = str(tags.get("ele") or "").strip().lower().removesuffix("m").strip()
    try:
        valor = round(float(crudo.replace(",", ".")))
    except ValueError:
        return None
    return valor if 0 <= valor <= 2800 else None


def contacto(tags: dict | None, campo: str) -> str | None:
    """Telefono o sitio web. OSM los escribe con y sin el prefijo contact:.

    Cuando hay varios se manda el primero: tres numeros no caben en el panel y
    el primero es el que la gente pone de principal.

    El separador oficial de OSM es el punto y coma, pero en telefonos aparece
    la coma con la misma frecuencia —"2121-2828, 2312-7228"— y sin partirla se
    mostrarian los dos numeros pegados como si fueran uno. En las direcciones
    web no se parte por coma: es un caracter valido en una URL y partir ahi
    romperia el enlace.
    """
    if not tags:
        return None
    valor = tags.get(campo) or tags.get(f"contact:{campo}")
    if not valor:
        return None

    texto = str(valor)
    if campo == "phone":
        texto = texto.replace(",", ";")
    return texto.split(";")[0].strip() or None


# Nexos que en un nombre propio castellano van en minuscula salvo al principio.
#
# Solo nexos, NO articulos: en el nombre de un negocio el articulo es parte del
# nombre —"Restaurante El Amate" y no "Restaurante el Amate"— mientras que "de"
# y "y" nunca se escriben en mayuscula en medio.
_NEXOS = frozenset(
    {"a", "al", "con", "de", "del", "e", "en", "o", "para", "por", "sin", "sobre", "u", "y"}
)


def _es_sigla(palabra: str) -> bool:
    """Si una palabra corta en mayusculas parece sigla y no palabra.

    La longitud sola no sirve: "DON" tiene tres letras y es una palabra. Sin
    vocales no se puede pronunciar, y eso si distingue "SV" o "TV" de "DON".
    """
    return 2 <= len(palabra) <= 3 and palabra.isalpha() and not set(palabra) & set("AEIOU")


def nombre_legible(nombre: str) -> str:
    """El nombre del lugar como se muestra, no como lo escribio OSM.

    OSM es texto libre y en el catalogo cargado hay 55 nombres enteros en
    mayusculas, 17 que terminan en puntuacion y algunos con espacios dobles.
    Puestos en un itinerario se leen como un grito o como un error: en una
    captura real salio "COMIDA A LA VISTA Y PUPUSERIA." entre paradas normales.

    **Se corrige al mostrar y no en el catalogo.** El catalogo guarda lo que
    dice OSM, que es la fuente; reescribirlo ahi perderia el original y haria
    que una recarga del catalogo deshiciera el arreglo.

    **Solo se rebaja lo que es seguro.** Una palabra sola en mayusculas puede
    ser una sigla —ISEADE-FEPADE, ANDEN— y convertirla en "Iseade-Fepade"
    empeora el nombre en vez de arreglarlo, asi que se rebaja unicamente cuando
    hay dos palabras o mas. Dentro del nombre, una palabra corta se conserva en
    mayusculas solo si no tiene vocales: "SV" se queda y "DON" no, porque la
    longitud sola confundia siglas con palabras.
    """
    limpio = " ".join(nombre.split()).rstrip(".,;:")

    palabras = limpio.split(" ")
    if len(palabras) > 1 and limpio == limpio.upper():
        salida = []
        for indice, palabra in enumerate(palabras):
            bajado = palabra.lower()
            # El nexo se comprueba ANTES de la sigla: "Y" no tiene vocales y la
            # prueba de sigla la daba por buena, asi que quedaba "Cafe Y Pan".
            if indice > 0 and bajado in _NEXOS:
                salida.append(bajado)
            elif indice > 0 and _es_sigla(palabra):
                salida.append(palabra)
            else:
                salida.append(bajado.capitalize())
        limpio = " ".join(salida)

    return limpio or nombre


def _row_to_hit(row) -> PlaceHit:
    return PlaceHit(
        id=row.id,
        name=row.name,
        category=row.category,
        subcategory=row.subcategory,
        lat=row.lat,
        lon=row.lon,
        quality_score=row.quality_score,
        distance_m=round(row.distance_m, 1) if getattr(row, "distance_m", None) else None,
        tags=getattr(row, "tags", None),
    )


def _category_filter(
    categories: list[Category] | None, include_lodging: bool
) -> tuple[str, dict]:
    """Arma la clausula de categoria y sus parametros.

    Si se piden categorias explicitas se respetan tal cual, incluso lodging:
    pedir alojamiento a proposito es distinto de que se cuele en una busqueda
    de destinos.
    """
    if categories:
        return "AND p.category = ANY(:categories)", {
            "categories": [c.value for c in categories]
        }
    if include_lodging:
        return "", {}
    return "AND p.category <> ALL(:excluded)", {
        "excluded": [c.value for c in DEFAULT_EXCLUDED]
    }


def search_nearby(
    db: Session,
    lat: float,
    lon: float,
    *,
    radius_m: int = 5_000,
    categories: list[Category] | None = None,
    include_lodging: bool = False,
    min_quality: float = 0.0,
    limit: int = 20,
) -> list[PlaceHit]:
    """Lugares dentro de un radio, del mas cercano al mas lejano.

    ST_DWithin usa el indice espacial; calcular la distancia con ST_Distance en
    el WHERE lo desactivaria y forzaria un recorrido completo de la tabla.

    El punto se convierte con ST_GeogFromText y no con `:punto::geography`: el
    operador :: de PostgreSQL colisiona con la sintaxis de parametros de
    SQLAlchemy y el parametro queda sin sustituir.
    """
    radius_m = min(max(radius_m, 1), MAX_RADIUS_M)
    limit = min(max(limit, 1), MAX_LIMIT)

    clausula, parametros = _category_filter(categories, include_lodging)

    filas = db.execute(
        text(f"""
            SELECT p.id, p.name, p.category::text AS category, p.subcategory,
                   p.lat, p.lon, p.quality_score, p.tags,
                   ST_Distance(p.geom, ST_GeogFromText(:punto)) AS distance_m
            FROM places p
            WHERE p.is_active
              AND p.quality_score >= :min_quality
              AND ST_DWithin(p.geom, ST_GeogFromText(:punto), :radius)
              {clausula}
            ORDER BY p.geom <-> ST_GeogFromText(:punto)
            LIMIT :limit
        """),
        {
            "punto": f"SRID=4326;POINT({lon} {lat})",
            "radius": radius_m,
            "min_quality": min_quality,
            "limit": limit,
            **parametros,
        },
    ).all()

    return [_row_to_hit(f) for f in filas]


def search_by_name(
    db: Session,
    query: str,
    *,
    limit: int = 10,
    min_similarity: float = 0.3,
) -> list[PlaceHit]:
    """Busca por nombre tolerando errores de escritura.

    Los nombres de OSM vienen con variaciones y los usuarios escriben "izalco"
    esperando encontrar "Volcán de Izalco". Los trigramas resuelven ambas cosas
    con el mismo indice que usa la deduplicacion.
    """
    limit = min(max(limit, 1), MAX_LIMIT)

    filas = db.execute(
        text("""
            SELECT p.id, p.name, p.category::text AS category, p.subcategory,
                   p.lat, p.lon, p.quality_score, p.tags
            FROM places p
            WHERE p.is_active
              AND similarity(p.name, :query) >= :min_similarity
            ORDER BY similarity(p.name, :query) DESC, p.quality_score DESC
            LIMIT :limit
        """),
        {"query": query, "min_similarity": min_similarity, "limit": limit},
    ).all()

    return [_row_to_hit(f) for f in filas]


# Cuanto tiene que despegarse el primero del segundo para darlo por bueno.
#
# **Sin margen, buscar "Galerias" elegiria entre dos empatados a 1.00**: el
# centro comercial y un local de comida rapida que esta adentro. Elegir uno de
# los dos por su calidad seria exactamente la sustitucion silenciosa que el
# resto del modulo evita. Con margen, un empate se declara ambiguo y quien
# llama lo dice en vez de adivinar.
#
# Una decima esta medido sobre los casos reales: los que despegan lo hacen por
# 0,25 o mas —Multiplaza 0,36, Volcan de Santa Ana 0,35, Las Cascadas 0,25— y
# los ambiguos empatan en 0,00 o quedan en 0,05. No hay nada en la franja.
MARGEN_DE_DESEMPATE = 0.10

# Cuanto tiene que encajar el nombre buscado dentro del encontrado.
#
# **El margen protege de los empates y no de un mal candidato solitario.** El
# caso que lo enseño: "Hotel California de Santa Ana" no esta en el catalogo;
# al quitarle la zona queda "hotel california de", y eso pesca "Parque Central
# de California" —por la palabra California— sin que nadie le dispute el
# puesto, asi que el margen lo daba por bueno.
#
# Medido sobre los aciertos y los fallos conocidos, la señal que los separa es
# esta: los aciertos encajan enteros, con 1,00, y los fallos se quedan por
# debajo. "las cascadas" contra "7 cascadas" da 0,75; "hotel california de"
# contra "Parque Central de California", 0,70. Los unicos fallos que llegan a
# 1,00 son empates —"galerias" contra el centro comercial y contra un local de
# comida rapida— y de esos se encarga el margen.
#
# Se pide 0,95 y no 1,00 exacto para no depender de como redondea el indice de
# trigramas. Exigir que encaje entero no deja fuera los errores de escritura:
# de esos se encarga la primera pasada, que compara las cadenas completas.
ENCAJE_MINIMO = 0.95

# Cuanto tiene que encajar para merecer al menos una sugerencia.
#
# Mas bajo que ENCAJE_MINIMO —sugerir es mas barato que elegir— pero no tanto
# como el umbral de busqueda: con 0,6, a quien escribia "Hotel California de
# Santa Ana" se le proponia "Parque Central de California", que es justo el
# candidato que acababamos de rechazar por malo. Una sugerencia equivocada es
# peor que ninguna, porque manda a la persona a escribir un nombre que no
# queria.
ENCAJE_PARA_SUGERIR = 0.80

# Un nombre practicamente igual al buscado: gana sin mirar nada mas.
#
# Es lo que deja pasar los errores de escritura. "Volcan de Sant Ana" contra
# "Volcán de Santa Ana" son 0,86; el siguiente candidato, 0,50.
CASI_EXACTO = 0.85

# Por debajo de esto no se mira siquiera. Es el umbral de la busqueda, no el de
# la decision: sirve para traer candidatos que luego se filtran.
MIN_SIMILARITY_BUSQUEDA = 0.6

# Quitar las tildes para comparar, sin depender de la extension `unaccent`.
#
# **La primera version creaba esa extension en una migracion, y eso podia tirar
# el sitio.** Las migraciones corren al arrancar el contenedor —ver
# backend/start.sh, que explica por que no van en el preDeployCommand de
# Railway—, asi que un `CREATE EXTENSION` sin permisos en el Postgres
# administrado no seria un fallo de busqueda: seria un contenedor que no
# levanta.
#
# `translate` mapea caracter a caracter y no necesita nada instalado. Es exacto
# para lo que hay: comparado con la extension sobre los 5.786 lugares activos
# del catalogo coinciden 5.785, y el unico que difiere es "¡Hey Cipote!", que no
# cambia ninguna busqueda.
#
# La comilla tipografica entra aunque no sea una tilde, y paga sola: el catalogo
# trae "Oma’s Coffee Shop" con la comilla curva de OpenStreetMap y nadie la
# teclea.
#
# Un caracter nuevo que no este aqui no rompe nada: esa busqueda queda un poco
# peor, no falla.
CON_TILDES = "áàâäãåçéèêëíìîïñóòôöõúùûüýÿ’¡¿"
SIN_TILDES = "aaaaaaceeeeiiiinooooouuuuyy'!?"


def _literal(texto: str) -> str:
    """Un literal de texto para SQL, con las comillas simples escapadas.

    Hace falta porque SIN_TILDES lleva una comilla simple —la comilla
    tipografica se convierte en la recta— y sin escaparla cierra la cadena
    antes de tiempo. Son constantes del modulo y no entrada de nadie, asi que
    esto es correccion, no defensa.
    """
    escapado = texto.replace("'", "''")
    return f"'{escapado}'"


def _llano(columna: str) -> str:
    """La expresion SQL que normaliza un texto antes de compararlo."""
    return f"translate(lower({columna}), {_literal(CON_TILDES)}, {_literal(SIN_TILDES)})"


_CONSULTA = _llano(":query")
_NOMBRE = _llano("name")
_NOMBRE_P = _llano("p.name")


@dataclass(frozen=True)
class Candidato:
    """Un lugar que podria ser el que se busca, con las dos medidas que lo dicen.

    Las dos hacen falta y miden cosas distintas. `parecido` compara las cadenas
    enteras y es lo que aguanta los errores de escritura: "Volcan de Sant Ana"
    saca 0,86 contra el nombre correcto. `encaje` busca el mejor tramo de
    palabras DENTRO del nombre y es lo que encuentra el nombre corto de un
    sitio: "Multiplaza" saca 1,00 dentro de "Centro Comercial Multiplaza",
    donde el parecido se queda en 0,41 porque el resto del texto cuenta como
    diferencia.
    """

    hit: PlaceHit
    parecido: float
    encaje: float


def search_candidates(db: Session, query: str, *, limit: int = 8) -> list[Candidato]:
    """Los lugares que se parecen al texto, por cualquiera de las dos medidas.

    Ordenados por encaje y despues por parecido. **No decide nada**: quien
    llama aplica elegir(), porque un nombre generico como "Museo" encaja
    perfecto en veinte lugares y ahi no hay nada que elegir.
    """
    limit = min(max(limit, 1), MAX_LIMIT)

    filas = db.execute(
        text(f"""
            SELECT p.id, p.name, p.category::text AS category, p.subcategory,
                   p.lat, p.lon, p.quality_score, p.tags,
                   similarity({_NOMBRE_P}, {_CONSULTA}) AS parecido,
                   word_similarity({_CONSULTA}, {_NOMBRE_P}) AS encaje
            FROM places p
            WHERE p.is_active
              AND (similarity({_NOMBRE_P}, {_CONSULTA}) >= :minimo
                   OR word_similarity({_CONSULTA}, {_NOMBRE_P}) >= :minimo)
            ORDER BY encaje DESC, parecido DESC, p.quality_score DESC
            LIMIT :limit
        """),
        {"query": query, "minimo": MIN_SIMILARITY_BUSQUEDA, "limit": limit},
    ).all()

    return [Candidato(_row_to_hit(f), f.parecido, f.encaje) for f in filas]


def elegir(candidatos: list[Candidato]) -> PlaceHit | None:
    """El lugar, o None si no hay uno que se despegue.

    Tres reglas, en orden, y cada una nacio de un fallo concreto:

    1. **Un nombre practicamente igual gana y no se discute.** Es lo que hace
       que los errores de escritura sigan funcionando: "Volcan de Sant Ana"
       contra "Volcán de Santa Ana" son 0,86 de parecido, y ninguna regla de
       encaje deberia poder tumbar eso.

    2. **Si no, manda el encaje y no el parecido.** El fallo: "Las Cascadas"
       devolvia "7 cascadas" —una catarata— porque de cadena entera se parecen
       0,64, mientras "Centro Comercial Las Cascadas" se quedaba en 0,44 por
       ser mas largo. Por encaje es al reves: 1,00 contra 0,75.

    3. **Y el primero tiene que despegarse del segundo.** "Museo" encaja
       perfecto en veinte museos y "Galerias" en el centro comercial y en un
       local de comida rapida que esta adentro. Elegir uno seria la sustitucion
       silenciosa que el resto del modulo evita.

    **El parecido no desempata, y se probo que no debia.** Usarlo de segundo
    criterio elegia sistematicamente el nombre mas corto —de dos que encajan
    igual, gana el que tiene menos texto alrededor— y con eso "Galerias" se iba
    al local de comida rapida en vez del centro comercial. Un empate de encaje
    es un empate de verdad.
    """
    if not candidatos:
        return None

    casi_exacto = max(candidatos, key=lambda c: c.parecido)
    if casi_exacto.parecido >= CASI_EXACTO:
        return casi_exacto.hit

    mejor = candidatos[0]
    if mejor.encaje < ENCAJE_MINIMO:
        return None
    if len(candidatos) == 1:
        return mejor.hit
    return mejor.hit if mejor.encaje - candidatos[1].encaje >= MARGEN_DE_DESEMPATE else None


def suggestions(candidatos: list[Candidato], *, limit: int = 3) -> list[PlaceHit]:
    """Lo que se le muestra a la persona cuando no se pudo decidir.

    Ver ENCAJE_PARA_SUGERIR: el umbral es mas bajo que el de elegir —sugerir es
    mas barato— pero no tanto como el de buscar.
    """
    return [c.hit for c in candidatos if c.encaje >= ENCAJE_PARA_SUGERIR][:limit]


def search_in_area(
    db: Session,
    lat: float,
    lon: float,
    *,
    radius_m: int = 15_000,
    categories: list[Category] | None = None,
    include_lodging: bool = False,
    min_quality: float = 0.0,
    per_category: int = 10,
) -> list[PlaceHit]:
    """Los mejores de cada categoria dentro de un radio.

    Ordenar solo por distancia devolveria veinte restaurantes de la misma
    cuadra. El planificador necesita variedad para armar un dia, asi que se
    reparte el cupo por categoria en vez de dejar que gane la mas numerosa.
    """
    radius_m = min(max(radius_m, 1), MAX_RADIUS_M)
    per_category = min(max(per_category, 1), 50)

    clausula, parametros = _category_filter(categories, include_lodging)

    filas = db.execute(
        text(f"""
            WITH candidatos AS (
                SELECT p.id, p.name, p.category::text AS category, p.subcategory,
                       p.lat, p.lon, p.quality_score, p.tags,
                       ST_Distance(p.geom, ST_GeogFromText(:punto)) AS distance_m,
                       ROW_NUMBER() OVER (
                           PARTITION BY p.category
                           ORDER BY p.quality_score DESC,
                                    ST_Distance(p.geom, ST_GeogFromText(:punto))
                       ) AS puesto
                FROM places p
                WHERE p.is_active
                  AND p.quality_score >= :min_quality
                  AND ST_DWithin(p.geom, ST_GeogFromText(:punto), :radius)
                  {clausula}
            )
            SELECT * FROM candidatos
            WHERE puesto <= :per_category
            ORDER BY category, puesto
        """),
        {
            "punto": f"SRID=4326;POINT({lon} {lat})",
            "radius": radius_m,
            "min_quality": min_quality,
            "per_category": per_category,
            **parametros,
        },
    ).all()

    return [_row_to_hit(f) for f in filas]


def by_ids(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, PlaceHit]:
    """Los lugares activos que correspondan a esos identificadores.

    Devuelve un diccionario y no una lista porque quien llama necesita saber
    cuales faltan. En la revision de un itinerario, un identificador que ya no
    esta en el catalogo no es un detalle: significa que la parada desaparecio
    y hay que decirlo, no omitirla en silencio.
    """
    if not ids:
        return {}

    filas = db.execute(
        text("""
            SELECT p.id, p.name, p.category::text AS category, p.subcategory,
                   p.lat, p.lon, p.quality_score, p.tags
            FROM places p
            WHERE p.is_active AND p.id = ANY(:ids)
        """),
        {"ids": list(ids)},
    ).all()

    return {fila.id: _row_to_hit(fila) for fila in filas}


def distance_between(db: Session, origen: uuid.UUID, destino: uuid.UUID) -> float | None:
    """Distancia en linea recta entre dos lugares del catalogo, en metros.

    Sirve de cota inferior antes de gastar una llamada al servicio de rutas: si
    dos paradas estan a 40 km en linea recta, no hace falta preguntar cuanto se
    tarda caminando.
    """
    return db.execute(
        text("""
            SELECT ST_Distance(a.geom, b.geom)
            FROM places a, places b
            WHERE a.id = :origen AND b.id = :destino
        """),
        {"origen": origen, "destino": destino},
    ).scalar()


def catalog_stats(db: Session) -> dict:
    """Resumen del catalogo para el endpoint de salud y el README."""
    fila = db.execute(
        text("""
            SELECT COUNT(*) FILTER (WHERE is_active) AS activos,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE rejected_reason = 'duplicado') AS duplicados
            FROM places
        """)
    ).one()

    por_categoria = {
        row.category: row.n
        for row in db.execute(
            text("""
                SELECT category::text AS category, COUNT(*) AS n
                FROM places WHERE is_active
                GROUP BY category ORDER BY COUNT(*) DESC
            """)
        )
    }

    return {
        "active": fila.activos,
        "downloaded": fila.total,
        "duplicates": fila.duplicados,
        "by_category": por_categoria,
    }
