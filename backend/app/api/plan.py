"""Endpoint conversacional.

Recibe una frase y emite por Server-Sent Events lo que va entendiendo y
armando. Las fases son las de `plan_streaming` mas una al principio con la
interpretacion.

**Un error a mitad del flujo viaja como evento, no como codigo HTTP.** Una vez
que empezaron a salir bytes el estado ya se mando, asi que no se puede cambiar
a 500. El cliente escucha el evento `error` igual que los otros.

La sesion de base se abre y se cierra dentro del generador. Con
`Depends(get_db)` el cierre ocurre despues de que la respuesta termina, y en
una respuesta que se transmite eso es una fuente conocida de sesiones colgadas.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.itinerary import _to_out
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.ratelimit import Limit, RateLimiter, limiter_dependency
from app.schemas import (
    AreaOut,
    AreaPhotoOut,
    InterpretationOut,
    PlanMessage,
    ReviseRequest,
    RevisionOut,
)
from app.services import itinerary as motor
from app.services.interpret import interpret, interpret_revision
from app.services.places import by_ids as places_by_ids

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])

# El limite mas estricto del proyecto: estos dos endpoints llaman al modelo.
_limiter = RateLimiter(
    [
        Limit(settings.plan_per_minute, 60, "por minuto"),
        Limit(settings.plan_per_day, 86_400, "por día"),
    ]
)
limitar = limiter_dependency(_limiter, settings.trust_proxy_header)


def _event(nombre: str, datos: dict) -> str:
    """Un evento SSE. El JSON va en una sola linea porque el formato lo exige."""
    return f"event: {nombre}\ndata: {json.dumps(datos, default=str)}\n\n"


def _interpretation_payload(resultado) -> dict:
    salida = InterpretationOut(
        area=(
            AreaOut(
                name=resultado.area.name,
                lat=resultado.area.lat,
                lon=resultado.area.lon,
                radius_m=resultado.area.radius_m,
                source=resultado.area.source,
                photo=(
                    AreaPhotoOut(
                        file=resultado.area.photo.file,
                        author=resultado.area.photo.author,
                        license=resultado.area.photo.license,
                        page=resultado.area.photo.page,
                    )
                    if resultado.area.photo
                    else None
                ),
            )
            if resultado.area
            else None
        ),
        constraints=resultado.request,
        unmapped=resultado.unmapped,
        notes=resultado.notes,
    )
    return salida.model_dump(mode="json")


def _stream(mensaje: str) -> Iterator[str]:
    db = SessionLocal()
    try:
        resultado = interpret(db, mensaje)

        if not resultado.ok:
            # Lo que si se entendio viaja igual: si el usuario tiene que
            # reformular, que no repita todo desde cero.
            yield _event(
                "error",
                {
                    "message": resultado.error,
                    "unmapped": resultado.unmapped,
                    "notes": resultado.notes,
                },
            )
            return

        yield _event("interpretation", _interpretation_payload(resultado))

        restricciones = motor.Constraints(
            days=resultado.request.days,
            center_lat=resultado.request.center_lat,
            center_lon=resultado.request.center_lon,
            radius_m=resultado.request.radius_m,
            earliest_start=resultado.request.earliest_start,
            latest_end=resultado.request.latest_end,
            max_travel_km_per_day=resultado.request.max_travel_km_per_day,
            mode=resultado.request.mode,
            preferred_categories=list(resultado.request.preferred_categories),
            avoided_categories=list(resultado.request.avoided_categories),
            must_include_categories=list(resultado.request.must_include_categories),
            day_modes={
                int(numero): modo for numero, modo in resultado.request.day_modes.items()
            },
            include_meals=resultado.request.include_meals,
            meal_minutes=resultado.request.meal_minutes,
            category_minutes=dict(resultado.request.category_minutes),
            max_stops_per_day=resultado.request.max_stops_per_day,
            min_quality=resultado.request.min_quality,
            start_place=resultado.start_place,
            return_to_start=resultado.return_to_start,
        )

        for evento in motor.plan_streaming(db, restricciones):
            yield _event(evento.phase, _phase_payload(evento, restricciones))

    except Exception:
        logger.exception("fallo armando el itinerario")
        yield _event("error", {"message": "no se pudo armar el itinerario"})
    finally:
        db.close()


def _phase_payload(evento, restricciones: motor.Constraints | None = None) -> dict:
    if isinstance(evento, motor.CandidatesReady):
        # Solo lo que el mapa necesita para dibujar los pines. Mandar el
        # catalogo entero de la zona serian cientos de kilobytes que el cliente
        # descarta.
        return {
            "destinations": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "lat": p.lat,
                    "lon": p.lon,
                    "category": p.category,
                }
                for p in evento.destinations
            ],
            "meals": len(evento.meals),
        }

    if isinstance(evento, motor.DraftReady):
        return _to_out(evento.itinerary, None, None, restricciones).model_dump(mode="json")

    # Aca el evento ya es PlanReady: la rama de arriba se llevo el borrador.
    return _to_out(evento.itinerary, evento.stats, evento.geometry, restricciones).model_dump(
        mode="json"
    )


@router.post("", dependencies=[Depends(limitar)])
def plan(peticion: PlanMessage) -> StreamingResponse:
    """Arma un itinerario a partir de una frase, transmitiendo cada fase.

    El orden de los eventos es `interpretation`, `candidates`, `draft` y
    `plan`, o un unico `error`. El borrador llega sin tocar la red; el plan
    llega cuando vuelve la matriz de rutas.
    """
    return StreamingResponse(
        _stream(peticion.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Sin esto, nginx y varios proxys acumulan la respuesta entera y
            # la entregan de una sola vez, que es justo lo que el streaming
            # existe para evitar.
            "X-Accel-Buffering": "no",
        },
    )


def _to_constraints(peticion, db: Session) -> motor.Constraints:
    """Las restricciones que el cliente devuelve, tal cual las mando.

    **Copiar campo por campo se paga con los que uno olvida.** Faltaban tres, y
    los tres eran limites duros: sin day_modes, revisar el segundo dia de "el
    primero en coche y el segundo a pie" lo rehacia en coche y con presupuesto
    de coche; sin must_include_categories, "minimo un museo" dejaba de exigirse
    justo cuando el dia se rehace; sin el punto de partida, el dia revisado ya
    no salia ni volvia al hotel. Nada de eso lo habia pedido quien revisaba.
    """
    partida = None
    if peticion.start_place_id is not None:
        # Se resuelve contra el catalogo y no se reconstruye de lo que mando el
        # cliente: es la misma regla que el resto de /revise, donde cada
        # identificador se valida antes de usarse.
        partida = places_by_ids(db, [peticion.start_place_id]).get(peticion.start_place_id)

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
        meal_minutes=peticion.meal_minutes,
        category_minutes=dict(peticion.category_minutes),
        max_stops_per_day=peticion.max_stops_per_day,
        min_quality=peticion.min_quality,
        start_place=partida,
        return_to_start=peticion.return_to_start,
    )


@router.post("/revise", response_model=RevisionOut, dependencies=[Depends(limitar)])
def revise(peticion: ReviseRequest) -> RevisionOut:
    """Cambia un dia del itinerario dejando los demas como estaban.

    **Devuelve JSON y no eventos, a diferencia de /plan.** Aqui se rehace un
    solo dia y el momento visual, los pines cayendo sobre el mapa, ya ocurrio.
    Transmitir la construccion de un dia suelto seria el teatro que el
    streaming de /plan existe para no hacer.
    """
    db = SessionLocal()
    try:
        estado = [
            motor.DayState(
                number=dia.number,
                stops=[(parada.place_id, parada.meal) for parada in dia.stops],
            )
            for dia in peticion.days
        ]

        objetivo = next(d for d in estado if d.number == peticion.day)
        catalogo = places_by_ids(db, [ref for ref, _ in objetivo.stops])
        nombres = [catalogo[ref].name for ref, _ in objetivo.stops if ref in catalogo]

        cambio = interpret_revision(peticion.message, nombres)
        if not cambio.ok:
            raise HTTPException(status_code=422, detail=cambio.error)

        if not cambio.touches_anything:
            # Sin un cambio que aplicar, rehacer el dia lo moveria por nada.
            partes = ["no entendí qué cambiar de ese día."]
            if cambio.unmapped:
                partes.append(f"No supe qué hacer con: {', '.join(cambio.unmapped)}.")
            partes.append(
                "Probá con la hora de inicio, los kilómetros, la cantidad de "
                "paradas, las categorías, o sacar una parada por su nombre."
            )
            raise HTTPException(status_code=422, detail=" ".join(partes))

        base = _to_constraints(peticion.constraints, db)
        del_dia = replace(base, **cambio.changes) if cambio.changes else base

        por_nombre = {hit.name: ref for ref, hit in catalogo.items()}
        excluir = {por_nombre[n] for n in cambio.remove if n in por_nombre}

        resultado = motor.revise_with_routing(
            db, base, estado, peticion.day, day_constraints=del_dia, exclude=excluir
        )

        return RevisionOut(
            itinerary=_to_out(resultado.itinerary, resultado.stats, None, base),
            applied={k: str(v) for k, v in cambio.changes.items()},
            removed=cambio.remove,
            missing=resultado.missing,
            unmapped=cambio.unmapped,
            notes=cambio.notes,
        )
    finally:
        db.close()
