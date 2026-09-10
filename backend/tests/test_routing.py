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
from app.services.geo import (
    ARRIVAL_OVERHEAD_MINUTES,
    DETOUR_FACTOR,
    EstimatedTravel,
    haversine_km,
)
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
    load_route_geometry,
    load_travel_matrix,
    split_by_stops,
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
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

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
        # El cliente real lleva un cupo por endpoint, y load_travel_matrix lo
        # consulta para distinguir "sin cupo" de "sin carretera". Sin sincronizar
        # con el servidor, `remaining` es None: cupo desconocido.
        self.matrix_quota = routing.DailyQuota(45)

    def matrix(self, coords, profile, sources=None, destinations=None):
        self.llamadas.append((list(coords), profile, sources, destinations))

        # El cliente real comprueba el presupuesto ANTES de contar la peticion:
        # quedarse sin cupo no gasta una llamada. El falso lo contaba igual, y
        # eso hacia que "sin cupo" se viera como "hubo peticion y no sirvio".
        if isinstance(self.falla_con, routing.ORSBudgetExhausted | routing.ORSQuotaExhausted):
            raise self.falla_con

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

        # Se corta en el primer bloque en vez de insistir contra el limite. El
        # contador queda en cero porque quedarse sin cupo no gasta peticion:
        # el presupuesto se comprueba antes de salir a la red.
        assert cliente.request_count == 0
        assert len(cliente.llamadas) == 1
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

        # La cache guarda el tiempo de conduccion puro que midio ORS; between()
        # devuelve lo que tarda llegar de verdad, o sea con la friccion de
        # estacionar y entrar sumada. Son dos numeros distintos a proposito.
        km, minutos = matriz.between(a, b)
        assert km == 123.4
        assert minutos == 99 + ARRIVAL_OVERHEAD_MINUTES["driving"]

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
        km, minutos = matriz.between(a, b)
        assert km == 5.5
        assert minutos == 9 + ARRIVAL_OVERHEAD_MINUTES["driving"]

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
        km, minutos = matriz.between(a, b)
        assert km == 5.5
        assert minutos == 9 + ARRIVAL_OVERHEAD_MINUTES["driving"]


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


# --------------------------------------------------------------------------
# Presupuesto diario
# --------------------------------------------------------------------------


class TestDailyQuota:
    def test_deja_gastar_hasta_el_techo(self):
        cupo = routing.DailyQuota(3)
        assert [cupo.try_spend() for _ in range(4)] == [True, True, True, False]
        assert cupo.own_remaining == 0

    def test_el_encabezado_del_servidor_manda_sobre_la_cuenta_propia(self):
        """Tras un reinicio nuestra cuenta esta en cero y la de ORS no."""
        cupo = routing.DailyQuota(45)
        assert cupo.own_remaining == 45

        cupo.sync_with_server(2)
        assert cupo.remaining == 2

    def test_no_gasta_si_el_servidor_dice_que_no_queda(self):
        cupo = routing.DailyQuota(45)
        cupo.sync_with_server(0)
        assert cupo.try_spend() is False

    def test_un_encabezado_ausente_no_rompe_la_cuenta(self):
        cupo = routing.DailyQuota(5)
        cupo.sync_with_server(None)
        assert cupo.own_remaining == 5
        assert cupo.remaining is None

    def test_la_ventana_es_deslizante(self, monkeypatch):
        """A las 24 horas de una llamada, esa llamada deja de contar."""
        cupo = routing.DailyQuota(2)
        reloj = {"t": 1000.0}
        monkeypatch.setattr(routing._time, "monotonic", lambda: reloj["t"])

        assert cupo.try_spend() and cupo.try_spend()
        assert cupo.try_spend() is False

        reloj["t"] += routing.DailyQuota.WINDOW_SECONDS + 1
        assert cupo.try_spend() is True


