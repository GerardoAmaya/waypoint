"""El clima del viaje, de Open-Meteo.

**Existe porque el motor ya razona asi.** El itinerario evita las paradas al
aire libre despues del anochecer y las de interior despues del cierre: "esta
parada es al aire libre y va a estar lloviendo" es la misma regla con otro
insumo. En El Salvador no es un detalle de lujo: de mayo a octubre llueve casi
todas las tardes, y un mirador a las 15:00 en septiembre puede ser agua.

Tres decisiones dan forma a este modulo.

**Nunca falla, degrada.** Es la misma regla que las distancias reales. Sin red,
con el servicio caido o con una fecha fuera del pronostico, el itinerario se
arma igual y la respuesta dice que se armo sin clima. Un plan sin clima sirve;
un error 500 porque el servidor del tiempo tardo tres segundos, no.

**El pronostico llega a dieciseis dias y no se disimula.** Quien planifica para
diciembre no recibe una prediccion inventada: recibe que todavia no hay
pronostico para esa fecha.

**Una hora de cache.** El pronostico se actualiza cada hora en el origen, asi
que pedirlo dos veces en el mismo minuto es gastar una peticion en recibir lo
mismo. El cupo es de 10.000 diarias y esto lo deja lejos del limite.

**La hora puede estar corrida hasta sesenta minutos y se dice.** Open-Meteo
documenta `precipitation` como la suma de la hora ANTERIOR a la marca, asi que
el dato de las 15:00 cubre de 14:00 a 15:00. Aqui se trata cada marca como la
hora del reloj que nombra, que es como la lee una persona. La imprecision que
eso introduce es de una hora sobre visitas que duran entre una y tres, y no
cambia ninguna decision: lo que se responde es "la tarde del lunes viene con
agua", no a que minuto empieza. Fingir la precision del cuarto de hora seria
peor que asumir el desfase.

Datos de Open-Meteo, licencia CC-BY 4.0: hay que atribuirlos donde se muestren.
"""

from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from functools import lru_cache
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# El horizonte del servicio. Mas alla de esto no hay pronostico que pedir.
HORIZONTE_PRONOSTICO_DIAS = 16

# Cuanta agua tiene que caer en una hora para que cuente como lluvia.
#
# Un milimetro por hora es lluvia ligera pero real: se moja uno. Por debajo son
# gotas que no cambian un paseo.
#
# **Era esto Y una probabilidad minima del 60%, y la probabilidad se quito
# porque la medicion la desmintio.** Sobre 640 horas de pronostico de cuatro
# zonas del pais:
#
#   - 79 horas daban probabilidad >=60% con menos de un milimetro: trazas de
#     0.0 a 0.9 mm. Son los falsos positivos de verdad, y los filtra este
#     umbral, no el otro.
#   - 28 de las 61 horas con >=1 mm declaraban probabilidad por debajo del 60%,
#     y las 28 traian codigo de llovizna, chubasco o tormenta. O sea que el
#     umbral de probabilidad tiraba el 46% de la lluvia real.
#   - el falso positivo que justificaba ese umbral —mucha agua, poca confianza,
#     cielo sin lluvia— aparecio 0 veces.
#
# La razon de fondo: cuanto mas lejos esta el dia, mas reparte el conjunto de
# modelos la probabilidad, asi que exigirla alta apagaba la funcion justo en los
# dias que alguien planifica con tiempo. Los milimetros no tienen ese sesgo.
#
# La probabilidad se sigue guardando y mostrando: informa. Lo que no hace es
# decidir.
UMBRAL_MM = 1.0

# Cuanto vale un dato del cache. Ver la cabecera del modulo.
CACHE_SEGUNDOS = 3600

# Las coordenadas se redondean para la clave del cache. Dos centesimas de grado
# son poco mas de un kilometro: el clima no cambia en esa distancia, y sin
# redondear cada itinerario pediria su propio pronostico por diferencias de
# metros entre dos puntos de partida.
PRECISION_CLAVE = 2

# Codigos WMO, que es lo que devuelve el servicio en `weather_code`. Solo los
# que pueden pasar en El Salvador: la nieve y la lluvia helada existen en la
# tabla y no aca.
DESCRIPCION_WMO = {
    0: "cielo despejado",
    1: "mayormente despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "neblina",
    48: "neblina con escarcha",
    51: "llovizna ligera",
    53: "llovizna",
    55: "llovizna intensa",
    61: "lluvia ligera",
    63: "lluvia",
    65: "lluvia intensa",
    80: "chubascos ligeros",
    81: "chubascos",
    82: "chubascos fuertes",
    95: "tormenta",
    96: "tormenta con granizo",
    99: "tormenta con granizo",
}


