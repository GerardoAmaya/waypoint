"""Tests del limite por IP.

El reloj se sustituye para no tener que esperar un dia a que se libere una
ventana. Lo que se prueba es la mecanica de la ventana deslizante y la lectura
de la IP, que es donde se puede regalar el limite sin darse cuenta.
"""

import pytest

from app.core import ratelimit
from app.core.ratelimit import Limit, RateLimiter, client_ip


class Reloj:
    """Un reloj que avanza cuando uno se lo dice."""

    def __init__(self, inicio: float = 1_000.0):
        self.t = inicio

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> None:
        self.t += segundos


@pytest.fixture
def reloj(monkeypatch):
    falso = Reloj()
    monkeypatch.setattr(ratelimit.time, "monotonic", falso)
    return falso


class PeticionFalsa:
    def __init__(self, host="1.2.3.4", headers=None):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})() if host else None


class TestVentanaDeslizante:
    def test_deja_pasar_hasta_el_limite(self, reloj):
        limiter = RateLimiter([Limit(3, 60, "por minuto")])

        assert [limiter.check("ip") for _ in range(3)] == [None, None, None]
        assert limiter.check("ip") is not None

    def test_se_libera_de_a_uno_y_no_de_golpe(self, reloj):
        """Con un contador que se pone en cero, quien gasta su cuota a las
        10:59:59 la recupera entera un segundo despues."""
        limiter = RateLimiter([Limit(2, 60, "por minuto")])

        limiter.check("ip")
        reloj.avanzar(30)
        limiter.check("ip")
        assert limiter.check("ip") is not None

        # A los 61 segundos de la primera, se libera SOLO esa.
        reloj.avanzar(31)
        assert limiter.check("ip") is None
        assert limiter.check("ip") is not None

    def test_las_ips_se_cuentan_por_separado(self, reloj):
        limiter = RateLimiter([Limit(1, 60, "por minuto")])

        assert limiter.check("uno") is None
        assert limiter.check("dos") is None
        assert limiter.check("uno") is not None

    def test_las_dos_ventanas_valen_a_la_vez(self, reloj):
        """La de minutos frena la rafaga, la diaria frena el goteo."""
        limiter = RateLimiter([Limit(2, 60, "por minuto"), Limit(3, 86_400, "por día")])

        limiter.check("ip")
        limiter.check("ip")
        assert limiter.check("ip").name == "por minuto"

        reloj.avanzar(61)
        assert limiter.check("ip") is None
        # Tres en el dia: la diaria corta aunque la del minuto este libre.
        assert limiter.check("ip").name == "por día"

    def test_un_intento_rechazado_no_cuenta(self, reloj):
        """Contar los rechazos haria que insistir extienda el propio bloqueo."""
        limiter = RateLimiter([Limit(1, 60, "por minuto")])

        limiter.check("ip")
        for _ in range(10):
            limiter.check("ip")

        reloj.avanzar(61)
        assert limiter.check("ip") is None


class TestEsperaSugerida:
    def test_dice_cuanto_falta_para_el_proximo_lugar(self, reloj):
        limiter = RateLimiter([Limit(2, 60, "por minuto")])
        limiter.check("ip")
        reloj.avanzar(10)
        limiter.check("ip")

        limite = limiter.check("ip")
        espera = limiter.retry_after("ip", limite)

        # La primera fue hace 10 s, asi que se libera en unos 50.
        assert 48 <= espera <= 52

    def test_nunca_sugiere_cero(self, reloj):
        limiter = RateLimiter([Limit(1, 60, "por minuto")])
        assert limiter.retry_after("desconocida", Limit(1, 60, "x")) >= 1


class TestLimpieza:
    def test_las_ips_viejas_no_se_acumulan(self, reloj):
        """Sin limpieza el diccionario crece con cada visitante y nunca baja."""
        limiter = RateLimiter([Limit(5, 60, "por minuto")])

        for i in range(50):
            limiter.check(f"ip-{i}")
        assert len(limiter._hits) == 50

        reloj.avanzar(ratelimit.CLEANUP_EVERY_SECONDS + 61)
        limiter.check("nueva")

        assert len(limiter._hits) == 1


class TestLecturaDeLaIP:
    def test_sin_proxy_usa_la_conexion(self):
        peticion = PeticionFalsa(host="9.9.9.9", headers={"x-forwarded-for": "1.1.1.1"})
        assert client_ip(peticion, trust_proxy=False) == "9.9.9.9"

    def test_confiar_en_el_encabezado_sin_proxy_regala_el_limite(self):
        """Cualquiera manda un X-Forwarded-For distinto en cada peticion.

        Por eso la confianza es una opcion y viene apagada: detras de Railway
        el proxy lo reescribe y ahi si es fiable.
        """
        limiter = RateLimiter([Limit(1, 60, "por minuto")])

        for i in range(10):
            peticion = PeticionFalsa(host="9.9.9.9", headers={"x-forwarded-for": f"1.1.1.{i}"})
            assert limiter.check(client_ip(peticion, trust_proxy=True)) is None

    def test_detras_de_proxy_toma_el_primero_de_la_cadena(self):
        peticion = PeticionFalsa(
            host="10.0.0.1", headers={"x-forwarded-for": "1.1.1.1, 10.0.0.5"}
        )
        assert client_ip(peticion, trust_proxy=True) == "1.1.1.1"

    def test_sin_cliente_no_revienta(self):
        assert client_ip(PeticionFalsa(host=None), trust_proxy=False) == "desconocido"
