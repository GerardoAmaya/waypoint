"""Tests de las distancias reales.

Ninguno toca la red. El cliente se sustituye por uno falso que registra lo que
se le pidio, que es la unica forma de comprobar cosas como "la segunda
consulta no llama a la API" sin gastar cupo en cada corrida de CI.
"""

import time as _time
import uuid

import pytest

from app.models import Category
from app.services import routing
from app.services.geo import DETOUR_FACTOR, EstimatedTravel, haversine_km
from app.services.itinerary import Constraints, build_days
from app.services.places import PlaceHit
from app.services.routing import (
    ORSAuthError,
    ORSClient,
    ORSError,
    ORSQuotaExhausted,
    Pacer,
    TravelMatrix,
    fetch_edges,
    load_travel_matrix,
)

SAN_SALVADOR = (13.6929, -89.2182)
SANTA_ANA = (13.9942, -89.5597)


def lugar(nombre, lat, lon, categoria=Category.attraction) -> PlaceHit:
    return PlaceHit(
        id=uuid.uuid4(),
        name=nombre,
        category=categoria.value,
        subcategory=None,
        lat=lat,
        lon=lon,
        quality_score=0.5,
    )


class RespuestaFalsa:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class ClienteFalso:
    """Cliente de ORS que devuelve distancias inventadas y anota las llamadas."""

    def __init__(self, km_por_par=None, nulos=(), falla_con=None):
        self.km_por_par = km_por_par or {}
        self.nulos = set(nulos)
        self.falla_con = falla_con
        self.llamadas = []
        self.request_count = 0

    def matrix(self, coords, profile, sources=None, destinations=None):
        self.llamadas.append((list(coords), profile, sources, destinations))
        self.request_count += 1

        if self.falla_con is not None:
            raise self.falla_con

        origenes = coords if sources is None else [coords[i] for i in sources]
        destinos = coords if destinations is None else [coords[i] for i in destinations]

        distancias, duraciones = [], []
        for o in origenes:
            fila_km, fila_min = [], []
            for d in destinos:
                if (o, d) in self.nulos:
                    fila_km.append(None)
                    fila_min.append(None)
                else:
                    por_defecto = haversine_km(o[0], o[1], d[0], d[1]) * 1.6
                    km = self.km_por_par.get((o, d), por_defecto)
                    fila_km.append(km)
                    # El cliente real devuelve minutos ya convertidos.
                    fila_min.append(km / 40.0 * 60)
            distancias.append(fila_km)
            duraciones.append(fila_min)
        return distancias, duraciones


# --------------------------------------------------------------------------
# Control de ritmo
# --------------------------------------------------------------------------


class TestPacer:
    def test_espacia_las_llamadas_seguidas(self):
        pacer = Pacer(0.05)
        inicio = _time.monotonic()
        for _ in range(3):
            pacer.wait()
        # La primera no espera; las otras dos si.
        assert _time.monotonic() - inicio >= 0.09

    def test_un_intervalo_de_cero_no_espera(self):
        pacer = Pacer(0)
        inicio = _time.monotonic()
        for _ in range(5):
            pacer.wait()
        assert _time.monotonic() - inicio < 0.05


# --------------------------------------------------------------------------
# Cliente de OpenRouteService
# --------------------------------------------------------------------------


class TestORSClient:
    def test_invierte_las_coordenadas_a_lon_lat(self, monkeypatch):
        """ORS espera lon,lat y el resto del proyecto usa lat,lon.

        Equivocarse aqui no da error: devuelve rutas plausibles en otro
        continente. Por eso se fija con un test y no con un comentario.
        """
        capturado = {}

        def post_falso(url, json, headers, timeout):
            capturado["body"] = json
            return RespuestaFalsa(200, {"distances": [[0, 1]], "durations": [[0, 60]]})

        monkeypatch.setattr(routing.httpx, "post", post_falso)

        cliente = ORSClient("llave", min_interval_seconds=0)
        cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")

        assert capturado["body"]["locations"] == [
            [-89.2182, 13.6929],
            [-89.5597, 13.9942],
        ]

    def test_convierte_segundos_a_minutos(self, monkeypatch):
        monkeypatch.setattr(
            routing.httpx,
            "post",
            lambda url, json, headers, timeout: RespuestaFalsa(
                200, {"distances": [[0]], "durations": [[5400]]}
            ),
        )
        cliente = ORSClient("llave", min_interval_seconds=0)
        _, duraciones = cliente.matrix([SAN_SALVADOR], "driving-car")
        assert duraciones[0][0] == pytest.approx(90.0)

    @pytest.mark.parametrize(
        "codigo,excepcion",
        [
            (401, ORSAuthError),
            (403, ORSQuotaExhausted),
            (429, ORSError),
            (500, ORSError),
        ],
    )
    def test_traduce_los_codigos_de_error(self, monkeypatch, codigo, excepcion):
        monkeypatch.setattr(
            routing.httpx,
            "post",
            lambda url, json, headers, timeout: RespuestaFalsa(codigo, text="fallo"),
        )
        cliente = ORSClient("llave", min_interval_seconds=0)
        with pytest.raises(excepcion):
            cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")

    def test_el_cupo_agotado_no_se_confunde_con_credenciales(self, monkeypatch):
        """403 es cupo, no llave invalida. Es la trampa de esta API."""
        monkeypatch.setattr(
            routing.httpx,
            "post",
            lambda url, json, headers, timeout: RespuestaFalsa(403, text="quota"),
        )
        cliente = ORSClient("llave", min_interval_seconds=0)
        with pytest.raises(ORSQuotaExhausted):
            cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")
        assert not issubclass(ORSQuotaExhausted, ORSAuthError)


