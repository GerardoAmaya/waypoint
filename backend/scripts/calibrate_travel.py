"""Calibra la estimacion geodesica contra rutas reales.

DETOUR_FACTOR y SPEED_BANDS salieron de este guion. Vuelve a medirlos contra el
catalogo: toma una muestra de lugares, pide una matriz real, y compara cada
par con lo que la estimacion habria dicho.

    python -m scripts.calibrate_travel --sample 30

**Los resultados se reportan por tramo de distancia y no como un promedio.**
Un salto de dos cuadras y la autopista a Santa Ana no se comportan igual: el
tramo corto tiene mas desvio y menos velocidad, y promediarlos produce un
numero que no describe a ninguno de los dos. Si los tramos difieren mucho, la
conclusion no es ajustar la constante sino que una constante sola no alcanza.

Cuesta dos peticiones de las cincuenta diarias, una por perfil.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Place
from app.services.geo import DETOUR_FACTOR, haversine_km, speed_kmh
from app.services.routing import ORSClient, ORSError

# Tramos en kilometros de linea recta, con su nombre para el reporte.
TRAMOS = [
    ("menos de 2 km", 0.0, 2.0),
    ("2 a 10 km", 2.0, 10.0),
    ("10 a 50 km", 10.0, 50.0),
    ("mas de 50 km", 50.0, float("inf")),
]


def muestra_de_lugares(db, cantidad: int, semilla: int) -> list[Place]:
    """Lugares activos repartidos por todo el pais.

    Se ordena al azar con semilla fija para que dos corridas comparen lo
    mismo. Sin la semilla, cada medicion sale sobre otros pares y no se puede
    saber si el numero cambio por el ajuste o por la muestra.
    """
    filas = db.execute(select(Place).where(Place.is_active.is_(True))).scalars().all()
    random.Random(semilla).shuffle(filas)
    return filas[:cantidad]


def calibrar(cliente: ORSClient, lugares: list[Place], modo: str, profile: str) -> None:
    try:
        distancias, duraciones = cliente.matrix([(p.lat, p.lon) for p in lugares], profile)
    except ORSError as exc:
        print(f"{modo}: no se pudo medir ({exc})")
        return

    por_tramo: dict[str, list[tuple[float, float]]] = {n: [] for n, _, _ in TRAMOS}
    sin_ruta = 0

    for i, origen in enumerate(lugares):
        for j, destino in enumerate(lugares):
            if i == j:
                continue
            km_real = distancias[i][j]
            minutos = duraciones[i][j]
            if km_real is None or minutos is None or minutos <= 0:
                sin_ruta += 1
                continue

            recta = haversine_km(origen.lat, origen.lon, destino.lat, destino.lon)
            if recta < 0.05:
                continue

            desvio = km_real / recta
            velocidad = km_real / (minutos / 60.0)

            for nombre, minimo, maximo in TRAMOS:
                if minimo <= recta < maximo:
                    por_tramo[nombre].append((desvio, velocidad))
                    break

    print(f"\n### {modo}  (desvio actual {DETOUR_FACTOR})")
    print(f"{'tramo':<16} {'pares':>6} {'desvio':>8} {'km/h':>8} {'esperado':>9}")

    for nombre, minimo, maximo in TRAMOS:
        datos = por_tramo[nombre]
        # Lo que diria la constante para un viaje tipico de este tramo.
        referencia = minimo + 1 if maximo == float("inf") else (minimo + maximo) / 2
        esperado = speed_kmh(modo, referencia)
        if not datos:
            print(f"{nombre:<16} {0:>6}        -        - {esperado:>9.1f}")
            continue
        desvios = statistics.median(d for d, _ in datos)
        velocidades = statistics.median(v for _, v in datos)
        print(
            f"{nombre:<16} {len(datos):>6} {desvios:>8.2f} {velocidades:>8.1f} "
            f"{esperado:>9.1f}"
        )

    if sin_ruta:
        total = len(lugares) * (len(lugares) - 1)
        print(
            f"\n{sin_ruta} de {total} pares sin ruta ({sin_ruta / total:.0%}): "
            "puntos lejos de toda carretera, que caen a estimacion."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=30, help="lugares a muestrear")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mode", choices=["driving", "walking", "both"], default="both")
    args = parser.parse_args()

    if not settings.ors_api_key:
        print("No hay ORS_API_KEY en el entorno.")
        return 1

    # 3.500 pares por peticion es el techo del servicio.
    if args.sample > 59:
        print(f"--sample {args.sample} pasaria de 3.500 pares. El maximo es 59.")
        return 1

    cliente = ORSClient(
        api_key=settings.ors_api_key,
        base_url=settings.ors_base_url,
        min_interval_seconds=settings.ors_min_interval_seconds,
    )

    with SessionLocal() as db:
        lugares = muestra_de_lugares(db, args.sample, args.seed)

    if len(lugares) < 2:
        print("El catalogo esta vacio. Corre primero la carga de lugares.")
        return 1

    print(f"Muestra de {len(lugares)} lugares, semilla {args.seed}.")
    print(f"Cuesta {1 if args.mode != 'both' else 2} peticiones de las 50 diarias.")

    modos = ["driving", "walking"] if args.mode == "both" else [args.mode]
    perfiles = {"driving": "driving-car", "walking": "foot-walking"}
    for modo in modos:
        calibrar(cliente, lugares, modo, perfiles[modo])

    return 0


if __name__ == "__main__":
    sys.exit(main())
