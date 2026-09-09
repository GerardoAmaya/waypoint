"""Geometria y medicion de traslados.

Vive aparte de itinerary.py por una razon concreta: el motor importa el
proveedor de rutas y el proveedor de rutas necesita la estimacion geodesica
para cubrir los pares que OpenRouteService no puede resolver. Con las dos
cosas en el mismo modulo el ciclo de importaciones seria inevitable.

La abstraccion central es TravelProvider: cualquier cosa que sepa decir
cuantos kilometros y cuantos minutos hay entre dos paradas. El motor no
distingue entre una estimacion y una ruta real, y esa indiferencia es lo que
permite que los tests corran sin red y la produccion use ORS.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Protocol, runtime_checkable

# Los caminos reales no van en linea recta. Este factor convierte la distancia
# geodesica en una aproximacion de la distancia por carretera.
#
# Desde la fase 4 ya no es la fuente principal: se usa cuando no hay llave de
# ORS, cuando se agoto el cupo diario, y para los pares que ORS no puede
# resolver porque el punto esta lejos de toda carretera. Eso ultimo no es raro
# en este catalogo: cumbres de volcanes y cascadas suelen estar a varios
# cientos de metros del camino mas cercano.
DETOUR_FACTOR = 1.35

SPEED_KMH = {"walking": 4.5, "driving": 40.0}

# Nuestros modos de traslado traducidos a perfiles de OpenRouteService.
ORS_PROFILES = {"walking": "foot-walking", "driving": "driving-car"}

# Como se obtuvo la medida de un traslado. Va a la base y al README: la
# proporcion de aristas reales frente a estimadas es una metrica del proyecto,
# no un detalle interno.
SOURCE_ORS = "ors"
SOURCE_ESTIMATED = "estimated"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en linea recta entre dos puntos, en kilometros."""
    radio_tierra = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radio_tierra * asin(sqrt(a))


@runtime_checkable
class Waypoint(Protocol):
    """Lo minimo que hace falta de una parada para medir un traslado."""

    lat: float
    lon: float


class TravelProvider(Protocol):
    """Cuanto cuesta ir de una parada a otra.

    Devuelve siempre kilometros de recorrido, nunca distancia en linea recta.
    Quien consume este valor no debe aplicarle ningun factor de correccion: si
    hace falta, ya viene aplicado.
    """

    def between(self, origen: Waypoint, destino: Waypoint) -> tuple[float, int]:
        """Kilometros y minutos entre dos paradas."""
        ...


class EstimatedTravel:
    """Traslados deducidos de la distancia geodesica.

    Es el proveedor por defecto y el respaldo de todos los demas. Deliberado
    que sea puro y sin estado: los tests del motor no necesitan ni red ni base
    de datos para comprobar que una restriccion se respeta.
    """

    source = SOURCE_ESTIMATED

    def __init__(self, mode: str = "driving") -> None:
        self.mode = mode
        self.speed_kmh = SPEED_KMH.get(mode, SPEED_KMH["driving"])

    def between(self, origen: Waypoint, destino: Waypoint) -> tuple[float, int]:
        km = haversine_km(origen.lat, origen.lon, destino.lat, destino.lon) * DETOUR_FACTOR
        return round(km, 3), max(1, round(km / self.speed_kmh * 60))
