"""Pruebas del estado del mar.

Lo que decide si esto es un dato o un adorno es que **solo salga donde hay
mar**, y eso no lo puede decidir la API: su rejilla se engancha a la celda con
agua mas cercana y le da 0.92 m de oleaje a Concepcion de Ataco, que esta en
la montaña a treinta kilometros de la costa.
"""

from datetime import date, timedelta

import pytest

from app.services.mar import (
    COSTERO_KM,
    DiaDeMar,
    MarDelViaje,
    MarError,
    _parsear,
    es_costero,
    km_a_la_costa,
    load_marine,
)

HOY = date(2026, 11, 20)

# Donde cae cada uno, comprobado contra el contorno por scripts/trazar_costa.
COSTA = {
    "El Cuco": (13.1667, -88.1167),
    "El Tunco": (13.4936, -89.3819),
    "El Zonte": (13.4936, -89.4400),
    "Costa del Sol": (13.3167, -88.9167),
    "La Libertad": (13.4883, -89.3222),
}
TIERRA = {
    "Santa Tecla": (13.6731, -89.2797),
    "San Salvador": (13.6929, -89.2182),
    "Ataco": (13.8697, -89.8467),
    "Santa Ana": (13.9942, -89.5597),
    "Suchitoto": (13.9356, -89.0272),
}


class ProveedorFalso:
    """Dicta la marejada en vez de pedirla por red."""

    def __init__(self, dias=None, falla=False):
        self.dias = dias or {}
        self.falla = falla
        self.llamadas = 0

    def marine(self, lat, lon, desde, hasta):
        self.llamadas += 1
        if self.falla:
            raise MarError("se cayó")
        return self.dias


def mar(fecha=HOY, **extra):
    base = {"ola_m": 1.16, "periodo_s": 13.4, "direccion_grados": 211, "agua_c": 31.0}
    return {fecha: DiaDeMar(fecha=fecha, **{**base, **extra})}


class TestQueCuentaComoCosta:
    def test_las_playas_estan_en_la_costa(self):
        for nombre, (lat, lon) in COSTA.items():
            assert es_costero(lat, lon), f"{nombre} a {km_a_la_costa(lat, lon):.1f} km"

    def test_tierra_adentro_no(self):
        """**Ataco es el caso que obligó a trazar la costa a mano**: la API
        marina le devuelve 0.92 m de oleaje porque engancha su rejilla a la
        celda con agua más cercana."""
        for nombre, (lat, lon) in TIERRA.items():
            assert not es_costero(lat, lon), f"{nombre} a {km_a_la_costa(lat, lon):.1f} km"

    def test_el_corte_cae_en_un_hueco_ancho(self):
        """No hay nada entre 7 y 26 km, así que el umbral no está peleado."""
        mas_lejos = max(km_a_la_costa(*c) for c in COSTA.values())
        mas_cerca = min(km_a_la_costa(*c) for c in TIERRA.values())

        assert mas_lejos < COSTERO_KM < mas_cerca


class TestNoPreguntaSiNoHaceFalta:
    def test_tierra_adentro_no_gasta_una_peticion(self):
        """Pedirle oleaje a Suchitoto es gastar una llamada para recibir
        nulos, y a veces para recibir algo peor que nulos."""
        proveedor = ProveedorFalso(mar())

        resultado = load_marine(13.9356, -89.0272, HOY, 2, HOY, proveedor)

        assert resultado.reason == "tierra_adentro"
        assert proveedor.llamadas == 0

    def test_sin_fecha_tampoco(self):
        proveedor = ProveedorFalso(mar())

        assert load_marine(13.4936, -89.3819, None, 2, HOY, proveedor).reason == "sin_fecha"
        assert proveedor.llamadas == 0

    def test_mas_alla_del_horizonte_se_dice(self):
        """Siete días es lo que el servicio marino alcanza; inventar el octavo
        sería peor que no tenerlo."""
        lejos = HOY + timedelta(days=30)

        resultado = load_marine(13.4936, -89.3819, lejos, 2, HOY, ProveedorFalso(mar()))

        assert resultado.reason == "fuera_de_pronostico"


class TestNuncaFalla:
    def test_el_servicio_caido_no_tumba_el_itinerario(self):
        """La misma regla que el clima y que las distancias: se degrada y se
        dice, no se lanza."""
        resultado = load_marine(13.4936, -89.3819, HOY, 2, HOY, ProveedorFalso(falla=True))

        assert resultado.reason == "sin_servicio"
        assert not resultado.hay

    def test_sin_proveedor_se_arma_igual(self):
        assert load_marine(13.4936, -89.3819, HOY, 2, HOY, None).reason == "sin_proveedor"

    def test_con_mar_lo_devuelve(self):
        resultado = load_marine(13.4936, -89.3819, HOY, 2, HOY, ProveedorFalso(mar()))

        assert resultado.hay
        assert resultado.de(HOY).periodo_s == pytest.approx(13.4)
        assert resultado.de(HOY + timedelta(days=5)) is None


class TestElParseo:
    def test_un_dia_sin_periodo_no_es_un_dia(self):
        """**La mitad del dato no permite decir nada.** Sin periodo no se
        puede distinguir la marejada de fondo del mar de viento, que es lo
        único que valía la pena decir."""
        cuerpo = {
            "daily": {
                "time": ["2026-11-20", "2026-11-21"],
                "wave_height_max": [1.16, 1.2],
                "wave_period_max": [13.4, None],
                "wave_direction_dominant": [211, 210],
            }
        }

        assert list(_parsear(cuerpo)) == [date(2026, 11, 20)]

    def test_tierra_adentro_la_api_devuelve_nulos(self):
        cuerpo = {
            "daily": {
                "time": ["2026-11-20"],
                "wave_height_max": [None],
                "wave_period_max": [None],
                "wave_direction_dominant": [None],
            }
        }

        assert _parsear(cuerpo) == {}

    def test_el_agua_sale_de_mediodia(self):
        """Que es cuando la gente se mete."""
        cuerpo = {
            "daily": {
                "time": ["2026-11-20"],
                "wave_height_max": [1.1],
                "wave_period_max": [13.0],
                "wave_direction_dominant": [211],
            },
            "hourly": {
                "time": ["2026-11-20T06:00", "2026-11-20T12:00"],
                "sea_surface_temperature": [29.0, 31.0],
            },
        }

        assert _parsear(cuerpo)[date(2026, 11, 20)].agua_c == pytest.approx(31.0)

    def test_sin_temperatura_no_la_inventa(self):
        cuerpo = {
            "daily": {
                "time": ["2026-11-20"],
                "wave_height_max": [1.1],
                "wave_period_max": [13.0],
                "wave_direction_dominant": [211],
            }
        }

        assert _parsear(cuerpo)[date(2026, 11, 20)].agua_c is None


class TestElViaje:
    def test_sin_dias_no_hay_mar(self):
        assert not MarDelViaje().hay
        assert MarDelViaje().de(HOY) is None
