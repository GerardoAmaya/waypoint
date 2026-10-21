"""Tests del cliente de OSRM propio.

Nada sale a la red: se sustituye httpx.get y se comprueba que URL se arma y
como se lee la respuesta. Lo que importa aqui son las dos cosas que no dan
error cuando se hacen mal —el orden lat/lon y las unidades— y que un punto sin
calle cerca no tumbe el dia entero.
"""

import pytest

from app.services import osrm
from app.services.osrm import OSRMClient, SinLimite
from app.services.routing import RutaError

URLS = {"car": "http://osrm-car:5000", "foot": "http://osrm-foot:5000"}

SUCHITOTO = (13.9356, -89.0272)
SANTA_ANA = (13.9942, -89.5597)


class RespuestaFalsa:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    def json(self):
        if isinstance(self._cuerpo, Exception):
            raise self._cuerpo
        return self._cuerpo


@pytest.fixture
def espia(monkeypatch):
    """Sustituye httpx.get y guarda la ultima llamada."""
    llamadas = []

    def falso_get(url, params=None, timeout=None):
        llamadas.append({"url": url, "params": params or {}, "timeout": timeout})
        return RespuestaFalsa(falso_get.respuesta)

    falso_get.respuesta = {"code": "Ok"}
    falso_get.llamadas = llamadas
    monkeypatch.setattr(osrm.httpx, "get", falso_get)
    return falso_get


# --- la URL ----------------------------------------------------------------


def test_las_coordenadas_van_lon_lat_y_no_al_reves(espia):
    """El error mas comun contra estas APIs, y no da fallo.

    Invertidas, El Salvador cae en el oceano Indico y OSRM contesta tan
    tranquilo. Por eso se fija aqui y no se deja a la vista.
    """
    espia.respuesta = {"code": "Ok", "distances": [[0]], "durations": [[0]]}
    OSRMClient(URLS).matrix([SUCHITOTO], "driving-car")

    assert "-89.0272,13.9356" in espia.llamadas[0]["url"]


def test_cada_perfil_llama_a_su_propio_servicio(espia):
    """osrm-routed sirve un solo perfil: el perfil elige el puerto."""
    espia.respuesta = {"code": "Ok", "distances": [[0]], "durations": [[0]]}
    cliente = OSRMClient(URLS)

    cliente.matrix([SUCHITOTO], "driving-car")
    cliente.matrix([SUCHITOTO], "foot-walking")

    assert espia.llamadas[0]["url"].startswith("http://osrm-car:5000/")
    assert espia.llamadas[1]["url"].startswith("http://osrm-foot:5000/")


def test_un_perfil_sin_servicio_no_tumba_a_los_demas(espia):
    """Tener el de carro y no el de a pie es una instalacion a medias valida."""
    cliente = OSRMClient({"car": URLS["car"]})

    with pytest.raises(RutaError):
        cliente.matrix([SUCHITOTO], "foot-walking")
    assert espia.llamadas == []


def test_el_trazo_pide_el_radio_de_enganche_de_cada_parada(espia):
    """Sin radio, un cerro sin calle a 350 metros deja el dia sin trazo."""
    espia.respuesta = {"code": "Ok", "routes": [{"geometry": {"coordinates": []}}]}
    OSRMClient(URLS).directions([SUCHITOTO, SANTA_ANA], "driving-car")

    radios = espia.llamadas[0]["params"]["radiuses"].split(";")
    assert radios == [str(osrm.RADIO_DE_ENGANCHE_M)] * 2


# --- las unidades ----------------------------------------------------------


def test_la_matriz_devuelve_kilometros_y_minutos(espia):
    """OSRM da metros y segundos; el motor trabaja en km y minutos."""
    espia.respuesta = {
        "code": "Ok",
        "distances": [[0, 58_000.0]],
        "durations": [[0, 3_600.0]],
    }
    distancias, duraciones = OSRMClient(URLS).matrix([SUCHITOTO, SANTA_ANA], "driving-car")

    assert distancias[0][1] == pytest.approx(58.0)
    assert duraciones[0][1] == pytest.approx(60.0)


