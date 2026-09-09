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
# Medido contra ORS sobre 812 pares del catalogo (scripts/calibrate_travel,
# muestra de 30 lugares, semilla 42): la mediana por tramo dio 1.36, 1.48,
# 1.41 y 1.51, sin tendencia clara con la distancia. O sea que una constante
# describe bien el desvio, pero no era 1.35.
#
# El valor viejo salio de una sola medicion, San Salvador a Santa Ana, que dio
# 1.26 y nos habria llevado a bajarlo. Ese par es la mejor carretera del pais
# y no representa al resto.
DETOUR_FACTOR = 1.45

# La velocidad, en cambio, no aguanta ser una constante. Medida sobre los
# mismos pares, en carro sube de 35 a 62 km/h segun el largo del viaje: el
# salto corto es urbano con semaforos y el largo es carretera. Con un solo
# numero, los tiempos de los tramos largos salian al doble de lo real.
#
# Cada entrada es (limite superior del tramo en kilometros de linea recta,
# velocidad efectiva). El tramo de menos de 2 km se apoya en solo 8 pares, asi
# que es el menos firme de los cuatro.
SPEED_BANDS: dict[str, list[tuple[float, float]]] = {
    "driving": [(2.0, 35.0), (10.0, 41.0), (50.0, 56.0), (float("inf"), 62.0)],
    # ORS devolvio 5.0 km/h exactos en los cuatro tramos. Eso no es una
    # medicion del terreno: es la constante que usa su perfil peatonal, que
    # ignora la pendiente. En un pais de volcanes el tiempo a pie que da ORS
    # no es mucho mejor que este numero, y conviene recordarlo antes de
    # presentarlo como dato duro.
    "walking": [(float("inf"), 5.0)],
}


def speed_kmh(mode: str, straight_line_km: float) -> float:
    """Velocidad efectiva para un viaje de esa distancia.

    El tramo se elige por la distancia en linea recta y no por la de
    carretera, porque asi se midio: al estimar todavia no existe la segunda.
    """
    bandas = SPEED_BANDS.get(mode, SPEED_BANDS["driving"])
    for limite, velocidad in bandas:
        if straight_line_km < limite:
            return velocidad
    return bandas[-1][1]


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


# Minutos que cuesta llegar de verdad a una parada, mas alla de moverse.
#
# El modelo no tenia ninguno, y se veia: 0.7 km en coche daban "1 min", o sea
# salir del hotel y estar dentro del museo sesenta segundos despues. Falta
# estacionar, caminar del carro a la puerta y entrar. En un dia urbano de
# saltos cortos el horario salia optimista por parada.
#
# No esta calibrado contra datos porque no hay datos que medir: es una
# estimacion de sentido comun, igual que DEFAULT_DURATIONS. Lo que si esta
# medido es su costo, que es lo que importa para elegir el numero.
#
# A pie es mucho menor: no hay donde estacionar, solo encontrar la entrada.
ARRIVAL_OVERHEAD_MINUTES = {"driving": 8, "walking": 2}


def with_arrival_overhead(minutos: int, mode: str) -> int:
    """Suma la friccion de llegar a los minutos de moverse.

    Se aplica al usar el dato y no al guardarlo. La cache de travel_edges
    guarda lo que midio OpenRouteService —tiempo de conduccion puro— y meterle
    la friccion ahi dejaria un numero que no es ni una cosa ni la otra, y que
    ya no se podria comparar con la fuente.
    """
    return minutos + ARRIVAL_OVERHEAD_MINUTES.get(mode, 0)


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

    def between(self, origen: Waypoint, destino: Waypoint) -> tuple[float, int]:
        recta = haversine_km(origen.lat, origen.lon, destino.lat, destino.lon)
        km = recta * DETOUR_FACTOR
        velocidad = speed_kmh(self.mode, recta)
        minutos = max(1, round(km / velocidad * 60))
        return round(km, 3), with_arrival_overhead(minutos, self.mode)