# --------------------------------------------------------------------------
# Armado de la matriz
# --------------------------------------------------------------------------


class TestFetchEdges:
    def test_pide_todos_los_pares_en_una_sola_llamada(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(5)]
        cliente = ClienteFalso()
        aristas = fetch_edges(lugares, "driving", cliente)

        assert cliente.request_count == 1
        assert len(aristas) == 5 * 4

    def test_no_guarda_la_diagonal(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(3)]
        aristas = fetch_edges(lugares, "driving", ClienteFalso())
        assert all(o != d for o, d in aristas)

    def test_trocea_cuando_hay_mas_lugares_que_el_limite(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(4)]
        cliente = ClienteFalso()
        aristas = fetch_edges(lugares, "driving", cliente, chunk_size=2)

        # Dos bloques de origen por dos de destino.
        assert cliente.request_count == 4
        assert len(aristas) == 4 * 3

    def test_una_celda_nula_no_invalida_el_resto(self):
        """Una cascada lejos de carretera no puede tumbar los otros pares."""
        a = lugar("Cascada", 13.70, -89.20)
        b = lugar("Museo", 13.71, -89.21)
        c = lugar("Parque", 13.72, -89.22)
        cliente = ClienteFalso(nulos=[((a.lat, a.lon), (b.lat, b.lon))])

        aristas = fetch_edges([a, b, c], "driving", cliente)

        assert (a.id, b.id) not in aristas
        assert (b.id, a.id) in aristas
        assert (a.id, c.id) in aristas

    def test_el_cupo_agotado_corta_y_devuelve_lo_que_haya(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(4)]
        cliente = ClienteFalso(falla_con=ORSQuotaExhausted("sin cupo"))

        aristas = fetch_edges(lugares, "driving", cliente, chunk_size=2)

        # Se corta en el primer bloque en vez de insistir contra el limite.
        assert cliente.request_count == 1
        assert aristas == {}

    def test_un_bloque_fallido_no_detiene_los_demas(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(4)]

        class ClienteIntermitente(ClienteFalso):
            def matrix(self, coords, profile, sources=None, destinations=None):
                if self.request_count == 0:
                    self.request_count += 1
                    raise ORSError("bloque malo")
                return super().matrix(coords, profile, sources, destinations)

        cliente = ClienteIntermitente()
        aristas = fetch_edges(lugares, "driving", cliente, chunk_size=2)

        assert cliente.request_count == 4
        assert aristas, "los bloques buenos tienen que haber entrado"


# --------------------------------------------------------------------------
# La matriz como proveedor
# --------------------------------------------------------------------------


class TestTravelMatrix:
    def test_sin_cliente_ni_base_todo_queda_estimado(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(4)]
        matriz = load_travel_matrix(lugares, "driving")

        assert matriz.stats.fetched == 0
        assert matriz.stats.estimated == 4 * 3
        assert matriz.stats.real_ratio == 0.0

    def test_con_cliente_las_medidas_son_reales(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(4)]
        matriz = load_travel_matrix(lugares, "driving", client=ClienteFalso())

        assert matriz.stats.fetched == 4 * 3
        assert matriz.stats.estimated == 0
        assert matriz.stats.real_ratio == 1.0

    def test_un_par_desconocido_cae_a_la_estimacion(self):
        a = lugar("A", *SAN_SALVADOR)
        b = lugar("B", *SANTA_ANA)
        matriz = TravelMatrix(fallback=EstimatedTravel("driving"))

        km, minutos = matriz.between(a, b)
        # El estimador redondea a tres decimales, como el resto del proyecto.
        esperado = round(haversine_km(*SAN_SALVADOR, *SANTA_ANA) * DETOUR_FACTOR, 3)

        assert km == pytest.approx(esperado)
        assert minutos > 0

    def test_la_medida_real_gana_sobre_la_estimada(self):
        a = lugar("A", *SAN_SALVADOR)
        b = lugar("B", *SANTA_ANA)
        matriz = TravelMatrix(edges={(a.id, b.id): (123.4, 99)})

        assert matriz.between(a, b) == (123.4, 99)

    def test_no_asume_simetria(self):
        """Ir no cuesta lo mismo que volver, y la matriz tiene que permitirlo."""
        a = lugar("A", *SAN_SALVADOR)
        b = lugar("B", *SANTA_ANA)
        matriz = TravelMatrix(edges={(a.id, b.id): (60.0, 80), (b.id, a.id): (72.0, 95)})

        assert matriz.between(a, b) != matriz.between(b, a)

    def test_con_un_solo_lugar_no_llama_a_la_api(self):
        cliente = ClienteFalso()
        matriz = load_travel_matrix([lugar("Solo", *SAN_SALVADOR)], "driving", client=cliente)
        assert cliente.request_count == 0
        assert matriz.stats.total == 0


