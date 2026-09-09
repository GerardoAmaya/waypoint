"""Limite de peticiones por IP.

La demo es publica y no tiene cuentas. Cada frase que alguien escriba gasta
tokens de Haiku y, si la zona esta fria, una peticion del cupo diario de
OpenRouteService. Sin un techo, una sola persona curioseando vacia las
cincuenta peticiones de rutas en un minuto, y el gasto de tokens no tiene
fondo.

**La cuenta vive en memoria.** El PLAN.md descarto Redis a proposito y meterlo
solo para esto seria infraestructura nueva para un problema que en el plan de
prueba de Railway no existe: hay una sola instancia. El precio es real y se
dice en vez de esconderse: la cuenta se pierde al reiniciar el proceso y no ve
lo que hizo otra instancia. Si el proyecto llega a escalar horizontalmente,
esto deja de servir y hay que moverlo a un almacen compartido.

Se cuentan dos ventanas a la vez. La de minutos frena la rafaga —alguien
apretando el boton— y la diaria frena el goteo constante, que es la que de
verdad vacia el cupo.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import HTTPException, Request

# Cada cuanto se recorren las IPs guardadas para tirar las que ya no cuentan.
# Sin esto el diccionario crece con cada visitante y nunca baja.
CLEANUP_EVERY_SECONDS = 300


@dataclass(frozen=True)
class Limit:
    """Cuantas peticiones caben en cuanto tiempo."""

    requests: int
    window_seconds: int
    name: str


class RateLimiter:
    """Ventanas deslizantes por IP.

    Deslizante y no un contador que se pone en cero cada minuto: con el segundo
    modelo, alguien que gasta su cuota a las 10:59:59 la recupera entera un
    segundo despues, y el limite deja de limitar justo en el momento en que
    haria falta.
    """

    def __init__(self, limits: list[Limit]) -> None:
        self.limits = limits
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._last_cleanup = time.monotonic()

    @property
    def _longest_window(self) -> int:
        return max((limit.window_seconds for limit in self.limits), default=0)

    def _cleanup(self, ahora: float) -> None:
        """Tira las IPs sin actividad dentro de la ventana mas larga."""
        if ahora - self._last_cleanup < CLEANUP_EVERY_SECONDS:
            return

        corte = ahora - self._longest_window
        self._hits = {
            ip: marcas for ip, marcas in self._hits.items() if marcas and marcas[-1] > corte
        }
        self._last_cleanup = ahora

    def check(self, ip: str) -> Limit | None:
        """Registra una peticion, o devuelve el limite que la rechaza.

        La marca se guarda solo si la peticion pasa: contar los intentos
        rechazados haria que quien insiste se castigue a si mismo extendiendo su
        propio bloqueo, sin que eso proteja nada.
        """
        ahora = time.monotonic()

        with self._lock:
            self._cleanup(ahora)
            marcas = self._hits.setdefault(ip, deque())

            corte = ahora - self._longest_window
            while marcas and marcas[0] <= corte:
                marcas.popleft()

            for limite in self.limits:
                desde = ahora - limite.window_seconds
                usadas = sum(1 for marca in marcas if marca > desde)
                if usadas >= limite.requests:
                    return limite

            marcas.append(ahora)
            return None

    def retry_after(self, ip: str, limite: Limit) -> int:
        """Segundos hasta que se libere un lugar en esa ventana."""
        with self._lock:
            marcas = self._hits.get(ip)
            if not marcas:
                return 1

            ahora = time.monotonic()
            dentro = [m for m in marcas if m > ahora - limite.window_seconds]
            if len(dentro) < limite.requests:
                return 1

            # La mas vieja de las que cuentan es la primera en salir.
            libera = dentro[-limite.requests] + limite.window_seconds
            return max(1, int(libera - ahora) + 1)


def client_ip(request: Request, trust_proxy: bool) -> str:
    """De quien viene la peticion.

    **X-Forwarded-For solo se lee detras de un proxy.** El encabezado lo pone
    quien quiera: en local, cualquiera se salta el limite mandando uno distinto
    en cada peticion. Detras de Railway el proxy lo reescribe y ahi si es
    fiable, por eso la confianza es una opcion de configuracion y viene apagada.
    """
    if trust_proxy:
        reenviado = request.headers.get("x-forwarded-for")
        if reenviado:
            return reenviado.split(",")[0].strip()

    return request.client.host if request.client else "desconocido"


def limiter_dependency(limiter: RateLimiter, trust_proxy: bool):
    """Dependencia de FastAPI que aplica el limite antes de entrar al endpoint."""

    def comprobar(request: Request) -> None:
        ip = client_ip(request, trust_proxy)
        excedido = limiter.check(ip)
        if excedido is None:
            return

        espera = limiter.retry_after(ip, excedido)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Demasiadas peticiones. El límite son {excedido.requests} "
                f"{excedido.name}. Probá de nuevo en {espera} segundos."
            ),
            headers={"Retry-After": str(espera)},
        )

    return comprobar
