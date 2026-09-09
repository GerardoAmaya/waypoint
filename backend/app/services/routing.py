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

import logging
import threading
import time as _time
import uuid
from dataclasses import dataclass, field

import httpx

from app.services.geo import (
    ORS_PROFILES,
    SOURCE_ESTIMATED,
    SOURCE_ORS,
    EstimatedTravel,
    Waypoint,
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


class ORSClient:
    """Cliente del endpoint de matriz de OpenRouteService."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openrouteservice.org",
        min_interval_seconds: float = 1.5,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pacer = Pacer(min_interval_seconds)
        self.request_count = 0

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

        self._raise_for_status(respuesta)

        datos = respuesta.json()
        distancias = datos.get("distances") or []
        # ORS devuelve segundos; el motor trabaja en minutos.
        duraciones = [
            [None if v is None else v / 60.0 for v in fila]
            for fila in (datos.get("durations") or [])
        ]
        return distancias, duraciones

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


@dataclass
class MatrixStats:
    """De donde salio cada medida. Va al README y a los logs."""

    cached: int = 0
    fetched: int = 0
    estimated: int = 0
    requests: int = 0

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
            return medida
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
            except ORSQuotaExhausted:
                # El cupo no se recupera reintentando. Se corta aqui y lo que
                # falte se estima.
                logger.warning("cupo de ORS agotado, el resto se estima")
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
                    resultado[(origen.id, destino.id)] = (
                        round(float(km), 3),
                        max(1, round(float(minutos))),
                    )

    return resultado


def _cell(matriz: list[list[float | None]], i: int, j: int) -> float | None:
    try:
        return matriz[i][j]
    except (IndexError, TypeError):
        return None


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
        nuevas = fetch_edges(unicos, mode, client, chunk_size)
        nuevas = {par: valor for par, valor in nuevas.items() if par in set(faltantes)}
        stats.fetched = len(nuevas)
        stats.requests = client.request_count
        edges.update(nuevas)

        if db is not None and nuevas:
            persist_edges(db, nuevas, profile, SOURCE_ORS)

    stats.estimated = len(_pairs(unicos)) - len(edges)

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


def client_from_settings() -> ORSClient | None:
    """Cliente listo para usar, o None si no hay llave configurada.

    Devolver None en vez de fallar es deliberado: sin llave el proyecto sigue
    corriendo con distancias estimadas, que es exactamente lo que necesita
    alguien que acaba de clonar el repo y todavia no saco cuenta en ORS.
    """
    from app.core.config import settings

    if not settings.ors_api_key:
        return None

    return ORSClient(
        api_key=settings.ors_api_key,
        base_url=settings.ors_base_url,
        min_interval_seconds=settings.ors_min_interval_seconds,
    )


__all__ = [
    "SOURCE_ESTIMATED",
    "SOURCE_ORS",
    "MatrixStats",
    "ORSAuthError",
    "ORSClient",
    "ORSError",
    "ORSQuotaExhausted",
    "ORSUnroutable",
    "Pacer",
    "TravelMatrix",
    "client_from_settings",
    "fetch_edges",
    "load_travel_matrix",
]