# --------------------------------------------------------------------------
# La cache
# --------------------------------------------------------------------------


class BaseFalsa:
    """Base de datos minima: devuelve filas fijas y anota lo que se guardo."""

    def __init__(self, filas=()):
        self.filas = list(filas)
        self.guardado = []

    def execute(self, sentencia):
        self.guardado.append(sentencia)
        resultado = type("R", (), {"all": lambda _self: self.filas})()
        return resultado

    def commit(self):
        pass


class Fila:
    def __init__(self, origin_id, destination_id, distance_km, duration_minutes):
        self.origin_id = origin_id
        self.destination_id = destination_id
        self.distance_km = distance_km
        self.duration_minutes = duration_minutes


class TestCache:
    def test_lo_que_esta_en_cache_no_se_le_pide_a_ors(self):
        """La verificacion de la fase 4: la segunda consulta no llama a la API."""
        a = lugar("A", 13.70, -89.20)
        b = lugar("B", 13.71, -89.21)
        db = BaseFalsa(filas=[Fila(a.id, b.id, 5.5, 9), Fila(b.id, a.id, 5.7, 10)])
        cliente = ClienteFalso()

        matriz = load_travel_matrix([a, b], "driving", db=db, client=cliente)

        assert cliente.request_count == 0
        assert matriz.stats.cached == 2
        assert matriz.stats.fetched == 0
        assert matriz.between(a, b) == (5.5, 9)

    def test_con_la_cache_a_medias_se_piden_los_que_faltan(self):
        a = lugar("A", 13.70, -89.20)
        b = lugar("B", 13.71, -89.21)
        db = BaseFalsa(filas=[Fila(a.id, b.id, 5.5, 9)])
        cliente = ClienteFalso()

        matriz = load_travel_matrix([a, b], "driving", db=db, client=cliente)

        assert cliente.request_count == 1
        assert matriz.stats.cached == 1
        assert matriz.stats.fetched == 1
        # El valor cacheado no se pisa con el de ORS.
        assert matriz.between(a, b) == (5.5, 9)


# --------------------------------------------------------------------------
# Integracion con el motor
# --------------------------------------------------------------------------


class TestMotorConRutasReales:
    def test_el_motor_acepta_la_matriz_sin_cambios(self):
        candidatos = [lugar(f"L{i}", 13.70 + i * 0.02, -89.22) for i in range(6)]
        matriz = load_travel_matrix(candidatos, "driving", client=ClienteFalso())
        restricciones = Constraints(days=2, center_lat=13.70, center_lon=-89.22)

        dias = build_days(candidatos, restricciones, matriz)

        assert dias
        assert all(dia for dia in dias)

    def test_una_carretera_larga_cambia_el_reparto(self):
        """Dos lugares cercanos en el mapa pero lejos por carretera se separan.

        Es la razon de ser de la fase 4: con la linea recta estos dos caen en
        el mismo dia, y con la distancia real no caben juntos.
        """
        a = lugar("Origen", 13.700, -89.220)
        b = lugar("Al otro lado del cerro", 13.705, -89.225)
        candidatos = [a, b]

        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=5
        )

        con_estimacion = build_days(candidatos, restricciones, EstimatedTravel("driving"))
        assert len(con_estimacion[0]) == 2, "en linea recta caben juntos"

        lejos = TravelMatrix(
            edges={(a.id, b.id): (40.0, 55), (b.id, a.id): (40.0, 55)},
            fallback=EstimatedTravel("driving"),
        )
        con_rutas_reales = build_days(candidatos, restricciones, lejos)
        assert len(con_rutas_reales[0]) == 1, "por carretera no caben"