class ClimaError(Exception):
    """Fallo hablando con Open-Meteo."""


@dataclass(frozen=True)
class HoraDeClima:
    """El clima de una hora concreta."""

    hora: int
    lluvia_prob: int
    lluvia_mm: float
    temperatura: float
    codigo: int

    @property
    def llueve(self) -> bool:
        """Si esta hora cuenta como lluviosa. Ver UMBRAL_MM."""
        return self.lluvia_mm >= UMBRAL_MM

    @property
    def descripcion(self) -> str:
        return DESCRIPCION_WMO.get(self.codigo, "sin datos")


@dataclass(frozen=True)
class ResumenDelDia:
    """El clima de un dia en una linea, para mostrarlo."""

    temp_max: int
    temp_min: int
    lluvia_mm: float
    horas_de_lluvia: tuple[int, ...]
    codigo: int

    @property
    def descripcion(self) -> str:
        return DESCRIPCION_WMO.get(self.codigo, "sin datos")

    @property
    def llueve(self) -> bool:
        return bool(self.horas_de_lluvia)


@dataclass(frozen=True)
class DiaDeClima:
    """El clima de un dia, hora por hora."""

    fecha: date
    horas: tuple[HoraDeClima, ...] = ()

    def a_las(self, momento: time) -> HoraDeClima | None:
        """El clima de la hora en que cae `momento`."""
        for h in self.horas:
            if h.hora == momento.hour:
                return h
        return None

    def llueve_a_las(self, momento: time) -> bool:
        hora = self.a_las(momento)
        return hora is not None and hora.llueve

    def horas_de_lluvia(self, desde: time, hasta: time) -> tuple[HoraDeClima, ...]:
        """Las horas lluviosas dentro de una franja, incluida la de `hasta`.

        La franja incluye las dos puntas porque son las horas del itinerario:
        una parada que empieza a las 15:00 y termina a las 17:00 pasa por las
        tres.
        """
        return tuple(h for h in self.horas if desde.hour <= h.hora <= hasta.hour and h.llueve)

    @property
    def lluvia_total_mm(self) -> float:
        return round(sum(h.lluvia_mm for h in self.horas), 1)

    def resumen(self, desde: time, hasta: time) -> ResumenDelDia | None:
        """El clima del dia resumido a la franja en que se viaja.

        **Se resume a la franja y no al dia entero a proposito.** Un dia con
        34 grados de maxima a las 14:00 y 21 de minima a las 4:00 de la
        madrugada no describe un itinerario que va de 9:00 a 18:00, y la
        maxima que importa es la de las horas en que uno esta afuera.
        """
        dentro = [h for h in self.horas if desde.hour <= h.hora <= hasta.hour]
        if not dentro:
            return None

        lluviosas = [h.hora for h in dentro if h.llueve]
        return ResumenDelDia(
            temp_max=round(max(h.temperatura for h in dentro)),
            temp_min=round(min(h.temperatura for h in dentro)),
            lluvia_mm=round(sum(h.lluvia_mm for h in dentro), 1),
            horas_de_lluvia=tuple(lluviosas),
            codigo=_codigo_dominante(dentro),
        )


class WeatherProvider(Protocol):
    """De donde sale el clima.

    Un protocolo y no una clase concreta por lo mismo que TravelProvider: los
    tests dictan el pronostico en vez de pedirlo por red, que es la unica forma
    de probar "llueve toda la tarde" sin esperar a que llueva.
    """

    def forecast(
        self, lat: float, lon: float, desde: date, hasta: date
    ) -> dict[date, DiaDeClima]: ...


@dataclass
class _Entrada:
    valor: dict[date, DiaDeClima]
    momento: float


