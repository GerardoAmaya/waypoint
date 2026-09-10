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

from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import Limit, RateLimiter, limiter_dependency
from app.schemas import (
    AdviceOut,
    DayOut,
    ItineraryOut,
    ItineraryRequest,
    PlaceOut,
    StopOut,
    TravelSourceOut,
    ViolationOut,
)
from app.services import itinerary as motor
from app.services.places import altitud_m, cocina_legible, contacto, nombre_legible
from app.services.places import by_ids as places_by_ids
from app.services.routing import client_from_settings

router = APIRouter(prefix="/itinerary", tags=["itinerary"])

# Sin modelo de por medio es mas barato, pero una zona fria gasta una peticion
# de las cincuenta diarias de OpenRouteService igual.
_limiter = RateLimiter(
    [
        Limit(settings.itinerary_per_minute, 60, "por minuto"),
        Limit(settings.itinerary_per_day, 86_400, "por día"),
    ]
)
limitar = limiter_dependency(_limiter, settings.trust_proxy_header)


def _to_constraints(peticion: ItineraryRequest, db: Session) -> motor.Constraints:
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
        must_include_categories=list(peticion.must_include_categories),
        day_modes={int(numero): modo for numero, modo in peticion.day_modes.items()},
        include_meals=peticion.include_meals,
        must_include_meals=list(peticion.must_include_meals),
        must_include_places=[
            hit for hit in places_by_ids(db, peticion.must_include_place_ids).values()
        ],
        place_minutes=dict(peticion.place_minutes),
        meal_minutes=peticion.meal_minutes,
        category_minutes=dict(peticion.category_minutes),
        max_stops_per_day=peticion.max_stops_per_day,
        min_quality=peticion.min_quality,
        start_place=(
            places_by_ids(db, [peticion.start_place_id]).get(peticion.start_place_id)
            if peticion.start_place_id is not None
            else None
        ),
        return_to_start=peticion.return_to_start,
    )


def _to_stop(
    parada: motor.Stop,
    trazo: list[tuple[float, float]] | None = None,
) -> StopOut:
    lugar = parada.place
    return StopOut(
        place=PlaceOut(
            id=lugar.id,
            name=nombre_legible(lugar.name),
            category=lugar.category,
            subcategory=lugar.subcategory,
            lat=lugar.lat,
            lon=lugar.lon,
            quality_score=lugar.quality_score,
            cuisine=cocina_legible(lugar.tags),
            elevation_m=altitud_m(lugar.tags),
            phone=contacto(lugar.tags, "phone"),
            website=contacto(lugar.tags, "website"),
        ),
        arrival=parada.arrival,
        departure=parada.departure,
        travel_minutes_from_previous=parada.travel_minutes_from_previous,
        travel_km_from_previous=parada.travel_km_from_previous,
        meal=parada.meal,
        geometry_from_previous=trazo,
    )


def _to_travel_source(stats) -> TravelSourceOut:
    """Traduce las estadisticas de la matriz, o dice que todo fue estimado."""
    cliente = client_from_settings()
    # El de la matriz y no "el cupo" a secas: este bloque habla de las
    # distancias, y el trazo por carretera tiene su propio cupo aparte.
    restante = cliente.matrix_quota.remaining if cliente else None

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
        reason=getattr(stats, "reason", None),
        quota_remaining=restante,
    )


def _to_out(
    itinerario: motor.Itinerary,
    stats,
    geometry: dict | None = None,
    constraints: motor.Constraints | None = None,
) -> ItineraryOut:
    """Serializa el itinerario, con el trazo de cada tramo si se pidio.

    `geometry` viene indexado por el par de lugares que une el tramo. Se busca
    por el par y no por posicion porque el mismo par puede aparecer en dos dias
    distintos y su trazo es el mismo.
    """
    trazos = geometry or {}

    return ItineraryOut(
        days=[
            DayOut(
                number=dia.number,
                stops=[
                    _to_stop(
                        parada,
                        trazos.get((anterior.place.id, parada.place.id))
                        if anterior is not None
                        else None,
                    )
                    for anterior, parada in zip([None, *dia.stops], dia.stops, strict=False)
                ],
                travel_km=dia.travel_km,
                start=dia.start,
                end=dia.end,
                mode=(
                    constraints.mode_for(dia.number) if constraints is not None else "driving"
                ),
                visits=(
                    motor.visits_of_day(dia, constraints)
                    if constraints is not None
                    else len(dia.stops)
                ),
            )
            for dia in itinerario.days
        ],
        violations=[
            ViolationOut(constraint=v.constraint, day=v.day, detail=v.detail)
            for v in itinerario.violations
        ],
        advice=[AdviceOut(kind=c.kind, day=c.day, detail=c.detail) for c in itinerario.advice],
        satisfies_all_constraints=itinerario.satisfies_all_constraints,
        total_stops=motor.total_visits(itinerario, constraints),
        unused_candidates=itinerario.unused_candidates,
        travel=_to_travel_source(stats),
    )


@router.post("", response_model=ItineraryOut, dependencies=[Depends(limitar)])
def build(peticion: ItineraryRequest, db: Session = Depends(get_db)) -> ItineraryOut:
    """Arma un itinerario que respeta las restricciones dadas.

    Con `real_routes` las distancias salen de OpenRouteService y de la cache;
    sin el, de la estimacion geodesica calibrada. En ninguno de los dos casos
    falla por quedarse sin cupo: degrada y lo dice en `travel`.
    """
    restricciones = _to_constraints(peticion, db)

    if not peticion.real_routes:
        return _to_out(motor.plan(db, restricciones), None, None, restricciones)

    itinerario, stats = motor.plan_with_routing(db, restricciones)
    return _to_out(itinerario, stats, None, restricciones)
