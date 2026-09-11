"""Cuanto cambia el itinerario al respetar los horarios de apertura.

El banco de `evaluate.py` no puede medir esto: sus casos no llevan fecha, y
`opening_hours` habla de dias de la semana. Asi que se arma el mismo itinerario
con fecha en varias zonas y varios dias, y se cuenta cuantas comidas caian en
un comedor que se sabe cerrado.

    docker compose exec api python -m scripts.medir_horarios
"""

from __future__ import annotations

from datetime import date, time, timedelta

from app.core.db import SessionLocal
from app.services import horarios
from app.services.itinerary import Constraints, plan

ZONAS = [
    ("San Salvador", 13.6929, -89.2182),
    ("Santa Ana", 13.9942, -89.5597),
    ("Suchitoto", 13.9375, -89.0281),
    ("La Libertad", 13.4883, -89.3222),
    ("San Miguel", 13.4833, -88.1833),
    ("Ruta de las Flores", 13.8697, -89.8467),
]

# Una semana entera desde un lunes: el domingo y el lunes son los dias donde se
# concentran los cierres, y con un solo dia no se veria.
PRIMER_LUNES = date(2026, 9, 14)


def main() -> int:
    db = SessionLocal()
    total_comidas = 0
    cerradas = 0
    desconocidas = 0
    abiertas = 0
    km_totales = 0.0
    paradas = 0
    por_dia: dict[str, int] = {}

    try:
        for nombre, lat, lon in ZONAS:
            for delta in range(7):
                fecha = PRIMER_LUNES + timedelta(days=delta)
                restricciones = Constraints(
                    days=1,
                    start_date=fecha,
                    center_lat=lat,
                    center_lon=lon,
                    radius_m=20_000,
                    earliest_start=time(9, 0),
                    latest_end=time(21, 0),
                    max_travel_km_per_day=40,
                    include_meals=True,
                )
                itinerario = plan(db, restricciones)

                for dia in itinerario.days:
                    km_totales += dia.travel_km
                    paradas += len(dia.stops)
                    for parada in dia.stops:
                        if parada.meal is None:
                            continue
                        total_comidas += 1
                        texto = (parada.place.tags or {}).get("opening_hours")
                        estado = horarios.estado(
                            texto, fecha, parada.arrival, parada.departure
                        )
                        if estado is horarios.Apertura.CERRADO:
                            cerradas += 1
                            clave = f"{nombre} {fecha}"
                            por_dia[clave] = por_dia.get(clave, 0) + 1
                            print(
                                f"  CERRADO  {nombre} {fecha} {parada.arrival:%H:%M} "
                                f"{parada.place.name}  [{texto}]"
                            )
                        elif estado is horarios.Apertura.ABIERTO:
                            abiertas += 1
                        else:
                            desconocidas += 1
    finally:
        db.close()

    print()
    print(f"itinerarios armados : {len(ZONAS) * 7}")
    print(f"comidas colocadas   : {total_comidas}")
    print(f"  se sabe abierto   : {abiertas}")
    print(f"  no se sabe        : {desconocidas}")
    print(f"  SE SABE CERRADO   : {cerradas}")
    print(f"kilometros totales  : {km_totales:.1f}")
    print(f"paradas totales     : {paradas}")
    return 1 if cerradas else 0


if __name__ == "__main__":
    raise SystemExit(main())
