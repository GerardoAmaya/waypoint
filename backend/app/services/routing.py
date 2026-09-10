"""Distancias reales de OpenRouteService, con cache y control de ritmo.

Tres decisiones dan forma a este modulo.

**Se pide una matriz, no una ruta por par.** El endpoint /v2/matrix admite
3.500 pares origen x destino por peticion, o sea 50 x 50. Un itinerario de
siete dias con treinta y cinco paradas son 1.225 pares: una sola llamada. Si
en cambio se pidiera cada par por separado, el 2-opt del motor dispararia
cientos de peticiones por itinerario y el cupo diario se agotaria en una demo.

**La distancia entre dos puntos fijos no cambia.** Por eso se guarda en
travel_edges y la segunda consulta no toca la red. El cupo se gasta una vez
por par, no una vez por itinerario.

**Nunca falla, degrada.** Sin llave, sin cupo, o con un punto que ORS no puede
enganchar a ninguna carretera, el par cae a la estimacion geodesica y queda
marcado como tal. Un itinerario con distancias aproximadas sirve; un error
500 en la demo no.
"""

from __future__ import annotations

import json
import logging
import threading
import time as _time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

from app.services.geo import (
    ORS_PROFILES,
    SOURCE_ESTIMATED,
    SOURCE_ORS,
    EstimatedTravel,
    Waypoint,
    haversine_km,
    with_arrival_overhead,
)

logger = logging.getLogger(__name__)

# 3.500 pares por peticion es el limite del servicio. Con bloques de 50 son
# 2.500 pares, que deja margen y coincide con el ejemplo de la documentacion.
MAX_LOCATIONS_PER_REQUEST = 50


class ORSError(Exception):
    """Fallo hablando con OpenRouteService."""


class ORSAuthError(ORSError):
    """La llave no sirve."""


class ORSQuotaExhausted(ORSError):
    """Se acabo el cupo diario.

    ORS responde 403 a esto, no 429. Distinguirlo importa: tratarlo como
    problema de credenciales manda a revisar la llave cuando lo unico que hay
    que hacer es esperar a que se reinicie la ventana de 24 horas, que ademas
    corre desde la primera peticion y no desde medianoche.
    """


class ORSUnroutable(ORSError):
    """Alguno de los puntos no se pudo enganchar a la red de carreteras."""


class ORSBudgetExhausted(ORSError):
    """Se acabo el presupuesto que nos pusimos nosotros, antes del de ORS."""


class DailyQuota:
    """Cuenta cuantas peticiones llevamos en la ventana de 24 horas.

    El espaciado del Pacer evita ir demasiado rapido pero no evita ir
    demasiado lejos: cincuenta llamadas a un segundo y medio de distancia
    agotan el cupo diario en poco mas de un minuto.

    **La ventana es deslizante y no un contador que se pone en cero a
    medianoche**, porque asi es como funciona ORS: el reinicio cae 24 horas
    despues de la primera peticion, no a una hora fija, y esa ventana se va
    corriendo dia a dia.

    Vive en memoria, asi que un reinicio del proceso le borra la cuenta. Por
    eso `sync_with_server` existe: la respuesta de ORS trae cuanto cupo queda
    de verdad, y esa cifra manda sobre la nuestra. Al primer intento despues
    de un reinicio volvemos a saber donde estamos parados.
    """

    WINDOW_SECONDS = 24 * 60 * 60

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self._lock = threading.Lock()
        self._calls: list[float] = []
        self._server_remaining: int | None = None

    def _prune(self, ahora: float) -> None:
        limite = ahora - self.WINDOW_SECONDS
        self._calls = [t for t in self._calls if t > limite]

    @property
    def remaining(self) -> int | None:
        """Cupo restante segun ORS, o None si todavia no nos lo dijo.

        **Devolver nuestro presupuesto entero como si fuera el de ORS es
        peor que no decir nada.** Recien arrancado el proceso, "quedan 45"
        parece una lectura y es un valor por defecto; el numero real puede ser
        cualquiera, porque otras corridas del dia ya gastaron y la ventana de
        24 horas no se reinicio.
        """
        if self._server_remaining is None:
            return None
        with self._lock:
            self._prune(_time.monotonic())
            propio = max(0, self.budget - len(self._calls))
        return min(propio, self._server_remaining)

    @property
    def own_remaining(self) -> int:
        """Lo que queda de nuestro presupuesto, sin mirar al servidor."""
        with self._lock:
            self._prune(_time.monotonic())
            return max(0, self.budget - len(self._calls))

    def try_spend(self) -> bool:
        """Reserva una peticion, o dice que no queda."""
        with self._lock:
            ahora = _time.monotonic()
            self._prune(ahora)
            if len(self._calls) >= self.budget:
                return False
            if self._server_remaining is not None and self._server_remaining <= 0:
                return False
            self._calls.append(ahora)
            if self._server_remaining is not None:
                self._server_remaining -= 1
            return True

    def sync_with_server(self, remaining: int | None) -> None:
        """Ajusta la cuenta a lo que dice ORS, que es la cifra que manda."""
        if remaining is None:
            return
        self._server_remaining = remaining