class TestClienteConPresupuesto:
    def test_el_cliente_deja_de_llamar_al_agotar_el_presupuesto(self, monkeypatch):
        llamadas = {"n": 0}

        def post_falso(url, json, headers, timeout):
            llamadas["n"] += 1
            return RespuestaFalsa(200, {"distances": [[0, 1]], "durations": [[0, 60]]})

        monkeypatch.setattr(routing.httpx, "post", post_falso)
        cliente = ORSClient("llave", min_interval_seconds=0, daily_budget=2)

        cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")
        cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")
        with pytest.raises(routing.ORSBudgetExhausted):
            cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")

        assert llamadas["n"] == 2, "la tercera no debio salir a la red"

    def test_manda_el_radio_de_enganche_con_cada_parada(self, monkeypatch):
        """Sin el, ORS usa 350 m y un volcan tumba el trazo del dia entero.

        Medido en el arnes antes de mandarlo: 34 de 61 dias y 127 de 236
        tramos se quedaban rectos, incluidos los que van entre museos del
        centro. Con el radio puesto, 34 de 36 en los dias mas duros.
        """
        cuerpos = []

        def post_falso(url, json, headers, timeout):
            cuerpos.append(json)
            return RespuestaFalsa(
                200,
                {"features": [{"geometry": {"coordinates": [[-89.2, 13.7], [-89.5, 14.0]]}}]},
            )

        monkeypatch.setattr(routing.httpx, "post", post_falso)
        cliente = ORSClient("llave", min_interval_seconds=0)

        cliente.directions([SAN_SALVADOR, SANTA_ANA, (13.8, -89.4)], "driving-car")

        assert cuerpos[0]["radiuses"] == [routing.SNAP_RADIUS_M] * 3, (
            "uno por parada: ORS espera la lista del mismo largo"
        )

    def test_la_matriz_no_se_come_el_cupo_del_trazo(self, monkeypatch):
        """Los dos endpoints tienen cupos separados y ORS los cuenta aparte.

        Con un contador compartido, la matriz —que corre primero en la misma
        peticion— se llevaba el presupuesto y la geometria no se llegaba a
        pedir: itinerarios con distancias reales y lineas rectas, y route_legs
        sin una sola fila.
        """
        respuestas = {
            "matrix": RespuestaFalsa(200, {"distances": [[0, 1]], "durations": [[0, 60]]}),
            "directions": RespuestaFalsa(
                200,
                {"features": [{"geometry": {"coordinates": [[-89.2, 13.7], [-89.5, 14.0]]}}]},
            ),
        }

        def post_falso(url, json, headers, timeout):
            return respuestas["directions" if "directions" in url else "matrix"]

        monkeypatch.setattr(routing.httpx, "post", post_falso)
        cliente = ORSClient("llave", min_interval_seconds=0, daily_budget=1)

        cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")
        with pytest.raises(routing.ORSBudgetExhausted):
            cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")

        # El trazo tiene su propio cupo y no lo toco la matriz.
        trazo = cliente.directions([SAN_SALVADOR, SANTA_ANA], "driving-car")
        assert trazo, "la geometria tenia cupo propio y debio salir"

    def test_el_cupo_que_informa_un_endpoint_no_apaga_al_otro(self, monkeypatch):
        """La segunda cara del mismo error.

        sync_with_server guardaba el x-ratelimit-remaining de la ultima
        respuesta en un campo comun, asi que un "quedan 0" de la matriz
        apagaba direcciones, que tenia su cupo intacto.
        """
        respuesta = RespuestaFalsa(200, {"distances": [[0]], "durations": [[0]]})
        respuesta.headers = {"x-ratelimit-remaining": "0"}
        monkeypatch.setattr(
            routing.httpx, "post", lambda url, json, headers, timeout: respuesta
        )

        cliente = ORSClient("llave", min_interval_seconds=0, daily_budget=45)
        cliente.matrix([SAN_SALVADOR], "driving-car")

        assert cliente.matrix_quota.remaining == 0
        assert cliente.directions_quota.remaining is None, (
            "direcciones no informo nada todavia; heredar el 0 de la matriz la apagaba"
        )

    def test_lee_el_cupo_restante_del_encabezado(self, monkeypatch):
        respuesta = RespuestaFalsa(200, {"distances": [[0]], "durations": [[0]]})
        respuesta.headers = {"x-ratelimit-remaining": "7"}
        monkeypatch.setattr(
            routing.httpx, "post", lambda url, json, headers, timeout: respuesta
        )

        cliente = ORSClient("llave", min_interval_seconds=0, daily_budget=45)
        cliente.matrix([SAN_SALVADOR], "driving-car")

        assert cliente.matrix_quota.remaining == 7

    def test_el_presupuesto_agotado_degrada_a_estimacion(self):
        """Sin cupo el itinerario sale igual, con distancias aproximadas."""
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(3)]
        cliente = ClienteFalso(falla_con=routing.ORSBudgetExhausted("sin presupuesto"))

        matriz = load_travel_matrix(lugares, "driving", client=cliente)

        assert matriz.stats.fetched == 0
        assert matriz.stats.estimated == 3 * 2
        km, minutos = matriz.between(lugares[0], lugares[1])
        assert km > 0 and minutos > 0


