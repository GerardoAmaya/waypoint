"""Endpoints de consulta del catalogo."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Category
from app.schemas import CatalogStats, PlaceField, PlaceList, PlaceOut
from app.services import places as servicio

router = APIRouter(prefix="/places", tags=["places"])


def _to_list(hits) -> PlaceList:
    return PlaceList(
        items=[
            PlaceOut(
                id=h.id,
                name=h.name,
                category=h.category,
                subcategory=h.subcategory,
                lat=h.lat,
                lon=h.lon,
                quality_score=h.quality_score,
                distance_m=h.distance_m,
            )
            for h in hits
        ],
        total=len(hits),
    )


@router.get("/nearby", response_model=PlaceList)
def nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_m: int = Query(default=5_000, ge=1, le=100_000),
    categories: list[Category] | None = Query(default=None),
    include_lodging: bool = Query(default=False),
    min_quality: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PlaceList:
    """Lugares dentro de un radio, del mas cercano al mas lejano.

    El alojamiento queda fuera salvo que se pida: donde dormir es otra decision
    y mezclarlo ensucia la seleccion de destinos.
    """
    return _to_list(
        servicio.search_nearby(
            db,
            lat,
            lon,
            radius_m=radius_m,
            categories=categories,
            include_lodging=include_lodging,
            min_quality=min_quality,
            limit=limit,
        )
    )


@router.get("/area", response_model=PlaceList)
def area(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_m: int = Query(default=15_000, ge=1, le=100_000),
    categories: list[Category] | None = Query(default=None),
    include_lodging: bool = Query(default=False),
    min_quality: float = Query(default=0.0, ge=0.0, le=1.0),
    per_category: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> PlaceList:
    """Los mejores de cada categoria en la zona.

    Es la consulta que alimenta al planificador: ordenar solo por distancia
    devolveria veinte restaurantes de la misma cuadra y ningun mirador.
    """
    return _to_list(
        servicio.search_in_area(
            db,
            lat,
            lon,
            radius_m=radius_m,
            categories=categories,
            include_lodging=include_lodging,
            min_quality=min_quality,
            per_category=per_category,
        )
    )


@router.get("/search", response_model=PlaceList)
def search(
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=10, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PlaceList:
    """Busca por nombre tolerando errores de escritura."""
    return _to_list(servicio.search_by_name(db, q, limit=limit))


@router.get("/field", response_model=PlaceField)
def field(db: Session = Depends(get_db)) -> PlaceField:
    """Solo las coordenadas de todo el catalogo activo.

    Alimenta el estado vacio del mapa: antes de que el usuario escriba nada, se
    ven los lugares del pais como puntos tenues. No es decoracion, es una foto
    del material disponible.

    Van como pares [lat, lon] redondeados a cuatro decimales —unos once metros,
    de sobra para un punto de dos pixeles— y no como objetos con nombre y
    categoria. Con cinco mil seiscientos lugares, la diferencia entre un arreglo
    de pares y un arreglo de objetos es de cientos de kilobytes que el cliente
    no dibuja.
    """
    filas = db.execute(text("SELECT lat, lon FROM places WHERE is_active")).all()

    return PlaceField(
        points=[[round(f.lat, 4), round(f.lon, 4)] for f in filas],
        total=len(filas),
    )


@router.get("/stats", response_model=CatalogStats)
def stats(db: Session = Depends(get_db)) -> CatalogStats:
    return CatalogStats(**servicio.catalog_stats(db))