def test_una_celda_nula_sobrevive_a_la_conversion(espia):
    """Un nulo es un punto que no engancho, y se trata por celda."""
    espia.respuesta = {"code": "Ok", "distances": [[0, None]], "durations": [[0, None]]}
    distancias, duraciones = OSRMClient(URLS).matrix([SUCHITOTO, SANTA_ANA], "driving-car")

    assert distancias[0][1] is None
    assert duraciones[0][1] is None


def test_el_trazo_vuelve_en_lat_lon(espia):
    espia.respuesta = {
        "code": "Ok",
        "routes": [{"geometry": {"coordinates": [[-89.0272, 13.9356]]}}],
    }
    trazo = OSRMClient(URLS).directions([SUCHITOTO, SANTA_ANA], "driving-car")

    assert trazo == [(13.9356, -89.0272)]


def test_un_trazo_de_un_solo_punto_no_llama(espia):
    assert OSRMClient(URLS).directions([SUCHITOTO], "driving-car") == []
    assert espia.llamadas == []


# --- los fallos ------------------------------------------------------------


@pytest.mark.parametrize("codigo", ["NoRoute", "NoSegment", "TooBig", "InvalidQuery"])
def test_un_codigo_que_no_sea_ok_es_un_fallo_de_ruta(espia, codigo):
    """OSRM pone el codigo en el cuerpo y contesta 400 por cosas normales.

    "NoSegment" es un punto lejos de toda calle —cerros, cascadas— y aca eso
    pasa a diario. Tiene que llegar como RutaError para que el motor lo estime,
    no como una excepcion cualquiera que rompa el itinerario.
    """
    espia.respuesta = {"code": codigo, "message": "lo que sea"}

    with pytest.raises(RutaError):
        OSRMClient(URLS).matrix([SUCHITOTO, SANTA_ANA], "driving-car")


def test_una_respuesta_que_no_es_json_es_un_fallo_de_ruta(espia):
    espia.respuesta = ValueError("esto no es json")

    with pytest.raises(RutaError):
        OSRMClient(URLS).matrix([SUCHITOTO, SANTA_ANA], "driving-car")


def test_si_el_servicio_no_contesta_es_un_fallo_de_ruta(monkeypatch):
    import httpx

    def se_cae(*args, **kwargs):
        raise httpx.ConnectError("nadie escucha en ese puerto")

    monkeypatch.setattr(osrm.httpx, "get", se_cae)

    with pytest.raises(RutaError):
        OSRMClient(URLS).matrix([SUCHITOTO, SANTA_ANA], "driving-car")


def test_una_ruta_sin_rutas_devuelve_vacio_en_vez_de_reventar(espia):
    espia.respuesta = {"code": "Ok", "routes": []}
    assert OSRMClient(URLS).directions([SUCHITOTO, SANTA_ANA], "driving-car") == []


# --- el cupo que no hay ----------------------------------------------------


def test_un_servidor_propio_no_declara_cupo():
    """None es lo que ya significa "no hay numero que mostrar" en ORS.

    Devolver un entero inventado pondria un techo en pantalla que no existe.
    """
    cliente = OSRMClient(URLS)

    assert cliente.matrix_quota.remaining is None
    assert cliente.directions_quota.remaining is None


def test_el_cupo_inexistente_nunca_frena_una_peticion():
    cupo = SinLimite()
    assert all(cupo.try_spend() for _ in range(1000))


def test_se_cuentan_las_peticiones_hechas(espia):
    """El motor mide el costo de un itinerario por la diferencia del contador."""
    espia.respuesta = {"code": "Ok", "distances": [[0]], "durations": [[0]]}
    cliente = OSRMClient(URLS)

    antes = cliente.request_count
    cliente.matrix([SUCHITOTO], "driving-car")
    cliente.matrix([SUCHITOTO], "driving-car")

    assert cliente.request_count - antes == 2