class TestClienteCompartido:
    def test_es_el_mismo_en_todo_el_proceso(self, monkeypatch):
        """Un cliente por peticion dejaria el presupuesto de adorno.

        Pacer y DailyQuota viven dentro del cliente. Si cada itinerario
        construye el suyo, arranca con el presupuesto entero y sin memoria del
        ritmo, y los dos controles no controlan nada.
        """
        from app.core.config import settings

        routing.client_from_settings.cache_clear()
        monkeypatch.setattr(settings, "ors_api_key", "llave-de-prueba")

        primero = routing.client_from_settings()
        segundo = routing.client_from_settings()

        assert primero is segundo
        assert primero.quotas is segundo.quotas
        routing.client_from_settings.cache_clear()

    def test_sin_llave_no_hay_cliente(self, monkeypatch):
        from app.core.config import settings

        routing.client_from_settings.cache_clear()
        monkeypatch.setattr(settings, "ors_api_key", None)
        assert routing.client_from_settings() is None
        routing.client_from_settings.cache_clear()

    def test_el_presupuesto_persiste_entre_llamadas(self, monkeypatch):
        from app.core.config import settings

        routing.client_from_settings.cache_clear()
        monkeypatch.setattr(settings, "ors_api_key", "llave-de-prueba")
        monkeypatch.setattr(settings, "ors_daily_budget", 2)

        cliente = routing.client_from_settings()
        assert cliente.matrix_quota.try_spend() and cliente.matrix_quota.try_spend()
        # Otra "peticion HTTP" pide el cliente de nuevo y encuentra la cuenta.
        assert routing.client_from_settings().matrix_quota.try_spend() is False
        routing.client_from_settings.cache_clear()


class TestPlausibilidad:
    """Una ruta por carretera no puede medir menos que la linea recta.

    El caso real: tres paradas dentro del Parque El Imposible, todas lejos de
    camino, engancharon al mismo nodo de la red vial. ORS devolvio 0.0 km
    entre puntos separados por 1.89 km. No es un nulo, es una medida valida de
    un viaje que no existe, asi que el manejo de nulos no la atrapaba.
    """

    def test_descarta_una_distancia_cero_entre_puntos_distintos(self):
        a = lugar("Parque Nacional El Imposible", 13.8308664, -89.9589112)
        b = lugar("Mirador El Mulo", 13.8288039, -89.9415312)
        cliente = ClienteFalso(
            km_por_par={
                ((a.lat, a.lon), (b.lat, b.lon)): 0.0,
                ((b.lat, b.lon), (a.lat, a.lon)): 0.0,
            }
        )

        aristas = fetch_edges([a, b], "driving", cliente)

        assert aristas == {}, "una medida imposible no puede entrar a la cache"

    def test_el_par_descartado_cae_a_la_estimacion(self):
        a = lugar("Parque Nacional El Imposible", 13.8308664, -89.9589112)
        b = lugar("Mirador El Mulo", 13.8288039, -89.9415312)
        cliente = ClienteFalso(
            km_por_par={
                ((a.lat, a.lon), (b.lat, b.lon)): 0.0,
                ((b.lat, b.lon), (a.lat, a.lon)): 0.0,
            }
        )

        matriz = load_travel_matrix([a, b], "driving", client=cliente)
        km, minutos = matriz.between(a, b)

        assert matriz.stats.estimated == 2
        assert km >= haversine_km(a.lat, a.lon, b.lat, b.lon)
        assert minutos >= 1

    def test_una_medida_apenas_menor_pasa_por_redondeo(self):
        """El margen existe para la proyeccion, no para tapar ceros."""
        a = lugar("A", 13.700, -89.220)
        b = lugar("B", 13.800, -89.220)
        recta = haversine_km(a.lat, a.lon, b.lat, b.lon)
        cliente = ClienteFalso(
            km_por_par={
                ((a.lat, a.lon), (b.lat, b.lon)): recta * 0.99,
                ((b.lat, b.lon), (a.lat, a.lon)): recta * 0.99,
            }
        )

        aristas = fetch_edges([a, b], "driving", cliente)
        assert len(aristas) == 2

    def test_un_par_imposible_no_contamina_a_los_demas(self):
        a = lugar("En el parque", 13.8308664, -89.9589112)
        b = lugar("Tambien en el parque", 13.8288039, -89.9415312)
        c = lugar("En el pueblo", 13.8697, -89.8467)
        cliente = ClienteFalso(
            km_por_par={
                ((a.lat, a.lon), (b.lat, b.lon)): 0.0,
                ((b.lat, b.lon), (a.lat, a.lon)): 0.0,
            }
        )

        aristas = fetch_edges([a, b, c], "driving", cliente)

        assert (a.id, b.id) not in aristas
        assert (a.id, c.id) in aristas
        assert (c.id, b.id) in aristas


