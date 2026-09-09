"""Schemas de la API.

Separados de los modelos ORM para que la base pueda cambiar de forma sin
romper el contrato que consume el frontend.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models import Category


class PlaceOut(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    subcategory: str | None = None
    lat: float
    lon: float
    quality_score: float
    # Presente solo en busquedas con un punto de referencia.
    distance_m: float | None = None


class PlaceList(BaseModel):
    items: list[PlaceOut]
    total: int


class CatalogStats(BaseModel):
    active: int
    downloaded: int
    duplicates: int
    by_category: dict[str, int]


class NearbyQuery(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=5_000, ge=1, le=100_000)
    categories: list[Category] | None = None
    include_lodging: bool = False
    min_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=200)
