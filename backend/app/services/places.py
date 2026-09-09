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