class TestObservabilidadDelCupo:
    """Lo que se reporta tiene que ser una lectura, no un valor por defecto."""

    def test_sin_respuesta_de_ors_el_cupo_restante_es_desconocido(self):
        cupo = routing.DailyQuota(45)
        assert cupo.remaining is None, "45 sin estrenar no es una lectura del cupo real"
        assert cupo.own_remaining == 45

    def test_despues_de_la_primera_respuesta_hay_lectura(self):
        cupo = routing.DailyQuota(45)
        cupo.sync_with_server(31)
        assert cupo.remaining == 31

    def test_nuestro_presupuesto_puede_ser_mas_estricto_que_el_de_ors(self):
        cupo = routing.DailyQuota(2)
        cupo.sync_with_server(40)
        cupo.try_spend()
        cupo.try_spend()
        assert cupo.remaining == 0

    def test_las_peticiones_reportadas_son_las_de_este_itinerario(self):
        """El cliente se comparte, asi que su contador es acumulado."""
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(3)]
        cliente = ClienteFalso()
        cliente.request_count = 7  # como si ya hubiera servido otros itinerarios

        matriz = load_travel_matrix(lugares, "driving", client=cliente)

        assert matriz.stats.requests == 1, "no el acumulado del proceso"


class TestPorQueNoHuboMedidasReales:
    """Las tres causas piden cosas distintas del usuario.

    Sin llave hay que configurar algo. Sin cupo hay que esperar. Sin ruta no
    hay nada que hacer: el lugar de verdad no tiene camino. Decir solo
    "estimadas" las mete en la misma bolsa.
    """

    def _lugares(self, cuantos=3):
        return [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(cuantos)]

    def test_sin_cliente_la_causa_es_la_llave(self):
        matriz = load_travel_matrix(self._lugares(), "driving", client=None)
        assert matriz.stats.reason == "no_key"

    def test_sin_cupo_la_causa_es_el_cupo(self):
        cliente = ClienteFalso(falla_con=routing.ORSBudgetExhausted("sin presupuesto"))
        cliente.request_count = 0
        matriz = load_travel_matrix(self._lugares(), "driving", client=cliente)
        assert matriz.stats.reason == "no_quota"

    def test_con_puntos_sin_carretera_la_causa_es_la_red_vial(self):
        """El caso de los cerros: ORS responde y ninguna medida sirve."""
        cerros = self._lugares()
        nulos = [((a.lat, a.lon), (b.lat, b.lon)) for a in cerros for b in cerros]
        cliente = ClienteFalso(nulos=nulos)

        matriz = load_travel_matrix(cerros, "driving", client=cliente)

        assert cliente.request_count == 1
        assert matriz.stats.reason == "unroutable"

    def test_con_medidas_reales_no_hay_causa_que_explicar(self):
        matriz = load_travel_matrix(self._lugares(), "driving", client=ClienteFalso())
        assert matriz.stats.reason is None