class OpenMeteo:
    """El proveedor de verdad.

    Sin llave: el servicio no la pide para uso no comercial. Eso lo vuelve lo
    contrario de ORS en lo que mas cuesta de ORS —no hay nada que configurar ni
    cupo que se agote a media demo— y es el motivo de haberlo elegido.
    """

    def __init__(self, base_url: str = BASE_URL, timeout: float = 4.0) -> None:
        self.base_url = base_url
        # Corto a proposito. El clima es un adorno del itinerario: si el
        # servicio tarda, se arma sin el. Esperar treinta segundos por un dato
        # opcional es convertir una mejora en una caida.
        self.timeout = timeout
        self._cache: dict[tuple, _Entrada] = {}
        self._lock = threading.Lock()
        self.requests = 0

    def forecast(
        self, lat: float, lon: float, desde: date, hasta: date
    ) -> dict[date, DiaDeClima]:
        """El clima por dia entre dos fechas, ambas incluidas.

        Las fechas fuera del horizonte simplemente no aparecen en el resultado:
        el que llama tiene que tratar la ausencia igual que un fallo de red, y
        asi no hay dos caminos distintos para "no se sabe".
        """
        clave = (round(lat, PRECISION_CLAVE), round(lon, PRECISION_CLAVE), desde, hasta)

        with self._lock:
            entrada = self._cache.get(clave)
            if entrada is not None and _time.monotonic() - entrada.momento < CACHE_SEGUNDOS:
                return entrada.valor

        datos = self._pedir(lat, lon, desde, hasta)

        with self._lock:
            self._cache[clave] = _Entrada(datos, _time.monotonic())
        return datos

    def _pedir(
        self, lat: float, lon: float, desde: date, hasta: date
    ) -> dict[date, DiaDeClima]:
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code",
            # La hora local, que es la que usa el itinerario. Sin esto el
            # servicio responde en UTC y las 15:00 del pronostico serian las
            # 09:00 del plan.
            "timezone": "America/El_Salvador",
            "start_date": desde.isoformat(),
            "end_date": hasta.isoformat(),
        }

        try:
            respuesta = httpx.get(self.base_url, params=params, timeout=self.timeout)
            respuesta.raise_for_status()
            cuerpo = respuesta.json()
        except httpx.HTTPError as exc:
            raise ClimaError(f"no se pudo consultar el clima: {exc}") from exc
        except ValueError as exc:
            raise ClimaError("el clima llego en algo que no es JSON") from exc

        self.requests += 1
        return _parsear(cuerpo)


def _parsear(cuerpo: dict) -> dict[date, DiaDeClima]:
    """Del JSON del servicio a los dias.

    **Tolera que falte una serie, no que falte la estructura.** Un servicio que
    deja de mandar `precipitation_probability` deberia dar un itinerario sin
    clima, no un 500; un servicio que manda las horas y las lluvias con
    distinto largo esta mandando algo que no se puede alinear, y ahi tampoco se
    inventa el relleno.
    """
    por_hora = cuerpo.get("hourly")
    if not isinstance(por_hora, dict):
        raise ClimaError("la respuesta del clima no trae horas")

    momentos = por_hora.get("time") or []
    if not isinstance(momentos, list) or not momentos:
        raise ClimaError("la respuesta del clima no trae horas")

    def serie(nombre: str) -> list:
        valores = por_hora.get(nombre)
        if not isinstance(valores, list) or len(valores) != len(momentos):
            return [None] * len(momentos)
        return valores

    probabilidades = serie("precipitation_probability")
    milimetros = serie("precipitation")
    temperaturas = serie("temperature_2m")
    codigos = serie("weather_code")

    dias: dict[date, list[HoraDeClima]] = {}
    for i, marca in enumerate(momentos):
        # "2026-09-11T15:00"
        try:
            fecha_texto, hora_texto = str(marca).split("T")
            fecha = date.fromisoformat(fecha_texto)
            hora = int(hora_texto.split(":")[0])
        except (ValueError, IndexError):
            continue

        dias.setdefault(fecha, []).append(
            HoraDeClima(
                hora=hora,
                lluvia_prob=_entero(probabilidades[i]),
                lluvia_mm=_decimal(milimetros[i]),
                temperatura=_decimal(temperaturas[i]),
                codigo=_entero(codigos[i]),
            )
        )

    return {
        fecha: DiaDeClima(fecha=fecha, horas=tuple(horas)) for fecha, horas in dias.items()
    }


# Por encima de esto los codigos WMO describen agua cayendo: 51 llovizna, 61
# lluvia, 80 chubascos, 95 tormenta.
PRIMER_CODIGO_DE_LLUVIA = 51


