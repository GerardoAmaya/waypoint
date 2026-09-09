"""Comprueba la llave de OpenRouteService y anota el cupo real.

Es la verificacion de la fase 4 que no se puede automatizar en CI: necesita
red y gasta cupo. Se corre a mano una vez y su salida va al README.

    python -m scripts.check_ors

Mide San Salvador - Santa Ana: 49.8 km en linea recta, 62.6 por carretera en
carro y 68.9 a pie, medido el 2026-09-09. Si el resultado se parece a la
distancia geodesica, o peor, si da un numero enorme, lo mas probable es que
las coordenadas se hayan mandado invertidas.

Ojo con el cupo: el endpoint de matriz da 50 peticiones al dia y este guion
gasta 3.
"""

from __future__ import annotations

import sys

import httpx

from app.core.config import settings
from app.services.geo import ORS_PROFILES, haversine_km
from app.services.routing import ORSClient, ORSError

SAN_SALVADOR = (13.6929, -89.2182)
SANTA_ANA = (13.9942, -89.5597)


def main() -> int:
    if not settings.ors_api_key:
        print("No hay ORS_API_KEY en el entorno. Sacala en account.heigit.org.")
        return 1

    linea_recta = haversine_km(*SAN_SALVADOR, *SANTA_ANA)
    print(f"Distancia geodesica de referencia: {linea_recta:.1f} km\n")

    cliente = ORSClient(
        api_key=settings.ors_api_key,
        base_url=settings.ors_base_url,
        min_interval_seconds=settings.ors_min_interval_seconds,
    )

    for modo, profile in ORS_PROFILES.items():
        try:
            distancias, duraciones = cliente.matrix([SAN_SALVADOR, SANTA_ANA], profile)
        except ORSError as exc:
            print(f"{modo:8} fallo: {exc}")
            continue

        km = distancias[0][1]
        minutos = duraciones[0][1]
        if km is None:
            print(f"{modo:8} sin ruta: algun punto no engancho a la red")
            continue

        desvio = km / linea_recta
        print(f"{modo:8} {km:7.1f} km  {minutos:6.0f} min  (factor de desvio {desvio:.2f})")

    print()
    mostrar_cupo(cliente)
    return 0


def mostrar_cupo(cliente: ORSClient) -> None:
    """Lee los encabezados de cupo con una peticion minima.

    ORS los manda en cada respuesta. Anotarlos importa porque la ventana
    diaria se reinicia 24 horas despues de la primera peticion, no a
    medianoche, asi que se va corriendo dia a dia.
    """
    cliente.pacer.wait()
    respuesta = httpx.post(
        f"{cliente.base_url}/v2/matrix/driving-car",
        json={"locations": [[-89.2182, 13.6929], [-89.5597, 13.9942]]},
        headers={"Authorization": cliente.api_key, "Content-Type": "application/json"},
        timeout=30.0,
    )

    cupo = {k: v for k, v in respuesta.headers.items() if "ratelimit" in k.lower()}
    if not cupo:
        print("La respuesta no trae encabezados de cupo.")
        return

    print("Cupo segun ORS:")
    for clave, valor in sorted(cupo.items()):
        print(f"  {clave}: {valor}")


if __name__ == "__main__":
    sys.exit(main())
