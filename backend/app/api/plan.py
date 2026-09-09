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

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.itinerary import _to_out
from app.core.db import SessionLocal
from app.schemas import AreaOut, InterpretationOut, PlanMessage
from app.services import itinerary as motor
from app.services.interpret import interpret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan", tags=["plan"])


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
            include_meals=resultado.request.include_meals,
            max_stops_per_day=resultado.request.max_stops_per_day,
            min_quality=resultado.request.min_quality,
        )

        for evento in motor.plan_streaming(db, restricciones):
            yield _event(evento.phase, _phase_payload(evento))

    except Exception:
        logger.exception("fallo armando el itinerario")
        yield _event("error", {"message": "no se pudo armar el itinerario"})
    finally:
        db.close()


def _phase_payload(evento) -> dict:
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
        return _to_out(evento.itinerary, None).model_dump(mode="json")

    return _to_out(evento.itinerary, evento.stats).model_dump(mode="json")


@router.post("")
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