class Pacer:
    """Espaciado minimo entre llamadas.

    La leccion de Voyage en DocuFlow: ante un limite conocido se controla el
    ritmo en origen. Reintentar a ciegas contra un limite que ya sabemos que
    existe gasta cupo en peticiones destinadas a fallar.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval = max(0.0, min_interval_seconds)
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            faltan = self.min_interval - (_time.monotonic() - self._last_call)
            if faltan > 0:
                _time.sleep(faltan)
            self._last_call = _time.monotonic()


# Cuanto puede alejarse una parada para engancharse a la red vial.
#
# **El valor por defecto de ORS son 350 metros y es lo que rompia el trazo.**
# No hay calle a menos de 350 m de la cumbre de un volcan, asi que ORS
# respondia 404 con el codigo 2010 —"could not find routable point"— y, como la
# geometria se pide una vez por dia, ese unico punto tumbaba el trazo del dia
# entero: en el arnes, 34 de 61 dias y 127 de 236 tramos, incluidos los que van
# entre museos del centro y ORS enruta sin problema.
#
# Medido contra el Volcan de San Salvador, que es el reincidente: con 5 km el
# dia enruta y el trazo arranca a 840 m de la cumbre. Eso no es un error de
# precision, es el dato correcto —ahi se acaba la carretera y empieza la
# caminata— y es mucho mas informativo que una linea recta de ocho kilometros.
#
# El tope existe para que un punto en medio de un lago no se engache a una
# carretera de la otra orilla y dibuje un recorrido que nadie va a hacer. Lo
# que pase de ahi se queda recto, que es la respuesta honesta.
SNAP_RADIUS_M = 5000

# Los dos endpoints que se usan, cada uno con su propio cupo.
ENDPOINT_MATRIX = "matrix"
ENDPOINT_DIRECTIONS = "directions"


class ORSClient:
    """Cliente de OpenRouteService: matriz para distancias, direcciones para el trazo."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openrouteservice.org",
        min_interval_seconds: float = 1.5,
        timeout: float = 30.0,
        daily_budget: int = 45,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pacer = Pacer(min_interval_seconds)
        # **Un cupo por endpoint, porque asi los cuenta ORS.** Con un contador
        # compartido la matriz se llevaba el presupuesto entero y la geometria
        # se quedaba sin pedir: como la matriz corre primero en la misma
        # peticion, cuando le tocaba al trazo el cliente creia que no quedaba
        # nada. Los itinerarios salian con distancias reales y lineas rectas, y
        # route_legs no llego a guardar ni una fila.
        #
        # El mismo error tenia una segunda cara peor: sync_with_server guardaba
        # el x-ratelimit-remaining de la ultima respuesta —de cualquiera de los
        # dos endpoints— en un campo comun, asi que un "quedan 4" de la matriz
        # apagaba direcciones, que tenia su cupo intacto.
        self.quotas = {
            ENDPOINT_MATRIX: DailyQuota(daily_budget),
            ENDPOINT_DIRECTIONS: DailyQuota(daily_budget),
        }
        self.request_count = 0

    @property
    def matrix_quota(self) -> DailyQuota:
        """El cupo de las distancias.

        Se expone con nombre propio y no como `quota` a secas: un atributo que
        no dice de que endpoint es fue exactamente lo que dejo pasar el bug.
        """
        return self.quotas[ENDPOINT_MATRIX]

    @property
    def directions_quota(self) -> DailyQuota:
        """El cupo del trazo por carretera."""
        return self.quotas[ENDPOINT_DIRECTIONS]

    def _registrar(self, endpoint: str, respuesta: httpx.Response) -> None:
        """Anota lo que la respuesta dice del cupo, y despues falla si toca.

        **Un 403 "Quota exceeded" no trae la cabecera del cupo**, asi que sin
        esto la unica noticia fiable de que no queda nada se perdia. El sintoma
        estaba en pantalla: la cabecera decia "estas paradas estan lejos de
        toda carretera y no se pueden medir" mientras el mapa dibujaba siete de
        nueve tramos por carretera. La causa no era el terreno, era el cupo, y
        el motor no podia distinguirlo porque un 403 tambien cuenta como
        peticion hecha.
        """
        restante = _remaining_header(respuesta)
        if respuesta.status_code == 403:
            restante = 0
        self.quotas[endpoint].sync_with_server(restante)
        self._raise_for_status(respuesta)

    def _spend(self, endpoint: str) -> None:
        cupo = self.quotas[endpoint]
        if not cupo.try_spend():
            raise ORSBudgetExhausted(
                f"presupuesto diario agotado en {endpoint} ({cupo.budget} peticiones)"
            )

    def matrix(
        self,
        coords: list[tuple[float, float]],
        profile: str,
        sources: list[int] | None = None,
        destinations: list[int] | None = None,
    ) -> tuple[list[list[float | None]], list[list[float | None]]]:
        """Kilometros y minutos entre cada origen y cada destino.

        `coords` va en (lat, lon) porque es el orden que usa el resto del
        proyecto. ORS espera (lon, lat) y aqui se invierte. Es el error mas
        comun contra esta API y no da fallo: devuelve rutas plausibles en el
        oceano Indico, asi que hay un test que lo fija.
        """
        cuerpo: dict = {
            "locations": [[lon, lat] for lat, lon in coords],
            "metrics": ["distance", "duration"],
            "units": "km",
        }
        if sources is not None:
            cuerpo["sources"] = sources
        if destinations is not None:
            cuerpo["destinations"] = destinations

        # El presupuesto se comprueba antes del espaciado: no tiene sentido
        # esperar segundo y medio para descubrir que no ibamos a llamar.
        self._spend(ENDPOINT_MATRIX)

        self.pacer.wait()
        self.request_count += 1

        try:
            respuesta = httpx.post(
                f"{self.base_url}/v2/matrix/{profile}",
                json=cuerpo,
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ORSError(f"no se pudo llamar a ORS: {exc}") from exc

        self._registrar(ENDPOINT_MATRIX, respuesta)

        datos = respuesta.json()
        distancias = datos.get("distances") or []
        # ORS devuelve segundos; el motor trabaja en minutos.
        duraciones = [
            [None if v is None else v / 60.0 for v in fila]
            for fila in (datos.get("durations") or [])
        ]
        return distancias, duraciones

    def directions(
        self, coords: list[tuple[float, float]], profile: str
    ) -> list[tuple[float, float]]:
        """El trazo por carretera que une los puntos, en el orden dado.

        Una peticion cubre el dia entero: ORS acepta varias paradas y devuelve
        una sola geometria que las recorre en orden. Pedir tramo por tramo
        costaria una peticion por tramo y el presupuesto diario no lo aguanta.

        Devuelve los vertices en (lat, lon), que es el orden del proyecto. ORS
        habla (lon, lat) en las dos direcciones —entrada y salida—, asi que hay
        dos inversiones y ninguna es opcional. Es el error mas comun contra
        esta API y no da fallo: devuelve una ruta plausible en el oceano Indico.

        Cada parada va con su radio de enganche: ver SNAP_RADIUS_M. Sin el, un
        volcan sin calle a 350 metros deja sin trazo al dia completo.
        """
        if len(coords) < 2:
            return []

        self._spend(ENDPOINT_DIRECTIONS)

        self.pacer.wait()
        self.request_count += 1

        try:
            respuesta = httpx.post(
                f"{self.base_url}/v2/directions/{profile}/geojson",
                json={
                    "coordinates": [[lon, lat] for lat, lon in coords],
                    # Uno por parada: ORS espera la lista del mismo largo.
                    "radiuses": [SNAP_RADIUS_M] * len(coords),
                },
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ORSError(f"no se pudo llamar a ORS: {exc}") from exc

        self._registrar(ENDPOINT_DIRECTIONS, respuesta)

        datos = respuesta.json()
        rasgos = datos.get("features") or []
        if not rasgos:
            return []

        vertices = ((rasgos[0].get("geometry") or {}).get("coordinates")) or []
        # Se leen solo las coordenadas y ningun otro campo de la respuesta a
        # proposito: partir el trazo por tramos se hace despues, buscando el
        # vertice mas cercano a cada parada. ORS publica indices de waypoint
        # que servirian, pero depender de ellos ata el dibujo a un campo mas
        # de un formato que ya cambio una vez, y el vertice mas cercano da lo
        # mismo porque ORS engancha cada parada a la red vial.
        return [(lat, lon) for lon, lat in vertices if lon is not None]

    def _raise_for_status(self, respuesta: httpx.Response) -> None:
        if respuesta.status_code == 200:
            return

        detalle = respuesta.text[:200]

        if respuesta.status_code == 401:
            raise ORSAuthError(f"llave rechazada por ORS: {detalle}")
        if respuesta.status_code == 403:
            raise ORSQuotaExhausted(f"cupo diario de ORS agotado: {detalle}")
        if respuesta.status_code == 429:
            raise ORSError(f"ritmo excedido en ORS: {detalle}")
        # 2010 y 6010 son "no encuentro este punto en la red de carreteras".
        if respuesta.status_code in (404, 413) or '"code":2010' in detalle:
            raise ORSUnroutable(f"punto sin carretera cercana: {detalle}")

        raise ORSError(f"ORS respondio {respuesta.status_code}: {detalle}")


def _remaining_header(respuesta) -> int | None:
    """Cupo restante segun ORS, si lo informa.

    Es la unica fuente fiable: nuestra cuenta se pierde al reiniciar el
    proceso y no ve las peticiones que hizo otra instancia con la misma llave.
    """
    valor = respuesta.headers.get("x-ratelimit-remaining")
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@dataclass
class MatrixStats:
    """De donde salio cada medida. Va al README y a los logs."""

    cached: int = 0
    fetched: int = 0
    estimated: int = 0
    requests: int = 0
    # Por que no hubo medidas reales, cuando no las hubo. Las tres causas
    # posibles piden cosas distintas: configurar una llave, esperar a manana, o
    # nada porque el lugar de verdad no tiene camino.
    reason: str | None = None

    @property
    def total(self) -> int:
        return self.cached + self.fetched + self.estimated

    @property
    def real_ratio(self) -> float:
        """Proporcion de pares con distancia real de carretera."""
        return 0.0 if not self.total else (self.cached + self.fetched) / self.total


@dataclass
class TravelMatrix:
    """Distancias precargadas, consultadas en memoria.

    Cumple TravelProvider igual que EstimatedTravel, y esa es toda la gracia:
    el motor de la fase 3 no sabe cual de los dos esta usando. `between` no
    hace ni una llamada de red ni una consulta a la base, porque se ejecuta
    dentro del 2-opt y ahi cualquier E/S seria ruinosa.
    """

    edges: dict[tuple[uuid.UUID, uuid.UUID], tuple[float, int]] = field(default_factory=dict)
    fallback: EstimatedTravel = field(default_factory=EstimatedTravel)
    stats: MatrixStats = field(default_factory=MatrixStats)

    def between(self, origen: Waypoint, destino: Waypoint) -> tuple[float, int]:
        clave = (getattr(origen, "id", None), getattr(destino, "id", None))
        medida = self.edges.get(clave)
        if medida is not None:
            # La friccion de llegar se suma aca y no en la cache: travel_edges
            # guarda el tiempo de conduccion que midio ORS, y mezclarlos
            # dejaria un numero que ya no se puede comparar con la fuente.
            km, minutos = medida
            return km, with_arrival_overhead(minutos, self.fallback.mode)
        # El respaldo ya la trae: EstimatedTravel la aplica por su cuenta.
        return self.fallback.between(origen, destino)


def _pairs(places: list) -> list[tuple[uuid.UUID, uuid.UUID]]:
    return [(a.id, b.id) for a in places for b in places if a.id != b.id]


def _blocks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def fetch_edges(
    places: list,
    mode: str,
    client: ORSClient,
    chunk_size: int = MAX_LOCATIONS_PER_REQUEST,
) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[float, int]]:
    """Pide a ORS todos los pares entre los lugares dados.

    Trocea en bloques para respetar el limite de pares por peticion. Con menos
    de cincuenta lugares es una sola llamada, que es el caso normal.

    Un bloque que ORS no puede resolver no aborta el resto: se registra y esos
    pares quedan sin medida, para que el llamador los cubra con la estimacion.
    """
    profile = ORS_PROFILES.get(mode, ORS_PROFILES["driving"])
    resultado: dict[tuple[uuid.UUID, uuid.UUID], tuple[float, int]] = {}
    bloques = _blocks(places, chunk_size)
    implausibles = 0

    for origenes in bloques:
        for destinos in bloques:
            if origenes is destinos:
                coords = [(p.lat, p.lon) for p in origenes]
                fuentes = destinos_idx = None
                filas, columnas = origenes, origenes
            else:
                coords = [(p.lat, p.lon) for p in origenes + destinos]
                fuentes = list(range(len(origenes)))
                destinos_idx = list(range(len(origenes), len(origenes) + len(destinos)))
                filas, columnas = origenes, destinos

            try:
                distancias, duraciones = client.matrix(coords, profile, fuentes, destinos_idx)
            except (ORSQuotaExhausted, ORSBudgetExhausted):
                # El cupo no se recupera reintentando. Se corta aqui y lo que
                # falte se estima.
                logger.warning("sin cupo para mas peticiones, el resto se estima")
                return resultado
            except ORSError as exc:
                logger.warning("bloque de matriz sin resolver, se estima: %s", exc)
                continue

            for i, origen in enumerate(filas):
                for j, destino in enumerate(columnas):
                    if origen.id == destino.id:
                        continue
                    km = _cell(distancias, i, j)
                    minutos = _cell(duraciones, i, j)
                    # Un nulo suelto es un punto que no engancho a la red. Se
                    # trata por celda y no por respuesta: que una cascada este
                    # lejos del camino no invalida los otros treinta pares.
                    if km is None or minutos is None:
                        continue
                    if not _is_plausible(origen, destino, float(km)):
                        implausibles += 1
                        continue
                    resultado[(origen.id, destino.id)] = (
                        round(float(km), 3),
                        max(1, round(float(minutos))),
                    )

    if implausibles:
        logger.warning(
            "%d pares descartados por medir menos que la linea recta: puntos "
            "enganchados al mismo nodo de la red vial",
            implausibles,
        )

    return resultado


# Margen para diferencias entre la geodesica y la proyeccion que usa ORS. Por
# debajo de esto, la medida es imposible y no un redondeo.
PLAUSIBILITY_MARGIN = 0.98


def _is_plausible(origen, destino, km: float) -> bool:
    """Una ruta por carretera no puede ser mas corta que la linea recta.

    Parece obvio y sin embargo ORS lo viola a diario: cuando dos puntos estan
    lejos de todo camino y enganchan al mismo nodo de la red, la matriz
    devuelve cero. No es un nulo, es una medida valida de un viaje que no
    existe, asi que el manejo de nulos no la atrapa.

    Sin esta comprobacion un itinerario dentro de un parque nacional sale con
    tres paradas separadas por cero kilometros, presentado como medicion real.
    Estar equivocado asi es peor que estimar: la estimacion al menos avisa.
    """
    recta = haversine_km(origen.lat, origen.lon, destino.lat, destino.lon)
    return km >= recta * PLAUSIBILITY_MARGIN


def _cell(matriz: list[list[float | None]], i: int, j: int) -> float | None:
    try:
        return matriz[i][j]
    except (IndexError, TypeError):
        return None


def split_by_stops(
    trazo: list[tuple[float, float]], paradas: list[tuple[float, float]]
) -> list[list[tuple[float, float]]]:
    """Parte el trazo del dia en un tramo por cada par de paradas consecutivas.

    Cada parada se ancla al vertice del trazo mas cercano a ella. Funciona
    porque el enrutador engancha cada parada a la red vial: el vertice mas
    cercano a la parada *es* su punto de entrada a la ruta.

    **Los anclajes se buscan hacia adelante y nunca retroceden.** Un trazo que
    pasa dos veces por el mismo cruce —ir y volver por la misma calle, que en
    un dia de montana es lo normal— tiene dos vertices casi identicos, y
    buscar el minimo global le asignaria a la tercera parada un vertice del
    principio. El tramo saldria vacio o del reves.

    Devuelve una lista de len(paradas) - 1 tramos. Un tramo puede salir vacio
    si el trazo no alcanza a cubrirlo, y quien dibuja tiene que aguantarlo.
    """
    if len(paradas) < 2 or len(trazo) < 2:
        return [[] for _ in range(max(0, len(paradas) - 1))]

    def cuadrado(a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    indices: list[int] = []
    desde = 0
    for numero, parada in enumerate(paradas):
        # La ultima parada ancla al final del trazo: es donde termina la ruta
        # que se pidio, y buscarla por cercania podria dejar fuera la cola.
        if numero == len(paradas) - 1:
            indices.append(len(trazo) - 1)
            break

        mejor = min(range(desde, len(trazo)), key=lambda i: cuadrado(trazo[i], parada))
        indices.append(mejor)
        desde = mejor

    tramos = []
    for inicio, fin in zip(indices, indices[1:], strict=False):
        # +1 para que el tramo incluya su vertice final: dos tramos
        # consecutivos comparten la parada que los une y el trazo no se corta.
        tramos.append(trazo[inicio : fin + 1] if fin > inicio else [])
    return tramos


def load_travel_matrix(
    places: list,
    mode: str = "driving",
    *,
    db=None,
    client: ORSClient | None = None,
    chunk_size: int = MAX_LOCATIONS_PER_REQUEST,
) -> TravelMatrix:
    """Arma la matriz de traslados: primero la cache, despues ORS, luego estimacion.

    Sin `db` no hay cache y sin `client` no hay red; con ninguno de los dos el
    resultado es equivalente a la estimacion pura. Eso hace que el camino de
    degradado sea el mismo codigo que el camino normal, y no una rama aparte
    que solo se ejercita cuando algo ya salio mal.
    """
    unicos = list({p.id: p for p in places}.values())
    fallback = EstimatedTravel(mode)
    stats = MatrixStats()

    if len(unicos) < 2:
        return TravelMatrix(fallback=fallback, stats=stats)

    profile = ORS_PROFILES.get(mode, ORS_PROFILES["driving"])
    edges: dict[tuple[uuid.UUID, uuid.UUID], tuple[float, int]] = {}

    if db is not None:
        edges = read_cached_edges(db, [p.id for p in unicos], profile)
        stats.cached = len(edges)

    faltantes = [par for par in _pairs(unicos) if par not in edges]

    if faltantes and client is not None:
        # Se piden todos los lugares aunque solo falten algunos pares: la
        # matriz es cuadrada por construccion y pedir un subconjunto de pares
        # no reduce el costo de la peticion.
        # El contador del cliente es acumulado desde que arranco el proceso, y
        # el cliente se comparte entre peticiones. Lo que interesa aqui es el
        # costo de ESTE itinerario, asi que se mide la diferencia.
        antes = client.request_count
        nuevas = fetch_edges(unicos, mode, client, chunk_size)
        nuevas = {par: valor for par, valor in nuevas.items() if par in set(faltantes)}
        stats.fetched = len(nuevas)
        stats.requests = client.request_count - antes
        edges.update(nuevas)

        if db is not None and nuevas:
            persist_edges(db, nuevas, profile, SOURCE_ORS)

    stats.estimated = len(_pairs(unicos)) - len(edges)

    if not stats.cached and not stats.fetched:
        if client is None:
            stats.reason = "no_key"
        elif not stats.requests or client.matrix_quota.remaining == 0:
            # Dos formas de quedarse sin cupo y las dos son la misma noticia:
            # el presupuesto local rechaza antes de llamar —cero peticiones— o
            # ORS contesta 403 "Quota exceeded", que SI cuenta como peticion
            # hecha. Sin el segundo caso, un cupo agotado se reportaba como
            # "estas paradas estan lejos de toda carretera", que es otra cosa y
            # se arregla de otra forma: una se espera, la otra no tiene arreglo.
            stats.reason = "no_quota"
        else:
            stats.reason = "unroutable"

    if stats.estimated:
        logger.info(
            "matriz de traslados: %d en cache, %d de ORS, %d estimados (%.0f%% reales)",
            stats.cached,
            stats.fetched,
            stats.estimated,
            stats.real_ratio * 100,
        )

    return TravelMatrix(edges=edges, fallback=fallback, stats=stats)


def read_cached_edges(
    db, place_ids: list[uuid.UUID], profile: str
) -> dict[tuple[uuid.UUID, uuid.UUID], tuple[float, int]]:
    """Lee de travel_edges los pares ya medidos entre estos lugares."""
    from sqlalchemy import select

    from app.models import TravelEdge

    filas = db.execute(
        select(
            TravelEdge.origin_id,
            TravelEdge.destination_id,
            TravelEdge.distance_km,
            TravelEdge.duration_minutes,
        ).where(
            TravelEdge.profile == profile,
            TravelEdge.origin_id.in_(place_ids),
            TravelEdge.destination_id.in_(place_ids),
            TravelEdge.source == SOURCE_ORS,
        )
    ).all()

    return {
        (f.origin_id, f.destination_id): (f.distance_km, f.duration_minutes) for f in filas
    }


def persist_edges(
    db,
    edges: dict[tuple[uuid.UUID, uuid.UUID], tuple[float, int]],
    profile: str,
    source: str = SOURCE_ORS,
) -> int:
    """Guarda las aristas nuevas. Si otra peticion ya las escribio, no pasa nada."""
    from sqlalchemy.dialects.postgresql import insert

    from app.models import TravelEdge

    if not edges:
        return 0

    valores = [
        {
            "origin_id": origen,
            "destination_id": destino,
            "profile": profile,
            "distance_km": km,
            "duration_minutes": minutos,
            "source": source,
        }
        for (origen, destino), (km, minutos) in edges.items()
    ]

    sentencia = insert(TravelEdge).values(valores)
    db.execute(
        sentencia.on_conflict_do_nothing(
            index_elements=["origin_id", "destination_id", "profile"]
        )
    )
    db.commit()
    return len(valores)


# Tolerancia de simplificacion del trazo, en grados.
#
# La geometria se guarda entera y se simplifica al servirla: la peticion es lo
# caro, asi que la cache tiene que quedarse con la mejor version disponible y
# la tolerancia poder cambiar sin volver a pedir nada.
#
# Medido sobre un tramo real de 18 km entre Ataco y Juayua, 451 vertices:
#
#     tolerancia  vertices     KB   desvio   px a z14   px a z16
#        0.00002       224    5.4      2 m        0.2        1.0
#        0.00005       132    3.2      6 m        0.6        2.4
#        0.00010        88    2.1     11 m        1.2        4.7
#        0.00050        39    0.9     54 m        5.8       23.2
#
# El trazo se dibuja con 3.5 px de grosor, asi que por debajo de un par de
# pixeles de desvio no hay nada que ver. En 0.00005 el trazo pesa un tercio y
# se separa de la carretera menos de lo que mide su propia linea hasta zoom 16,
# que es donde el mapa trabaja: encuadra los dias como maximo a 14 y vuela a 16
# al elegir una parada.
SIMPLIFY_TOLERANCE_DEG = 0.00005


def read_cached_geometry(
    db, place_ids: list[uuid.UUID], profile: str
) -> dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, float]]]:
    """Los trazos ya guardados entre estos lugares, simplificados al servir.

    ST_Simplify trabaja en grados sobre 4326, que es la unidad en la que se
    calibro la tolerancia. Devuelve (lat, lon) porque es el orden del proyecto;
    PostGIS entrega (lon, lat) como manda GeoJSON.
    """
    from sqlalchemy import text

    filas = db.execute(
        text("""
            SELECT origin_id, destination_id,
                   ST_AsGeoJSON(ST_Simplify(geometry, :tol)) AS trazo
            FROM route_legs
            WHERE profile = :profile
              AND origin_id = ANY(:ids)
              AND destination_id = ANY(:ids)
        """),
        {"tol": SIMPLIFY_TOLERANCE_DEG, "profile": profile, "ids": list(place_ids)},
    ).all()

    salida: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, float]]] = {}
    for fila in filas:
        if not fila.trazo:
            continue
        coords = json.loads(fila.trazo).get("coordinates") or []
        if len(coords) >= 2:
            salida[(fila.origin_id, fila.destination_id)] = [(lat, lon) for lon, lat in coords]
    return salida


