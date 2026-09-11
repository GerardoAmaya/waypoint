"""Dice si ORS esta dibujando rutas por carretera ahora mismo.

Gasta **una** peticion del endpoint de direcciones y contesta una sola cosa:
si el trazo del mapa funciona o no, y si no, por que.

    python -m scripts.check_directions

Hace falta porque `check_ors` prueba la matriz y no las direcciones, y los dos
endpoints se contabilizan aparte: cada uno lleva su ventana de 24 horas y rueda
desde SU primera llamada, asi que uno puede estar agotado y el otro
respondiendo. Sin este guion, la unica forma de saberlo era pedir un itinerario
y mirar si las lineas del mapa salian curvas o rectas.

Los dos puntos son del centro de San Salvador, a kilometro y medio y con calle
de por medio: si ORS no puede enrutar ESTO, el problema no es el terreno.
"""

from __future__ import annotations

import sys

from app.core.config import settings
from app.services.geo import haversine_km
from app.services.routing import ORSClient, ORSError, ORSQuotaExhausted

# Plaza Libertad y el Teatro Nacional, en el centro de San Salvador.
DESDE = (13.6985, -89.1914)
HASTA = (13.6975, -89.1893)


def main() -> int:
    if not settings.ors_api_key:
        print("No hay ORS_API_KEY en el entorno. Sacala en account.heigit.org.")
        return 1

    cliente = ORSClient(
        api_key=settings.ors_api_key,
        base_url=settings.ors_base_url,
        min_interval_seconds=settings.ors_min_interval_seconds,
        directions_budget=settings.ors_directions_budget,
    )

    try:
        trazo = cliente.directions([DESDE, HASTA], "driving-car")
    except ORSQuotaExhausted:
        print("TODAVIA NO: ORS sigue diciendo que el cupo de direcciones esta agotado.")
        print(
            "\nSu ventana es de 24 h y rueda desde la primera llamada del dia "
            "anterior, no a medianoche. Reintentar cuesta una peticion, asi que "
            "probar mas tarde con este mismo comando es barato."
        )
        print("Mientras tanto el mapa dibuja lineas rectas punteadas y lo dice.")
        return 1
    except ORSError as exc:
        print(f"FALLO, y no es el cupo: {exc}")
        return 1

    if len(trazo) < 2:
        print("ORS contesto sin geometria. No es el cupo; revisa las coordenadas.")
        return 1

    recta = haversine_km(*DESDE, *HASTA)
    largo = sum(haversine_km(*a, *b) for a, b in zip(trazo, trazo[1:], strict=False))
    print(f"FUNCIONA: el trazo volvio con {len(trazo)} vertices.")
    print(f"  en linea recta {recta * 1000:.0f} m, por carretera {largo * 1000:.0f} m")
    print(f"  cupo restante segun ORS: {cliente.directions_quota.remaining}")
    print("\nYa se pueden pedir itinerarios y ver las rutas pintadas en el mapa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
