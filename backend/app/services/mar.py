"""El estado del mar, de la API marina de Open-Meteo.

**Existe porque el pais vende Surf City y la aplicacion no sabia nada del
mar.** Un dia en El Tunco sin decir como esta la marejada es un dia a medias:
1.2 m con periodo de 13 s del sur es marejada de fondo limpia, y 1.2 m con
periodo de 7 s es mar picado. El mismo numero de altura, dos dias distintos.

Medido antes de construirlo, sobre el archivo marino de El Tunco: la mediana
de altura pasa de 0.90 m en enero a 1.36 m en julio —el pico de las marejadas
del Pacifico sur— y entre playas hay un 40% de diferencia el mismo dia. O sea
que varia por fecha y por sitio, que es lo que separa un dato de un adorno.

Mismo proveedor que el clima, misma filosofia: sin llave, cache de una hora,
y **nunca falla**. Un dia sin oleaje se arma igual y la respuesta dice por que
falta.

Datos de Open-Meteo, licencia CC-BY 4.0.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Protocol

import httpx

from app.services.geo import haversine_km

logger = logging.getLogger(__name__)

BASE_URL = "https://marine-api.open-meteo.com/v1/marine"

# El horizonte del servicio marino, mas corto que el del clima.
HORIZONTE_PRONOSTICO_DIAS = 7

CACHE_SEGUNDOS = 3600
PRECISION_CLAVE = 2

# El contorno del Pacifico salvadoreño, en (lon, lat).
#
# **Derivado del catalogo, no escrito a mano.** La frontera sur del pais es el
# mar, asi que el lugar mas austral de cada franja de longitud esta en la
# costa; se toma el minimo de cada vecindad para quitar los picos tierra
# adentro donde el catalogo no llega a la playa. Lo produce
# `scripts/trazar_costa.py`.
#
# Hace falta porque **la API marina no sirve para saber que es costa**: su
# rejilla se engancha a la celda con agua mas cercana y le da 0.92 m de
# oleaje a Concepcion de Ataco, que esta en la montaña a treinta kilometros.
COSTA: tuple[tuple[float, float], ...] = (
    (-90.1, 13.669),
    (-90.0, 13.625),
    (-89.9, 13.490),
    (-89.8, 13.490),
    (-89.7, 13.490),
    (-89.6, 13.495),
    (-89.5, 13.485),
    (-89.4, 13.467),
    (-89.3, 13.432),
    (-89.2, 13.369),
    (-89.1, 13.322),
    (-89.0, 13.271),
    (-88.9, 13.270),
    (-88.8, 13.270),
    (-88.7, 13.225),
    (-88.6, 13.183),
    (-88.5, 13.168),
    (-88.4, 13.168),
    (-88.3, 13.167),
    (-88.2, 13.166),
    (-88.1, 13.159),
    (-88.0, 13.159),
    (-87.9, 13.159),
    (-87.8, 13.159),
    (-87.7, 13.166),
)

# Hasta donde un destino cuenta como "de playa".
#
# Medido contra el contorno de arriba: El Cuco 2.0 km, El Tunco 3.6, El Zonte
# 5.3, Costa del Sol 5.5, La Libertad 6.7; y tierra adentro Santa Tecla 26.4,
# San Salvador 30.3, Ataco 31.8, Santa Ana 55.7. Entre 7 y 26 no hay nada, asi
# que el corte va holgado en medio.
COSTERO_KM = 12.0


class MarError(Exception):
    """El servicio marino no contesto, o contesto algo que no se entiende."""


def km_a_la_costa(lat: float, lon: float) -> float:
    """Distancia al punto mas cercano del contorno."""
    return min(haversine_km(lat, lon, clat, clon) for clon, clat in COSTA)


def es_costero(lat: float, lon: float) -> bool:
    """Si ese punto da para hablar del mar."""
    return km_a_la_costa(lat, lon) <= COSTERO_KM


@dataclass(frozen=True)
class DiaDeMar:
    """Como esta el mar un dia.

    `periodo_s` importa tanto como la altura y por eso viaja al lado: es lo
    que separa la marejada de fondo del viento local.
    """

    fecha: date
    ola_m: float
    periodo_s: float
    direccion_grados: int
    agua_c: float | None = None


class MarProvider(Protocol):
    """De donde sale el estado del mar.

    Protocolo y no clase concreta por lo mismo que el clima: los tests dictan
    la marejada en vez de pedirla por red.
    """

    def marine(
        self, lat: float, lon: float, desde: date, hasta: date
    ) -> dict[date, DiaDeMar]: ...


@dataclass
class _Entrada:
    valor: dict[date, DiaDeMar]
    momento: float


class OpenMeteoMarine:
    """El proveedor de verdad. Sin llave, igual que el del clima."""

    def __init__(self, timeout: float = 4.0) -> None:
        self._timeout = timeout
        self._cache: dict[tuple, _Entrada] = {}
        self._candado = threading.Lock()

    def marine(self, lat: float, lon: float, desde: date, hasta: date) -> dict[date, DiaDeMar]:
        clave = (round(lat, PRECISION_CLAVE), round(lon, PRECISION_CLAVE), desde, hasta)
        ahora = _time.monotonic()

        with self._candado:
            entrada = self._cache.get(clave)
            if entrada is not None and ahora - entrada.momento < CACHE_SEGUNDOS:
                return entrada.valor

        try:
            respuesta = httpx.get(
                BASE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": ("wave_height_max,wave_period_max,wave_direction_dominant"),
                    "hourly": "sea_surface_temperature",
                    "timezone": "America/El_Salvador",
                    "start_date": desde.isoformat(),
                    "end_date": hasta.isoformat(),
                },
                timeout=self._timeout,
            )
            respuesta.raise_for_status()
            dias = _parsear(respuesta.json())
        except httpx.HTTPError as exc:
            raise MarError(f"no se pudo pedir el estado del mar: {exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise MarError(f"el servicio marino devolvio algo raro: {exc}") from exc

        with self._candado:
            self._cache[clave] = _Entrada(valor=dias, momento=ahora)
        return dias


def _parsear(cuerpo: dict) -> dict[date, DiaDeMar]:
    diario = cuerpo.get("daily") or {}
    fechas = diario.get("time") or []
    alturas = diario.get("wave_height_max") or []
    periodos = diario.get("wave_period_max") or []
    direcciones = diario.get("wave_direction_dominant") or []

    # La temperatura viene por hora; se toma la de mediodia, que es cuando la
    # gente se mete al agua.
    aguas: dict[str, float] = {}
    horario = cuerpo.get("hourly") or {}
    for marca, valor in zip(
        horario.get("time") or [], horario.get("sea_surface_temperature") or [], strict=False
    ):
        fecha, hora = marca.split("T")
        if hora.startswith("12") and valor is not None:
            aguas[fecha] = float(valor)

    salida: dict[date, DiaDeMar] = {}
    for i, marca in enumerate(fechas):
        altura = alturas[i] if i < len(alturas) else None
        periodo = periodos[i] if i < len(periodos) else None
        # **Sin altura o sin periodo no hay dia.** Un punto tierra adentro
        # devuelve nulos, y la mitad del dato no permite decir si la marejada
        # es de fondo o es viento, que es lo unico que valia la pena decir.
        if altura is None or periodo is None:
            continue
        direccion = direcciones[i] if i < len(direcciones) else None
        salida[date.fromisoformat(marca)] = DiaDeMar(
            fecha=date.fromisoformat(marca),
            ola_m=round(float(altura), 2),
            periodo_s=round(float(periodo), 1),
            direccion_grados=int(direccion) if direccion is not None else 0,
            agua_c=round(aguas[marca], 1) if marca in aguas else None,
        )
    return salida


@dataclass
class MarDelViaje:
    """El mar de todos los dias del itinerario, y por que falta si falta."""

    dias: dict[date, DiaDeMar] = field(default_factory=dict)
    reason: str | None = None

    @property
    def hay(self) -> bool:
        return bool(self.dias)

    def de(self, fecha: date | None) -> DiaDeMar | None:
        if fecha is None:
            return None
        return self.dias.get(fecha)


def load_marine(
    lat: float,
    lon: float,
    start_date: date | None,
    days: int,
    today: date,
    provider: MarProvider | None = None,
) -> MarDelViaje:
    """Trae el estado del mar del viaje, o explica por que no se pudo.

    No lanza, igual que el clima: un itinerario se arma con mar o sin el.

    **El primer corte es la costa.** Pedirle oleaje a un viaje por Suchitoto
    gasta una peticion para recibir nulos, y la API ademas los rellena con la
    celda marina mas cercana cuando le da la gana: Ataco, en la montaña, sale
    con 0.92 m. El contorno de la costa decide antes de preguntar.
    """
    if not es_costero(lat, lon):
        return MarDelViaje(reason="tierra_adentro")
    if start_date is None:
        return MarDelViaje(reason="sin_fecha")
    if provider is None:
        return MarDelViaje(reason="sin_proveedor")

    limite = today + timedelta(days=HORIZONTE_PRONOSTICO_DIAS - 1)
    if start_date > limite:
        return MarDelViaje(reason="fuera_de_pronostico")

    try:
        dias = provider.marine(
            lat, lon, start_date, min(start_date + timedelta(days=days - 1), limite)
        )
    except MarError as exc:
        logger.warning("sin estado del mar para el itinerario: %s", exc)
        return MarDelViaje(reason="sin_servicio")

    return MarDelViaje(dias=dias) if dias else MarDelViaje(reason="sin_servicio")


def provider_from_settings() -> MarProvider | None:
    """El proveedor segun la configuracion, o None si el mar esta apagado.

    Uno solo para todo el proceso, porque el cache vive dentro del objeto.
    """
    from app.core.config import settings

    if not settings.weather_enabled:
        return None
    return _compartido(settings.weather_timeout_seconds)


@lru_cache(maxsize=1)
def _compartido(timeout: float) -> OpenMeteoMarine:
    return OpenMeteoMarine(timeout=timeout)
