"""Mide cuanto se desvia la carretera de la linea recta, zona por zona.

    make rodeo          (necesita `make osrm` levantado)

**Existe porque una constante nacional no describe el desvio.** `geo.py` usaba
1.45 para todo el pais, calibrado contra ORS sobre 812 pares de una muestra de
treinta lugares, y esa medicion concluyo "sin tendencia clara". Pero una
muestra de treinta lugares repartidos por el pais coge sobre todo pares largos
entre ciudades, que van por la mejor carretera que hay. Los itinerarios se
mueven DENTRO de una zona, que es donde la montaña manda: medido asi, la
mediana va de 1.26 en San Miguel a 2.64 en La Palma.

Mide contra OSRM y no contra ORS a proposito: el grafo es local, no tiene
cupo, y eso convierte la calibracion en algo que se puede repetir cuando el
catalogo cambie en vez de un numero heredado que nadie se atreve a tocar.

Lo que sale de aqui se pega en `RODEO_POR_ZONA`, en geo.py. Produccion no
necesita OSRM: lee la tabla.
"""

from __future__ import annotations

import argparse
import random
import statistics

import httpx
from sqlalchemy import text

from app.core.db import SessionLocal
from app.services.geo import haversine_km
from app.services.geocode import ZONES

# Por debajo de esto el par no dice nada del desvio: dos lugares a trescientos
# metros dan factores enormes por un sentido unico.
MINIMO_KM = 0.5

# Menos pares que esto y la mediana de la zona es una anecdota.
MINIMO_PARES = 30


def lugares_de(db, zona, cuantos: int):
    return db.execute(
        text("""
            select st_y(geom::geometry) lat, st_x(geom::geometry) lon
            from places
            where st_dwithin(geom, st_makepoint(:lon, :lat)::geography, :r)
            order by random()
            limit :n
        """),
        {"lat": zona.lat, "lon": zona.lon, "r": zona.radius_m, "n": cuantos},
    ).fetchall()


def factores(cli: httpx.Client, url: str, lugares) -> list[float]:
    salida: list[float] = []
    for i in range(len(lugares)):
        for j in range(i + 1, len(lugares)):
            a, b = lugares[i], lugares[j]
            recta = haversine_km(a.lat, a.lon, b.lat, b.lon)
            if recta < MINIMO_KM:
                continue
            try:
                r = cli.get(
                    f"{url}/route/v1/driving/{a.lon},{a.lat};{b.lon},{b.lat}",
                    params={"overview": "false"},
                ).json()
            except Exception:  # noqa: BLE001
                continue
            if r.get("code") != "Ok" or not r.get("routes"):
                continue
            salida.append((r["routes"][0]["distance"] / 1000) / recta)
    return salida


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lugares", type=int, default=20, help="lugares por zona")
    parser.add_argument("--url", default="http://osrm-car:5000")
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument(
        "--repeticiones",
        type=int,
        default=3,
        help="muestras independientes por zona; la mediana de una sola baila",
    )
    args = parser.parse_args()

    db = SessionLocal()
    cli = httpx.Client(timeout=30)
    todos: list[float] = []
    tabla: list[tuple] = []

    try:
        print(f"{'zona':<26} {'pares':>6} {'mediana':>8} {'rango':>7} {'p90':>7} {'peor':>7}")
        for zona in ZONES:
            # **Una muestra sola no basta.** Medido con tres semillas, la
            # mediana de Suchitoto se movio 0.84 entre ellas y la de Santa Ana
            # 0.06: el ruido depende de como este repartido el catalogo en esa
            # zona. Se promedian las repeticiones y se enseña cuanto bailaron,
            # para que quien lea la tabla sepa de cual fiarse.
            medianas: list[float] = []
            medidos: list[float] = []
            for repeticion in range(args.repeticiones):
                random.seed(args.semilla + repeticion * 1000)
                lugares = lugares_de(db, zona, args.lugares)
                if len(lugares) < 6:
                    break
                muestra = factores(cli, args.url, lugares)
                if len(muestra) < MINIMO_PARES:
                    continue
                medianas.append(statistics.median(muestra))
                medidos += muestra
            if not medianas:
                print(f"{zona.name[:26]:<26}  (pocos pares, se omite)")
                continue

            medidos.sort()
            todos += medidos
            factor = statistics.mean(medianas)
            rango = max(medianas) - min(medianas)
            tabla.append((zona.key, zona.lat, zona.lon, zona.radius_m, factor, rango))
            print(
                f"{zona.name[:26]:<26} {len(medidos):>6} {factor:>8.2f} {rango:>7.2f} "
                f"{medidos[int(len(medidos) * 0.9)]:>7.2f} {max(medidos):>7.1f}"
            )
    finally:
        db.close()
        cli.close()

    if not todos:
        print("\nsin mediciones: ¿está OSRM levantado? (make osrm)")
        return 1

    todos.sort()
    nacional = statistics.median(todos)
    print(
        f"\n{'TODAS':<26} {len(todos):>6} {nacional:>8.2f} "
        f"{todos[int(len(todos) * 0.9)]:>7.2f} {max(todos):>7.1f}"
    )

    print("\n# Pegar en geo.py:\n")
    print(f"RODEO_NACIONAL = {nacional:.2f}\n")
    print("RODEO_POR_ZONA: tuple[tuple[float, float, float, float], ...] = (")
    for clave, lat, lon, radio, factor, rango in sorted(tabla, key=lambda t: t[0]):
        print(
            f"    ({lat}, {lon}, {radio / 1000:.1f}, {factor:.2f}),"
            f"  # {clave}, ±{rango / 2:.2f}"
        )
    print(")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
