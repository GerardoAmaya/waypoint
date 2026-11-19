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
# **No es una constante: depende del terreno.** La version anterior usaba 1.45
# para todo el pais, calibrado contra ORS sobre 812 pares de una muestra de
# treinta lugares, y esa medicion concluyo "sin tendencia clara". Pero treinta
# lugares repartidos por el pais son sobre todo pares largos entre ciudades,
# que van por la mejor carretera que hay. Los itinerarios se mueven DENTRO de
# una zona, y ahi manda la montaña.
#
# Medido de nuevo contra OSRM —local, sin cupo, repetible— sobre 10.726 pares
# dentro de las veinte zonas del nomenclator, tres muestras por zona
# (scripts/calibrar_rodeo): la mediana nacional es 1.53, y por zona va de 1.36
# en San Salvador a 2.19 en La Palma. Con 1.45 un dia "de 55 km" en La Palma
# son 83 en carretera, y el motor lo arma como si cupiera.
RODEO_NACIONAL = 1.53

# El factor de cada zona, con su centro y su radio en kilometros. El "±" del
# comentario es cuanto se movio la mediana entre las tres muestras: donde es
# grande —La Palma, Suchitoto, Costa del Sol— el catalogo esta repartido de
# forma que una muestra distinta da otra cosa, y el numero es menos firme.
#
# Lo produce `make rodeo`. Produccion no necesita OSRM para nada de esto: lee
# la tabla, que es lo que se versiona.
RODEO_POR_ZONA: tuple[tuple[float, float, float, float], ...] = (
    (13.9214, -89.845, 15.0, 1.47),  # ahuachapan, ±0.05
    (13.5069, -88.4897, 12.0, 1.59),  # alegria, ±0.10
    (13.8547, -89.8036, 12.0, 1.53),  # apaneca, ±0.04
    (13.8697, -89.8467, 20.0, 1.53),  # ataco, ±0.04
    (13.8258, -89.6314, 18.0, 1.55),  # cerro-verde, ±0.04
    (13.8667, -89.55, 15.0, 1.45),  # coatepeque, ±0.04
    (13.3167, -88.9167, 20.0, 1.61),  # costa-del-sol, ±0.20
    (13.4936, -89.3819, 15.0, 1.44),  # el-tunco, ±0.03
    (13.4936, -89.44, 12.0, 1.65),  # el-zonte, ±0.11
    (13.8414, -89.7461, 12.0, 1.61),  # juayua, ±0.00
    (13.4883, -89.3222, 20.0, 1.50),  # la-libertad, ±0.15
    (14.3167, -89.1667, 15.0, 2.19),  # la-palma, ±0.33
    (14.3333, -89.45, 25.0, 1.74),  # metapan, ±0.04
    (13.7789, -89.7375, 10.0, 1.39),  # nahuizalco, ±0.08
    (13.9564, -88.1583, 15.0, 1.96),  # perquin, ±0.12
    (13.4833, -88.1833, 20.0, 1.38),  # san-miguel, ±0.00
    (13.6929, -89.2182, 15.0, 1.36),  # san-salvador, ±0.01
    (13.9942, -89.5597, 25.0, 1.37),  # santa-ana, ±0.05
    (13.7189, -89.7242, 15.0, 1.39),  # sonsonate, ±0.06
    (13.9356, -89.0272, 15.0, 1.80),  # suchitoto, ±0.23
)

# El nombre viejo, para quien lo importe. Es el nacional: el que se usaba
# cuando el factor no sabia donde estaba.
DETOUR_FACTOR = RODEO_NACIONAL


def factor_de_rodeo(lat: float, lon: float) -> float:
    """Cuanto se desvia la carretera de la recta en ese punto.

    La zona cuyo centro queda mas cerca, si el punto cae dentro de su radio;
    si no cae en ninguna, el nacional. **El respaldo importa tanto como la
    tabla**: el catalogo tiene lugares fuera de las veinte zonas, y para esos
    el numero honesto es el del pais, no el de la zona que casualmente este
    menos lejos.
    """
    mejor = RODEO_NACIONAL
    distancia_mejor = None
    for centro_lat, centro_lon, radio_km, factor in RODEO_POR_ZONA:
        distancia = haversine_km(lat, lon, centro_lat, centro_lon)
        if distancia <= radio_km and (distancia_mejor is None or distancia < distancia_mejor):
            mejor, distancia_mejor = factor, distancia
    return mejor


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
SOURCE_OSRM = "osrm"
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
        # El factor sale del punto medio del tramo y no de un parametro: asi
        # esta funcion sigue siendo pura y ningun sitio tiene que acordarse de
        # pasarle la zona. Un tramo que cruza de una zona a otra se juzga por
        # donde pasa, que es lo mas justo que da un solo numero.
        km = recta * factor_de_rodeo(
            (origen.lat + destino.lat) / 2, (origen.lon + destino.lon) / 2
        )
        velocidad = speed_kmh(self.mode, recta)
        minutos = max(1, round(km / velocidad * 60))
        return round(km, 3), with_arrival_overhead(minutos, self.mode)
