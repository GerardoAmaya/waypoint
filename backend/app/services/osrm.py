"""Medir traslados contra un OSRM propio en vez de contra ORS.

**El cupo de ORS era el techo del proyecto, no un detalle de configuracion.**
Con 450 matrices y 1.800 trazos al dia, armar un itinerario de nueve paradas
gasta una matriz y un trazo; la bateria de evaluacion arma decenas seguidas, y
a media corrida se queda sin cupo y mide el resto en linea recta. Los numeros
con los que se afinaron los presupuestos de kilometros salian, entonces, en
parte de distancias estimadas.

OSRM resuelve eso de raiz: el extracto de El Salvador son 33 MB, cabe en un
contenedor al lado de la base, y contesta en milisegundos sin cupo, sin llave y
sin espaciado entre llamadas. Lo que se pierde es el detalle de ORS para el
peaton —OSRM trae un perfil a pie mas simple— y por eso ORS sigue siendo el
proveedor por defecto: OSRM entra solo si esta configurado.

**Escribe en la misma cache que ORS, con el mismo `profile`.** Una arista
medida es una arista medida: el dia que alguien levante OSRM en local, las
filas que ya habia de ORS le sirven igual, y al reves. Lo que cambia es la
columna `source`, que dice quien la midio, y se usa para saber de donde salio
un numero, no para decidir si vale.
"""

from __future__ import annotations

import logging

import httpx

from app.services.routing import RutaError

logger = logging.getLogger(__name__)

# Nuestros perfiles de cache traducidos al servicio que los contesta. Son dos
# contenedores y no uno porque osrm-routed sirve un solo perfil: el que se
# preparo al construir el grafo. El nombre que va en la URL lo ignora, asi que
# aqui lo que elige el perfil es a que puerto se llama.
SERVICIOS = {"driving-car": "car", "foot-walking": "foot"}

# Lo mismo que SNAP_RADIUS_M en routing.py, en la forma que espera OSRM. Sin
# esto, un volcan sin calle a 350 metros deja sin trazo al dia completo.
RADIO_DE_ENGANCHE_M = 5000


class SinLimite:
    """El cupo de un servidor propio.

    Existe para que OSRMClient ofrezca la misma superficie que ORSClient, que
    es lo que leen el endpoint de estado y el motor. `remaining` da None, que
    es lo que ese campo ya significa en ORS cuando todavia no hay noticia del
    servidor: "no hay un numero que mostrar". Decir un entero cualquiera seria
    inventar un techo que no existe.
    """

    budget = 0

    @property
    def remaining(self) -> int | None:
        return None

    @property
    def own_remaining(self) -> int:
        return 0

    def try_spend(self) -> bool:
        return True

    def sync_with_server(self, remaining: int | None) -> None:
        return None


class OSRMClient:
    """Cliente de un OSRM propio: tabla para distancias, ruta para el trazo.

    Un servicio por perfil. Si falta el del perfil que se pide, se levanta
    RutaError y el motor estima ese tramo, igual que cuando ORS no contesta:
    tener el de coche y no el de a pie es una instalacion a medias razonable, y
    no tiene por que tumbar los dias en carro.
    """

    def __init__(self, urls: dict[str, str], timeout: float = 10.0) -> None:
        self.urls = {perfil: url.rstrip("/") for perfil, url in urls.items()}
        self.timeout = timeout
        self.request_count = 0
        self._cupo = SinLimite()

    @property
    def matrix_quota(self) -> SinLimite:
        return self._cupo

    @property
    def directions_quota(self) -> SinLimite:
        return self._cupo

    def _base(self, profile: str) -> str:
        servicio = SERVICIOS.get(profile)
        url = self.urls.get(servicio) if servicio else None
        if not url:
            raise RutaError(f"no hay un OSRM configurado para el perfil {profile}")
        return url

    def matrix(
        self,
        coords: list[tuple[float, float]],
        profile: str,
        sources: list[int] | None = None,
        destinations: list[int] | None = None,
    ) -> tuple[list[list[float | None]], list[list[float | None]]]:
        """Kilometros y minutos entre cada origen y cada destino.

        `coords` va en (lat, lon) porque es el orden del proyecto. OSRM, como
        ORS, habla (lon, lat), y la inversion no es opcional: al reves devuelve
        rutas plausibles en el oceano Indico sin dar error.
        """
        base = self._base(profile)
        parametros: dict[str, str] = {"annotations": "distance,duration"}
        if sources is not None:
            parametros["sources"] = ";".join(str(i) for i in sources)
        if destinations is not None:
            parametros["destinations"] = ";".join(str(i) for i in destinations)

        datos = self._pedir(f"{base}/table/v1/driving/{_puntos(coords)}", parametros)

        # OSRM da metros y segundos; el proyecto trabaja en kilometros y
        # minutos, y es la misma conversion que ya hace la rama de ORS.
        distancias = [
            [None if v is None else v / 1000.0 for v in fila]
            for fila in (datos.get("distances") or [])
        ]
        duraciones = [
            [None if v is None else v / 60.0 for v in fila]
            for fila in (datos.get("durations") or [])
        ]
        return distancias, duraciones

    def directions(
        self, coords: list[tuple[float, float]], profile: str
    ) -> list[tuple[float, float]]:
        """El trazo por carretera que une los puntos, en el orden dado.

        Una peticion cubre el dia entero, igual que en ORS. Devuelve los
        vertices en (lat, lon).
        """
        if len(coords) < 2:
            return []

        base = self._base(profile)
        datos = self._pedir(
            f"{base}/route/v1/driving/{_puntos(coords)}",
            {
                "overview": "full",
                "geometries": "geojson",
                "radiuses": ";".join([str(RADIO_DE_ENGANCHE_M)] * len(coords)),
            },
        )

        rutas = datos.get("routes") or []
        if not rutas:
            return []
        vertices = ((rutas[0].get("geometry") or {}).get("coordinates")) or []
        return [(lat, lon) for lon, lat in vertices if lon is not None]

    def _pedir(self, url: str, parametros: dict[str, str]) -> dict:
        self.request_count += 1
        try:
            respuesta = httpx.get(url, params=parametros, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise RutaError(f"no se pudo llamar a OSRM: {exc}") from exc

        # **El codigo va en el cuerpo, no en el estado HTTP.** OSRM contesta
        # 400 con "NoSegment" cuando un punto queda lejos de toda calle, que es
        # un caso normal aca —cerros, cascadas— y no un fallo del servicio.
        try:
            datos = respuesta.json()
        except ValueError as exc:
            raise RutaError(f"OSRM respondio algo que no es JSON: {exc}") from exc

        codigo = datos.get("code")
        if codigo != "Ok":
            raise RutaError(f"OSRM respondio {codigo}: {datos.get('message', '')[:160]}")
        return datos


def _puntos(coords: list[tuple[float, float]]) -> str:
    """Las coordenadas como las pide la URL de OSRM: lon,lat separadas por ;."""
    return ";".join(f"{lon},{lat}" for lat, lon in coords)