def persist_geometry(
    db,
    trazos: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, float]]],
    profile: str,
) -> int:
    """Guarda el trazo de cada tramo en route_legs.

    No depende de que la distancia del par este medida. ORS mide el cupo por
    endpoint —observado en vivo: la matriz agotada y direcciones contestando—
    asi que un tramo puede tener trazo real y distancia estimada. Cuando esto
    era una columna de travel_edges, ese caso no se podia guardar y el trazo se
    volvia a pedir en cada consulta.
    """
    from sqlalchemy import text

    escritas = 0
    for (origen, destino), trazo in trazos.items():
        if len(trazo) < 2:
            continue
        wkt = "LINESTRING(" + ",".join(f"{lon} {lat}" for lat, lon in trazo) + ")"
        resultado = db.execute(
            text("""
                INSERT INTO route_legs
                    (origin_id, destination_id, profile, geometry)
                VALUES
                    (:origen, :destino, :profile, ST_GeomFromText(:wkt, 4326))
                ON CONFLICT (origin_id, destination_id, profile) DO NOTHING
            """),
            {"wkt": wkt, "origen": origen, "destino": destino, "profile": profile},
        )
        escritas += resultado.rowcount or 0

    if escritas:
        db.commit()
    return escritas


@dataclass
class GeometryStats:
    """De donde salio el trazo de cada tramo."""

    cached: int = 0
    fetched: int = 0
    straight: int = 0
    requests: int = 0

    @property
    def real_ratio(self) -> float:
        total = self.cached + self.fetched + self.straight
        return (self.cached + self.fetched) / total if total else 0.0