class TestTroceoDelTrazo:
    """Partir el trazo del dia en un tramo por par de paradas consecutivas.

    Es la pieza con mas riesgo de error silencioso de toda la geometria: si el
    troceo se equivoca, el mapa dibuja lineas que van del reves o que faltan, y
    no hay excepcion que lo delate.

    Validado tambien contra geometria real de carretera de tres paradas
    (Ataco - Apaneca - Juayua): los tramos que salen miden lo mismo que las
    distancias por tramo que reporta el enrutador, con un 0.2% de diferencia.
    """

    def test_parte_un_trazo_recto(self):
        trazo = [(i * 1.0, 0.0) for i in range(11)]
        tramos = split_by_stops(trazo, [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])

        assert len(tramos) == 2
        assert tramos[0][0] == (0.0, 0.0)
        assert tramos[0][-1] == (5.0, 0.0)
        assert tramos[1][0] == (5.0, 0.0)
        assert tramos[1][-1] == (10.0, 0.0)

    def test_los_tramos_comparten_la_parada_que_los_une(self):
        """Sin el vertice compartido el trazo sale cortado en cada parada."""
        trazo = [(i * 1.0, 0.0) for i in range(11)]
        tramos = split_by_stops(trazo, [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)])

        assert tramos[0][-1] == tramos[1][0]

    def test_ida_y_vuelta_por_la_misma_calle(self):
        """El caso que rompe la version ingenua del troceo.

        Un trazo que pasa dos veces por el mismo punto tiene dos vertices casi
        identicos. Buscando el minimo global, la parada final se anclaria a un
        vertice del principio y el segundo tramo saldria vacio o del reves.
        """
        ida = [(i * 1.0, 0.0) for i in range(6)]
        vuelta = [(i * 1.0, 0.0) for i in range(4, -1, -1)]
        tramos = split_by_stops(ida + vuelta, [(0.0, 0.0), (5.0, 0.0), (0.0, 0.0)])

        assert len(tramos) == 2
        assert all(tramo for tramo in tramos), "un tramo salio vacio"
        assert tramos[0][0] == (0.0, 0.0)
        assert tramos[0][-1] == (5.0, 0.0)
        assert tramos[1][-1] == (0.0, 0.0)

    def test_la_ultima_parada_ancla_al_final_del_trazo(self):
        """Buscarla por cercania podria dejar fuera la cola de la ruta."""
        trazo = [(i * 1.0, 0.0) for i in range(11)]
        tramos = split_by_stops(trazo, [(0.0, 0.0), (9.4, 0.0)])

        assert tramos[0][-1] == trazo[-1]

    def test_devuelve_un_tramo_menos_que_paradas(self):
        trazo = [(i * 1.0, 0.0) for i in range(21)]
        paradas = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (20.0, 0.0)]

        assert len(split_by_stops(trazo, paradas)) == len(paradas) - 1

    @pytest.mark.parametrize(
        "trazo,paradas,esperado",
        [
            ([], [(0.0, 0.0), (1.0, 0.0)], 1),
            ([(0.0, 0.0)], [(0.0, 0.0), (1.0, 0.0)], 1),
            ([(i * 1.0, 0.0) for i in range(5)], [(0.0, 0.0)], 0),
            ([(i * 1.0, 0.0) for i in range(5)], [], 0),
        ],
    )
    def test_sin_datos_devuelve_tramos_vacios_y_no_falla(self, trazo, paradas, esperado):
        """El dibujo tiene que aguantar la falta de geometria, no romperse."""
        tramos = split_by_stops(trazo, paradas)

        assert len(tramos) == esperado
        assert all(tramo == [] for tramo in tramos)


class LugarFalso:
    """Lo minimo que load_route_geometry necesita de un lugar."""

    def __init__(self, nombre: str, lat: float, lon: float) -> None:
        self.id = uuid.uuid4()
        self.name = nombre
        self.lat = lat
        self.lon = lon


class ClienteGeometriaFalso:
    """Devuelve un trazo recto entre las paradas y cuenta las peticiones."""

    def __init__(self, falla: bool = False) -> None:
        self.request_count = 0
        self.llamadas: list[list[tuple[float, float]]] = []
        self.llamadas_con_perfil: list[tuple[list, str]] = []
        self.falla = falla

    def directions(self, coords, profile):
        self.request_count += 1
        self.llamadas.append(list(coords))
        self.llamadas_con_perfil.append((list(coords), profile))
        if self.falla:
            raise ORSError("sin ruta")
        # Diez vertices por tramo, interpolados: se parece a un trazo real lo
        # suficiente para que el troceo tenga algo que partir.
        trazo = []
        for a, b in zip(coords, coords[1:], strict=False):
            for paso in range(10):
                t = paso / 10
                trazo.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        trazo.append(coords[-1])
        return trazo


