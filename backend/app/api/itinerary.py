"""Endpoint del planificador.

Convierte el schema de entrada en las restricciones del motor, arma el
itinerario y lo devuelve junto con lo que no se pudo cumplir.

**Las violaciones viajan en la respuesta con codigo 200, no como error.** Un
itinerario que respeta cinco restricciones de seis es util y el usuario decide
si le sirve; devolver un 422 lo tiraria entero y no le diria mas. El motor ya
esta escrito para informar en vez de ocultar, y la API mantiene ese trato.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas import (
    DayOut,
    ItineraryOut,
    ItineraryRequest,
    PlaceOut,
    StopOut,
    TravelSourceOut,
    ViolationOut,
)
from app.services import itinerary as motor
from app.services.routing import client_from_settings

router = APIRouter(prefix="/itinerary", tags=["itinerary"])


def _to_constraints(peticion: ItineraryRequest) -> motor.Constraints:
    return motor.Constraints(
        days=peticion.days,
        center_lat=peticion.center_lat,
        center_lon=peticion.center_lon,
        radius_m=peticion.radius_m,
        earliest_start=peticion.earliest_start,
        latest_end=peticion.latest_end,
        max_travel_km_per_day=peticion.max_travel_km_per_day,
        mode=peticion.mode,
        preferred_categories=list(peticion.preferred_categories),
        avoided_categories=list(peticion.avoided_categories),
        include_meals=peticion.include_meals,
        max_stops_per_day=peticion.max_stops_per_day,
        min_quality=peticion.min_quality,
    )


def _to_stop(parada: motor.Stop) -> StopOut:
    lugar = parada.place
    return StopOut(
        place=PlaceOut(
            id=lugar.id,
            name=lugar.name,
            category=lugar.category,
            subcategory=lugar.subcategory,
            lat=lugar.lat,
            lon=lugar.lon,
            quality_score=lugar.quality_score,
        ),
        arrival=parada.arrival,
        departure=parada.departure,
        travel_minutes_from_previous=parada.travel_minutes_from_previous,
        travel_km_from_previous=parada.travel_km_from_previous,
        meal=parada.meal,
    )


def _to_travel_source(stats) -> TravelSourceOut:
    """Traduce las estadisticas de la matriz, o dice que todo fue estimado."""
    cliente = client_from_settings()
    restante = cliente.quota.remaining if cliente else None

    if stats is None:
        return TravelSourceOut(source="estimated", quota_remaining=restante)

    reales = stats.cached + stats.fetched
    if not reales:
        origen = "estimated"
    elif stats.estimated:
        origen = "mixed"
    else:
        origen = "real"

    return TravelSourceOut(
        source=origen,
        cached=stats.cached,
        fetched=stats.fetched,
        estimated=stats.estimated,
        real_ratio=round(stats.real_ratio, 3),
        requests=stats.requests,
        quota_remaining=restante,
    )


def _to_out(itinerario: motor.Itinerary, stats) -> ItineraryOut:
    return ItineraryOut(
        days=[
            DayOut(
                number=dia.number,
                stops=[_to_stop(p) for p in dia.stops],
                travel_km=dia.travel_km,
                start=dia.start,
                end=dia.end,
            )
            for dia in itinerario.days
        ],
        violations=[
            ViolationOut(constraint=v.constraint, day=v.day, detail=v.detail)
            for v in itinerario.violations
        ],
        satisfies_all_constraints=itinerario.satisfies_all_constraints,
        total_stops=itinerario.total_stops,
        unused_candidates=itinerario.unused_candidates,
        travel=_to_travel_source(stats),
    )


@router.post("", response_model=ItineraryOut)
def build(peticion: ItineraryRequest, db: Session = Depends(get_db)) -> ItineraryOut:
    """Arma un itinerario que respeta las restricciones dadas.

    Con `real_routes` las distancias salen de OpenRouteService y de la cache;
    sin el, de la estimacion geodesica calibrada. En ninguno de los dos casos
    falla por quedarse sin cupo: degrada y lo dice en `travel`.
    """
    restricciones = _to_constraints(peticion)

    if not peticion.real_routes:
        return _to_out(motor.plan(db, restricciones), None)

    itinerario, stats = motor.plan_with_routing(db, restricciones)
    return _to_out(itinerario, stats)