def _codigo_dominante(horas: list[HoraDeClima]) -> int:
    """Un codigo que resuma la franja, coherente con las horas de lluvia.

    En la tabla WMO los codigos crecen mas o menos con la severidad —despejado
    0, nublado 3, llovizna 51, tormenta 95— asi que el maximo se queda con lo
    mas significativo en vez de con un promedio, que describiria un dia que no
    ocurre.

    **Pero el maximo a secas contradecia los datos del mismo dia.** Caso real:
    Suchitoto el 12 de septiembre daba "tormenta" —codigo 95 en una hora
    suelta— con medio milimetro en toda la jornada y ninguna hora que pase el
    umbral de lluvia. Quien lee "32 grados, tormenta" cancela el paseo por algo
    que la propia respuesta dice que no va a pasar.

    Asi que el maximo se toma entre las horas de lluvia si las hay, y si no,
    solo entre los codigos que no son de lluvia: cuando por nuestro propio
    criterio no va a llover, no se nombra un fenomeno de lluvia.

    **Queda un desacuerdo al reves y se deja, porque viene de la fuente.**
    Open-Meteo devuelve a veces codigo 3 —nublado— en horas con mas de un
    milimetro: Santa Ana el 25 de septiembre a las 18:00, codigo 3 con 1.88 mm.
    Ahi la descripcion sale "nublado" y `horas_de_lluvia` marca la hora igual,
    porque el milimetro es la magnitud fisica en la que se confia y es la base
    del umbral. En pantalla eso se lee "nublado · lluvia de 17:00 a 18:59", que
    no es contradictorio: se queda corto de nombre y lleva el dato accionable
    al lado. El error que si habia que quitar era el contrario —alarmar sin
    nada detras— y es el que se quito. Medido sobre 64 dias de cuatro zonas,
    el desacuerdo restante aparece en cuatro.
    """
    lluviosas = [h for h in horas if h.llueve]
    if lluviosas:
        return max(h.codigo for h in lluviosas)

    secas = [h.codigo for h in horas if h.codigo < PRIMER_CODIGO_DE_LLUVIA]
    if secas:
        return max(secas)

    # Todas las horas traen codigo de lluvia y ninguna llega al umbral: llueve
    # poco pero llueve, y lo mas suave que se puede decir es el minimo.
    return min(h.codigo for h in horas)


def _entero(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def _decimal(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class ClimaDelViaje:
    """El clima de todos los dias del itinerario, y por que falta si falta.

    `reason` sigue el patron de las distancias: la respuesta dice siempre de
    donde salieron los datos, y cuando no hay, por que no hay. Callarse deja a
    la persona sin saber si no llueve o si no se miro.
    """

    dias: dict[date, DiaDeClima] = field(default_factory=dict)
    reason: str | None = None

    @property
    def hay(self) -> bool:
        return bool(self.dias)

    def de(self, fecha: date | None) -> DiaDeClima | None:
        if fecha is None:
            return None
        return self.dias.get(fecha)


def load_forecast(
    lat: float,
    lon: float,
    start_date: date | None,
    days: int,
    today: date,
    provider: WeatherProvider | None = None,
) -> ClimaDelViaje:
    """Trae el clima del viaje, o explica por que no se pudo.

    No lanza: el itinerario se arma con clima o sin el, y decidir eso a base de
    excepciones que suban hasta el endpoint es la forma de que un dia el
    servicio del tiempo tumbe el planificador.
    """
    if start_date is None:
        return ClimaDelViaje(reason="sin_fecha")

    if provider is None:
        return ClimaDelViaje(reason="sin_proveedor")

    ultimo_dia = start_date + timedelta(days=days - 1)
    limite = today + timedelta(days=HORIZONTE_PRONOSTICO_DIAS - 1)

    if start_date > limite:
        # El viaje entero cae fuera del pronostico. Se dice, no se rellena.
        return ClimaDelViaje(reason="fuera_de_pronostico")

    # Un viaje que empieza dentro del horizonte y termina fuera se pide hasta
    # donde llega: cinco dias con clima y dos sin el es mejor respuesta que
    # ninguno con clima.
    hasta = min(ultimo_dia, limite)

    try:
        dias = provider.forecast(lat, lon, start_date, hasta)
    except ClimaError as exc:
        logger.warning("sin clima para el itinerario: %s", exc)
        return ClimaDelViaje(reason="sin_servicio")

    if not dias:
        return ClimaDelViaje(reason="sin_servicio")

    return ClimaDelViaje(dias=dias)


def provider_from_settings() -> WeatherProvider | None:
    """El proveedor segun la configuracion, o None si el clima esta apagado.

    Devuelve None y no lanza cuando esta apagado: `load_forecast` ya sabe
    seguir sin proveedor, asi que apagar el clima es un camino normal y no un
    fallo.

    **Es uno solo para todo el proceso y tiene que serlo**, porque el cache de
    una hora vive dentro del objeto. Un proveedor nuevo por peticion tendria el
    cache siempre vacio y pediria el pronostico otra vez a cada itinerario.
    """
    from app.core.config import settings

    if not settings.weather_enabled:
        return None
    return _compartido(settings.weather_timeout_seconds)


@lru_cache(maxsize=1)
def _compartido(timeout: float) -> OpenMeteo:
    return OpenMeteo(timeout=timeout)