class TestGeometriaDeLaRuta:
    def test_una_peticion_por_dia_y_no_por_tramo(self):
        """Es la decision que sostiene el presupuesto.

        Un dia de cuatro paradas tiene tres tramos. Pedirlos por separado
        triplicaria el costo del dia, y con cuarenta y cinco peticiones diarias
        eso se agota en una demo.
        """
        dia1 = [LugarFalso(f"A{i}", 13.70 + i * 0.01, -89.22) for i in range(4)]
        dia2 = [LugarFalso(f"B{i}", 13.80 + i * 0.01, -89.30) for i in range(3)]
        cliente = ClienteGeometriaFalso()

        trazos, stats = load_route_geometry(
            [("driving", dia1), ("driving", dia2)], client=cliente
        )

        assert cliente.request_count == 2, "una peticion por dia"
        assert stats.requests == 2
        # Tres tramos del primer dia mas dos del segundo.
        assert len(trazos) == 5
        assert stats.fetched == 5
        assert stats.straight == 0

    def test_manda_las_paradas_en_orden_y_en_lat_lon(self):
        """Invertir lat/lon no da error: devuelve una ruta en el oceano Indico."""
        dia = [LugarFalso("A", 13.70, -89.22), LugarFalso("B", 13.75, -89.30)]
        cliente = ClienteGeometriaFalso()

        load_route_geometry([("driving", dia)], client=cliente)

        assert cliente.llamadas[0] == [(13.70, -89.22), (13.75, -89.30)]

    def test_sin_cliente_no_hay_trazos_y_todos_son_rectas(self):
        """Sin llave el mapa dibuja lo de siempre, no se queda vacio."""
        dia = [LugarFalso(f"A{i}", 13.70 + i * 0.01, -89.22) for i in range(3)]

        trazos, stats = load_route_geometry([("driving", dia)])

        assert trazos == {}
        assert stats.straight == 2
        assert stats.real_ratio == 0.0

    def test_si_ors_falla_el_dia_se_queda_sin_trazo_pero_no_revienta(self):
        dia = [LugarFalso(f"A{i}", 13.70 + i * 0.01, -89.22) for i in range(3)]
        cliente = ClienteGeometriaFalso(falla=True)

        trazos, stats = load_route_geometry([("driving", dia)], client=cliente)

        assert trazos == {}
        assert stats.straight == 2
        assert stats.fetched == 0

    def test_un_dia_de_una_sola_parada_no_gasta_peticion(self):
        cliente = ClienteGeometriaFalso()

        trazos, stats = load_route_geometry(
            [("driving", [LugarFalso("Solo", 13.70, -89.22)])], client=cliente
        )

        assert cliente.request_count == 0
        assert trazos == {}
        assert stats.straight == 0

    def test_los_tramos_van_en_el_sentido_del_recorrido(self):
        """El sentido importa: un tramo del reves se dibuja igual y esta mal."""
        a = LugarFalso("A", 13.70, -89.22)
        b = LugarFalso("B", 13.75, -89.22)
        cliente = ClienteGeometriaFalso()

        trazos, _ = load_route_geometry([("driving", [a, b])], client=cliente)

        tramo = trazos[(a.id, b.id)]
        assert tramo[0][0] == pytest.approx(13.70, abs=1e-6)
        assert tramo[-1][0] == pytest.approx(13.75, abs=1e-6)


class TestGeometriaPorModo:
    """El trazo depende de la red, no solo de las coordenadas.

    El camino a pie entre dos plazas no es el mismo que el del carro —un sendero
    que el peaton cruza no existe para el vehiculo— asi que dibujar uno por el
    otro seria mentir sobre el recorrido. Por eso el modo va por dia y no por
    itinerario.
    """

    def test_pide_cada_dia_con_el_perfil_de_su_modo(self):
        coche = [LugarFalso(f"C{i}", 13.70 + i * 0.01, -89.22) for i in range(3)]
        pie = [LugarFalso(f"P{i}", 13.80 + i * 0.002, -89.30) for i in range(3)]
        cliente = ClienteGeometriaFalso()

        load_route_geometry([("driving", coche), ("walking", pie)], client=cliente)

        perfiles = [perfil for _, perfil in cliente.llamadas_con_perfil]
        assert perfiles == [
            routing.ORS_PROFILES["driving"],
            routing.ORS_PROFILES["walking"],
        ]

    def test_un_itinerario_de_un_solo_modo_no_cambia_nada(self):
        dia = [LugarFalso(f"A{i}", 13.70 + i * 0.01, -89.22) for i in range(3)]
        cliente = ClienteGeometriaFalso()

        _, stats = load_route_geometry([("driving", dia)], client=cliente)

        assert cliente.request_count == 1
        assert stats.fetched == 2