def load_route_geometry(
    days: list[tuple[str, list]],
    *,
    db=None,
    client: ORSClient | None = None,
) -> tuple[dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, float]]], GeometryStats]:
    """El trazo por carretera de cada tramo del itinerario.

    `days` es una lista de (modo, lugares ordenados) por dia. El modo va por
    dia porque el trazo depende de la red: el camino a pie entre dos plazas no
    es el mismo que el del carro, y dibujar uno por el otro seria mentir sobre
    el recorrido. Se
    pide **una peticion por dia**: ORS acepta varias paradas y devuelve una
    sola geometria que las recorre en orden, y despues se parte por tramos.
    Pedir tramo por tramo multiplicaria el costo por el numero de tramos.

    **La geometria cuesta aparte de la distancia.** La matriz cubre el
    itinerario entero con una peticion; la geometria necesita una por dia. Un
    itinerario de tres dias pasa de una peticion a cuatro, asi que la cache
    importa mas aca que en la matriz: el trazo entre dos puntos fijos tampoco
    cambia, y una zona ya recorrida no gasta nada.

    Igual que la matriz, nunca falla: sin llave, sin cupo o con un dia que ORS
    no puede enrutar, los tramos de ese dia se quedan sin trazo y quien dibuja
    tira la linea recta. El degradado es por tramo y no por itinerario, que es
    lo que permite decir la verdad de cada uno por separado.
    """
    perfiles = {ORS_PROFILES.get(modo, ORS_PROFILES["driving"]) for modo, _ in days}
    stats = GeometryStats()
    trazos: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, float]]] = {}

    tramos = [
        (a.id, b.id) for _, lugares in days for a, b in zip(lugares, lugares[1:], strict=False)
    ]
    if not tramos:
        return trazos, stats

    if db is not None:
        # Un perfil por modo presente: el trazo a pie y el del carro se
        # guardan en filas distintas porque son recorridos distintos.
        pendientes = set(tramos)
        ids = list({lugar.id for _, lugares in days for lugar in lugares})
        for perfil in perfiles:
            trazos.update(
                {
                    par: trazo
                    for par, trazo in read_cached_geometry(db, ids, perfil).items()
                    if par in pendientes
                }
            )
        stats.cached = len(trazos)

    if client is not None:
        antes = client.request_count
        nuevos: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[float, float]]] = {}
        # El perfil con el que se midio cada tramo, para guardarlo en el suyo.
        perfil_de: dict[tuple[uuid.UUID, uuid.UUID], str] = {}

        for modo, lugares in days:
            perfil = ORS_PROFILES.get(modo, ORS_PROFILES["driving"])
            pares = list(zip(lugares, lugares[1:], strict=False))
            # Un dia entero ya en cache no se vuelve a pedir. Se comprueba el
            # dia completo y no tramo por tramo porque la peticion es del dia:
            # si falta un solo tramo hay que pedirlo igual.
            if len(lugares) < 2 or all((a.id, b.id) in trazos for a, b in pares):
                continue

            try:
                trazo = client.directions([(p.lat, p.lon) for p in lugares], perfil)
            except (ORSError, ORSBudgetExhausted) as exc:
                logger.info("sin geometria para un dia: %s", exc)
                continue

            for (a, b), tramo in zip(
                pares,
                split_by_stops(trazo, [(p.lat, p.lon) for p in lugares]),
                strict=False,
            ):
                if len(tramo) >= 2:
                    nuevos[(a.id, b.id)] = tramo
                    perfil_de[(a.id, b.id)] = perfil

        stats.fetched = len(nuevos)
        stats.requests = client.request_count - antes
        trazos.update(nuevos)

        if db is not None and nuevos:
            for perfil in set(perfil_de.values()):
                persist_geometry(
                    db,
                    {par: t for par, t in nuevos.items() if perfil_de[par] == perfil},
                    perfil,
                )

    stats.straight = len(tramos) - len(trazos)
    return trazos, stats


