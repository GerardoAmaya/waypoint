"""Schemas de la API.

Separados de los modelos ORM para que la base pueda cambiar de forma sin
romper el contrato que consume el frontend.
"""

from __future__ import annotations

import uuid
from datetime import time
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


# --------------------------------------------------------------------------
# Itinerarios
# --------------------------------------------------------------------------


class ItineraryRequest(BaseModel):
    """Las restricciones del usuario, ya traducidas a limites verificables.

    En la fase 5 este objeto lo va a llenar el modelo a partir de una frase.
    Que sea un schema explicito y no texto libre es la division de
    responsabilidades del proyecto: el modelo interpreta, el motor cumple.
    """

    days: int = Field(default=1, ge=1, le=7)
    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)

    radius_m: int = Field(default=20_000, ge=1, le=100_000)
    earliest_start: time = time(9, 0)
    latest_end: time = time(20, 0)
    max_travel_km_per_day: float = Field(default=25.0, gt=0, le=500)
    mode: Literal["driving", "walking"] = "driving"

    preferred_categories: list[Category] = Field(default_factory=list)
    avoided_categories: list[Category] = Field(default_factory=list)
    include_meals: bool = True
    max_stops_per_day: int = Field(default=5, ge=1, le=12)
    min_quality: float = Field(default=0.0, ge=0.0, le=1.0)

    # Con rutas reales el itinerario consume cupo de ORS. Se puede apagar para
    # probar o para ahorrar, y la respuesta dice siempre cual se uso.
    real_routes: bool = True

    @model_validator(mode="after")
    def _horario_coherente(self) -> ItineraryRequest:
        if self.earliest_start >= self.latest_end:
            raise ValueError("earliest_start tiene que ser anterior a latest_end")
        if set(self.preferred_categories) & set(self.avoided_categories):
            raise ValueError("una categoria no puede estar preferida y evitada a la vez")
        return self


class StopOut(BaseModel):
    place: PlaceOut
    arrival: time
    departure: time
    travel_minutes_from_previous: int
    travel_km_from_previous: float
    meal: str | None = None


class DayOut(BaseModel):
    number: int
    stops: list[StopOut]
    travel_km: float
    start: time | None = None
    end: time | None = None


class ViolationOut(BaseModel):
    """Una restriccion que no se pudo cumplir.

    Se devuelve en vez de ocultarse. Un itinerario que empieza antes de lo
    pedido es un fallo y el usuario tiene que verlo.
    """

    constraint: str
    day: int | None = None
    detail: str


class TravelSourceOut(BaseModel):
    """De donde salieron las distancias de este itinerario.

    Va en la respuesta a proposito. El usuario ve horas de llegada, y tiene
    derecho a saber si estan medidas sobre carretera o aproximadas desde la
    linea recta.
    """

    # Los contadores en cero son ambiguos: no distinguen "todo estimado" de
    # "no se midio nada". Este campo lo dice sin que haya que deducirlo.
    source: Literal["estimated", "mixed", "real"] = "estimated"
    cached: int = 0
    fetched: int = 0
    estimated: int = 0
    real_ratio: float = 0.0
    quota_remaining: int | None = None


class ItineraryOut(BaseModel):
    days: list[DayOut]
    violations: list[ViolationOut] = Field(default_factory=list)
    satisfies_all_constraints: bool
    total_stops: int
    unused_candidates: int
    travel: TravelSourceOut


# --------------------------------------------------------------------------
# Capa conversacional
# --------------------------------------------------------------------------


class PlanMessage(BaseModel):
    """Lo que el usuario escribe, sin estructura."""

    message: str = Field(min_length=1, max_length=600)


class AreaOut(BaseModel):
    name: str
    lat: float
    lon: float
    radius_m: int
    # "zone" si vino del nomenclator, "catalog" si de la busqueda por nombre.
    source: str


class InterpretationOut(BaseModel):
    """Lo que se entendio de la frase, antes de armar nada.

    `unmapped` y `notes` son la parte importante y no un adorno: dicen que
    quedo afuera y que hubo que recortar. Un planificador que silenciosamente
    ignora la mitad de lo que le pediste es peor que uno que lo admite.
    """

    area: AreaOut | None = None
    constraints: ItineraryRequest | None = None
    unmapped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