class TestUn403NoEsUnaCarreteraQueFalta:
    """ "Quota exceeded" y "punto sin carretera" se arreglan distinto.

    Una se espera a que ruede la ventana; la otra no tiene arreglo. El sintoma
    estaba en pantalla: la cabecera decia "estas paradas estan lejos de toda
    carretera y no se pueden medir" mientras el mapa dibujaba siete de nueve
    tramos por carretera. La causa era el cupo, y el motor no lo distinguia
    porque un 403 tambien cuenta como peticion hecha.
    """

    def test_el_403_deja_el_cupo_en_cero(self, monkeypatch):
        respuesta = RespuestaFalsa(403, {"error": "Quota exceeded"})
        monkeypatch.setattr(
            routing.httpx, "post", lambda url, json, headers, timeout: respuesta
        )
        cliente = ORSClient("llave", min_interval_seconds=0)

        with pytest.raises(routing.ORSQuotaExhausted):
            cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")

        assert cliente.matrix_quota.remaining == 0, (
            "el 403 no trae cabecera de cupo: es la unica noticia de que no queda"
        )
        # Y no apaga el otro endpoint, que tiene su propio cupo.
        assert cliente.directions_quota.remaining is None

    def test_con_el_cupo_agotado_la_causa_es_el_cupo(self):
        lugares = [lugar(f"L{i}", 13.7 + i * 0.01, -89.2) for i in range(3)]
        cliente = ClienteFalso(falla_con=routing.ORSQuotaExhausted("Quota exceeded"))
        # Como lo deja el cliente real despues de un 403.
        cliente.matrix_quota.sync_with_server(0)

        matriz = load_travel_matrix(lugares, "driving", client=cliente)

        assert matriz.stats.reason == "no_quota"
        # Tres lugares son seis pares ordenados, no tres.
        assert matriz.stats.fetched == 0 and matriz.stats.estimated == 6


class TestCadaEndpointConSuTecho:
    """Los cupos de ORS no son iguales, y con un solo numero el trazo perdia.

    Medido en las cabeceras de sus respuestas: la matriz da 50 y las
    direcciones 200. Un techo compartido de 45 dejaba el trazo por carretera
    limitado a menos de la cuarta parte de lo que ORS permite, y el trazo es
    lo que se ve en el mapa.
    """

    def test_el_trazo_tiene_su_propio_techo(self):
        cliente = ORSClient("llave", daily_budget=45, directions_budget=180)

        assert cliente.matrix_quota.budget == 45
        assert cliente.directions_quota.budget == 180

    def test_gastar_la_matriz_no_gasta_el_trazo(self, monkeypatch):
        respuestas = {
            "matrix": RespuestaFalsa(200, {"distances": [[0, 1]], "durations": [[0, 60]]}),
            "directions": RespuestaFalsa(
                200,
                {"features": [{"geometry": {"coordinates": [[-89.2, 13.7], [-89.5, 14.0]]}}]},
            ),
        }
        monkeypatch.setattr(
            routing.httpx,
            "post",
            lambda url, json, headers, timeout: respuestas[
                "directions" if "directions" in url else "matrix"
            ],
        )
        cliente = ORSClient(
            "llave", min_interval_seconds=0, daily_budget=1, directions_budget=3
        )

        cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")
        with pytest.raises(routing.ORSBudgetExhausted):
            cliente.matrix([SAN_SALVADOR, SANTA_ANA], "driving-car")

        # Al trazo le quedan sus tres, intactas.
        for _ in range(3):
            assert cliente.directions([SAN_SALVADOR, SANTA_ANA], "driving-car")
        with pytest.raises(routing.ORSBudgetExhausted):
            cliente.directions([SAN_SALVADOR, SANTA_ANA], "driving-car")

    def test_sin_segundo_numero_los_dos_comparten_el_mismo(self):
        """El valor por defecto no cambia el comportamiento de quien no lo pasa."""
        cliente = ORSClient("llave", daily_budget=45)

        assert cliente.directions_quota.budget == 45