@lru_cache(maxsize=1)
def client_from_settings() -> ORSClient | None:
    """Cliente compartido por todo el proceso, o None si no hay llave.

    **Tiene que ser uno solo.** El espaciado entre llamadas y el presupuesto
    diario viven dentro del cliente, asi que un cliente nuevo por peticion
    HTTP arranca siempre con el presupuesto entero y sin memoria del ritmo:
    los dos controles quedarian de adorno en cuanto hubiera mas de un
    itinerario. Pacer y DailyQuota usan candados, asi que compartirlo entre
    hilos es seguro.

    Devolver None en vez de fallar es deliberado: sin llave el proyecto sigue
    corriendo con distancias estimadas, que es lo que necesita alguien que
    acaba de clonar el repo y todavia no saco cuenta en ORS.
    """
    from app.core.config import settings

    if not settings.ors_api_key:
        return None

    return ORSClient(
        api_key=settings.ors_api_key,
        base_url=settings.ors_base_url,
        min_interval_seconds=settings.ors_min_interval_seconds,
        daily_budget=settings.ors_daily_budget,
    )


__all__ = [
    "SOURCE_ESTIMATED",
    "SOURCE_ORS",
    "GeometryStats",
    "MatrixStats",
    "DailyQuota",
    "ORSAuthError",
    "ORSBudgetExhausted",
    "ORSClient",
    "ORSError",
    "ORSQuotaExhausted",
    "ORSUnroutable",
    "Pacer",
    "TravelMatrix",
    "client_from_settings",
    "SIMPLIFY_TOLERANCE_DEG",
    "fetch_edges",
    "load_route_geometry",
    "load_travel_matrix",
    "persist_geometry",
    "read_cached_geometry",
    "split_by_stops",
]
