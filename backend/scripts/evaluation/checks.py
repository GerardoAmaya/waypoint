"""Comprobaciones independientes sobre un itinerario terminado.

**Deliberadamente NO usan validate().** El motor arma el itinerario y despues
lo juzga con la misma logica; medir el cumplimiento asi mide consistencia
consigo mismo, no correccion. Si validate() tiene un punto ciego, la
evaluacion da cien por ciento y no ve nada.

Aqui se relee la salida y se derivan las condiciones de nuevo. Dos
implementaciones que coinciden es evidencia; una que coincide consigo misma no
es nada.

Como efecto secundario, se pueden comprobar cosas que validate() ni mira: un
lugar repetido entre dos dias, una parada fuera del radio pedido, un horario
que retrocede, o un identificador que no esta en el catalogo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import time

from app.services.geo import haversine_km
from app.services.itinerary import DINNER_WINDOW, LUNCH_WINDOW, Constraints, Itinerary


@dataclass
class Failure:
    """Una condicion que el itinerario no cumple."""

    check: str
    day: int | None
    detail: str


@dataclass
class Report:
    failures: list[Failure] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def add(self, check: str, day: int | None, detail: str) -> None:
        self.failures.append(Failure(check, day, detail))


def _minutes(momento: time) -> int:
    return momento.hour * 60 + momento.minute


def check_all(
    itinerario: Itinerary,
    constraints: Constraints,
    catalog_ids: set[uuid.UUID] | None = None,
) -> Report:
    """Todas las comprobaciones sobre un itinerario."""
    reporte = Report()

    _check_days_requested(itinerario, constraints, reporte)
    _check_no_repeats(itinerario, reporte)
    if catalog_ids is not None:
        _check_no_invented_places(itinerario, catalog_ids, reporte)

    for dia in itinerario.days:
        if not dia.stops:
            reporte.add("empty_day", dia.number, "el dia quedo sin paradas")
            continue

        _check_schedule_window(dia, constraints, reporte)
        _check_chronology(dia, reporte)
        _check_stop_count(dia, constraints, reporte)
        _check_travel_budget(dia, constraints, reporte)
        _check_avoided(dia, constraints, reporte)
        _check_within_radius(dia, constraints, reporte)
        _check_meals(dia, constraints, reporte)

    return reporte


def _check_days_requested(
    itinerario: Itinerary, constraints: Constraints, reporte: Report
) -> None:
    armados = len(itinerario.days)
    if armados < constraints.days:
        reporte.add(
            "days",
            None,
            f"se pidieron {constraints.days} dias y se armaron {armados}",
        )


def _check_no_repeats(itinerario: Itinerary, reporte: Report) -> None:
    """Un lugar no puede aparecer dos veces en el mismo viaje.

    validate() no lo comprueba. Es exactamente el tipo de fallo que una
    evaluacion hecha con el mismo codigo del motor nunca encontraria.
    """
    vistos: dict[uuid.UUID, int] = {}
    for dia in itinerario.days:
        for parada in dia.stops:
            anterior = vistos.get(parada.place.id)
            if anterior is not None:
                reporte.add(
                    "repeated_place",
                    dia.number,
                    f"{parada.place.name} ya aparecia en el dia {anterior}",
                )
            else:
                vistos[parada.place.id] = dia.number


def _check_no_invented_places(
    itinerario: Itinerary, catalog_ids: set[uuid.UUID], reporte: Report
) -> None:
    """Cada parada tiene que existir en el catalogo.

    Debe dar cero por construccion, porque el modelo no elige lugares. Se mide
    igual: "por construccion" es una afirmacion sobre el diseno, y una metrica
    que nunca se comprueba es una creencia.
    """
    for dia in itinerario.days:
        for parada in dia.stops:
            if parada.place.id not in catalog_ids:
                reporte.add(
                    "invented_place",
                    dia.number,
                    f"{parada.place.name} no esta en el catalogo",
                )


def _check_schedule_window(dia, constraints: Constraints, reporte: Report) -> None:
    if dia.start < constraints.earliest_start:
        reporte.add(
            "earliest_start",
            dia.number,
            f"empieza {dia.start} y el minimo era {constraints.earliest_start}",
        )
    if dia.end > constraints.latest_end:
        reporte.add(
            "latest_end",
            dia.number,
            f"termina {dia.end} y el maximo era {constraints.latest_end}",
        )


def _check_chronology(dia, reporte: Report) -> None:
    """El tiempo no retrocede y las paradas no se solapan."""
    anterior = None
    for parada in dia.stops:
        if parada.arrival > parada.departure:
            reporte.add(
                "chronology",
                dia.number,
                f"{parada.place.name} sale {parada.departure} antes de llegar "
                f"{parada.arrival}",
            )
        if anterior is not None and parada.arrival < anterior.departure:
            reporte.add(
                "overlap",
                dia.number,
                f"{parada.place.name} empieza antes de que termine {anterior.place.name}",
            )
        anterior = parada


def _check_stop_count(dia, constraints: Constraints, reporte: Report) -> None:
    if len(dia.stops) > constraints.max_stops_per_day:
        reporte.add(
            "max_stops_per_day",
            dia.number,
            f"{len(dia.stops)} paradas y el limite era {constraints.max_stops_per_day}",
        )


def _check_travel_budget(dia, constraints: Constraints, reporte: Report) -> None:
    """Se recalcula la suma en vez de leer dia.travel_km.

    Leer la propiedad seria confiar en la misma cuenta que hizo el motor.
    """
    total = round(sum(p.travel_km_from_previous for p in dia.stops), 2)
    if total > constraints.max_travel_km_per_day + 0.01:
        reporte.add(
            "max_travel_km_per_day",
            dia.number,
            f"{total} km y el limite era {constraints.max_travel_km_per_day}",
        )


def _check_avoided(dia, constraints: Constraints, reporte: Report) -> None:
    evitadas = {c.value for c in constraints.avoided_categories}
    for parada in dia.stops:
        if parada.place.category in evitadas:
            reporte.add(
                "avoided_categories",
                dia.number,
                f"{parada.place.name} es {parada.place.category}, que se pidio evitar",
            )


def _check_within_radius(dia, constraints: Constraints, reporte: Report) -> None:
    """Ninguna parada puede caer fuera de la zona pedida.

    validate() tampoco lo mira: da por hecho que la busqueda espacial filtro
    bien. Comprobarlo aparte es lo que haria notar si dejara de filtrar.
    """
    limite_km = constraints.radius_m / 1000.0
    for parada in dia.stops:
        distancia = haversine_km(
            constraints.center_lat,
            constraints.center_lon,
            parada.place.lat,
            parada.place.lon,
        )
        if distancia > limite_km + 0.5:
            reporte.add(
                "radius",
                dia.number,
                f"{parada.place.name} esta a {distancia:.1f} km del centro y el "
                f"radio era {limite_km:.1f} km",
            )


def _check_meals(dia, constraints: Constraints, reporte: Report) -> None:
    """Si se pidieron comidas y el dia cruza la franja, tiene que haber una."""
    if not constraints.include_meals:
        return

    cruza_almuerzo = _minutes(dia.start) <= _minutes(LUNCH_WINDOW[1]) and _minutes(
        dia.end
    ) >= _minutes(LUNCH_WINDOW[0])
    if cruza_almuerzo and not any(p.meal == "lunch" for p in dia.stops):
        reporte.add("include_meals", dia.number, "cruza el almuerzo y no lo tiene")

    cruza_cena = _minutes(dia.end) >= _minutes(DINNER_WINDOW[0])
    if cruza_cena and not any(p.meal == "dinner" for p in dia.stops):
        reporte.add("include_meals", dia.number, "llega a la cena y no la tiene")
