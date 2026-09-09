"""Tests del motor de itinerarios.

Se prueban las funciones puras con lugares construidos a mano: no hacen falta
ni base de datos ni catalogo para verificar que una restriccion se respeta.
"""

import uuid
from datetime import time

import pytest

from app.models import Category
from app.services.geo import DETOUR_FACTOR, haversine_km, speed_kmh
from app.services.itinerary import (
    Constraints,
    Day,
    Itinerary,
    Stop,
    _route_km,
    build_days,
    estimate_travel,
    order_by_proximity,
    schedule_day,
    validate,
)
from app.services.places import PlaceHit

SAN_SALVADOR = (13.6929, -89.2182)
SANTA_ANA = (13.9942, -89.5597)


def lugar(nombre, lat, lon, categoria=Category.attraction, calidad=0.5) -> PlaceHit:
    return PlaceHit(
        id=uuid.uuid4(),
        name=nombre,
        category=categoria.value,
        subcategory=None,
        lat=lat,
        lon=lon,
        quality_score=calidad,
    )


class TestGeometria:
    def test_la_distancia_conocida_es_correcta(self):
        """San Salvador a Santa Ana: unos 55 km en linea recta."""
        km = haversine_km(*SAN_SALVADOR, *SANTA_ANA)
        assert 45 < km < 65

    def test_la_distancia_a_si_mismo_es_cero(self):
        assert haversine_km(*SAN_SALVADOR, *SAN_SALVADOR) == pytest.approx(0, abs=0.001)

    def test_el_tiempo_estimado_depende_del_modo(self):
        a = lugar("A", 13.6929, -89.2182)
        b = lugar("B", 13.7100, -89.2182)
        _, minutos_a_pie = estimate_travel(a, b, "walking")
        _, minutos_en_auto = estimate_travel(a, b, "driving")
        assert minutos_a_pie > minutos_en_auto

    def test_la_estimacion_supera_la_linea_recta(self):
        """Los caminos reales dan vuelta; estimar la geodesica seria optimista."""
        a = lugar("A", 13.6929, -89.2182)
        b = lugar("B", 13.7929, -89.2182)
        km, _ = estimate_travel(a, b, "driving")
        assert km > haversine_km(a.lat, a.lon, b.lat, b.lon)


class TestCalibracion:
    """Las constantes salieron de scripts/calibrate_travel, no de la intuicion.

    Medido sobre 812 pares del catalogo contra OpenRouteService.
    """

    def test_en_carro_la_velocidad_sube_con_la_distancia(self):
        """Un salto urbano y la carretera a Santa Ana no se recorren igual."""
        urbano = speed_kmh("driving", 1.0)
        medio = speed_kmh("driving", 5.0)
        largo = speed_kmh("driving", 80.0)

        assert urbano < medio < largo

    def test_a_pie_la_velocidad_es_plana(self):
        """ORS usa 5 km/h fijos para el perfil peatonal, sin mirar pendiente.

        Se replica su comportamiento a proposito: fingir una variacion que la
        fuente no tiene seria inventar precision.
        """
        assert speed_kmh("walking", 0.5) == speed_kmh("walking", 40.0)

    def test_un_modo_desconocido_cae_a_los_tramos_de_carro(self):
        assert speed_kmh("teleport", 30.0) == speed_kmh("driving", 30.0)

    def test_el_desvio_supera_la_linea_recta_en_todo_tramo(self):
        for km in (0.5, 5.0, 30.0, 120.0):
            assert DETOUR_FACTOR > 1.0, km

    def test_el_tramo_largo_tarda_menos_por_kilometro(self):
        """La correccion que motivo la recalibracion.

        Con una sola velocidad de 40 km/h, un viaje de cien kilometros salia
        al doble del tiempo real. Ahora el minuto por kilometro baja cuando el
        viaje se alarga.
        """
        cerca = lugar("A", 13.700, -89.220)
        vecino = lugar("B", 13.706, -89.226)
        lejos = lugar("C", 14.400, -89.900)

        km_corto, min_corto = estimate_travel(cerca, vecino, "driving")
        km_largo, min_largo = estimate_travel(cerca, lejos, "driving")

        assert min_corto / km_corto > min_largo / km_largo


class TestOrdenamiento:
    def test_deshace_el_zigzag(self):
        """Un orden cruzado debe salir mas corto tras reordenar."""
        paradas = [
            lugar("A", 13.70, -89.22),
            lugar("C", 13.72, -89.22),
            lugar("B", 13.71, -89.22),
            lugar("D", 13.73, -89.22),
        ]
        antes = _route_km(paradas)
        despues = _route_km(order_by_proximity(paradas))
        assert despues < antes

    def test_no_pierde_ni_agrega_paradas(self):
        paradas = [lugar(f"P{i}", 13.70 + i * 0.01, -89.22) for i in range(6)]
        ordenadas = order_by_proximity(paradas)
        assert len(ordenadas) == len(paradas)
        assert {p.name for p in ordenadas} == {p.name for p in paradas}

    def test_con_una_o_dos_paradas_no_cambia_nada(self):
        una = [lugar("A", 13.70, -89.22)]
        assert order_by_proximity(una) == una


class TestArmadoDeDias:
    def test_arma_la_cantidad_de_dias_pedida(self):
        candidatos = [lugar(f"P{i}", 13.70 + i * 0.005, -89.22) for i in range(20)]
        restricciones = Constraints(days=3, center_lat=13.70, center_lon=-89.22)
        assert len(build_days(candidatos, restricciones)) == 3

    def test_no_repite_lugares_entre_dias(self):
        candidatos = [lugar(f"P{i}", 13.70 + i * 0.005, -89.22) for i in range(20)]
        restricciones = Constraints(days=3, center_lat=13.70, center_lon=-89.22)
        dias = build_days(candidatos, restricciones)

        vistos = [p.name for dia in dias for p in dia]
        assert len(vistos) == len(set(vistos)), "Un lugar aparece en dos dias"

    def test_respeta_el_presupuesto_de_traslado(self):
        """Lugares muy separados no pueden entrar todos en el mismo dia."""
        candidatos = [lugar(f"P{i}", 13.70 + i * 0.15, -89.22) for i in range(10)]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=20
        )
        dias = build_days(candidatos, restricciones)
        # _route_km devuelve kilometros de traslado, con el desvio ya aplicado.
        # Antes de la fase 4 este test multiplicaba otra vez por 1.35 y seguia
        # pasando por casualidad, porque el resultado quedaba lejos del limite.
        assert _route_km(dias[0]) <= 20

    def test_con_pocos_lugares_arma_menos_dias(self):
        candidatos = [lugar("Unico", 13.70, -89.22)]
        restricciones = Constraints(days=5, center_lat=13.70, center_lon=-89.22)
        assert len(build_days(candidatos, restricciones)) == 1

    def test_prefiere_las_categorias_pedidas(self):
        candidatos = [
            lugar("Comun", 13.70, -89.22, Category.attraction, 0.5),
            lugar("Preferida", 13.7001, -89.22, Category.nature, 0.5),
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            preferred_categories=[Category.nature],
            max_stops_per_day=1,
            include_meals=False,
        )
        dias = build_days(candidatos, restricciones)
        assert dias[0][0].name == "Preferida"


class TestHorarios:
    def test_nunca_empieza_antes_de_la_hora_pedida(self):
        """La traduccion de "odio madrugar" a un limite que se cumple."""
        secuencia = [(lugar(f"P{i}", 13.70 + i * 0.01, -89.22), None) for i in range(4)]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(10, 0)
        )
        dia = schedule_day(1, secuencia, restricciones)
        assert dia.start == time(10, 0)
        assert all(s.arrival >= time(10, 0) for s in dia.stops)

    def test_las_paradas_no_se_solapan(self):
        secuencia = [(lugar(f"P{i}", 13.70 + i * 0.01, -89.22), None) for i in range(5)]
        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        dia = schedule_day(1, secuencia, restricciones)

        for anterior, siguiente in zip(dia.stops, dia.stops[1:], strict=False):
            assert siguiente.arrival >= anterior.departure, "Dos paradas a la vez"

    def test_el_almuerzo_no_se_sirve_antes_de_su_franja(self):
        secuencia = [
            (lugar("Mirador", 13.70, -89.22, Category.viewpoint), None),
            (lugar("Restaurante", 13.7005, -89.22, Category.food), "lunch"),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(8, 0)
        )
        dia = schedule_day(1, secuencia, restricciones)
        comida = next(s for s in dia.stops if s.is_meal)
        assert comida.arrival >= time(11, 30)

    def test_cada_parada_dura_segun_su_categoria(self):
        secuencia = [
            (lugar("Mirador", 13.70, -89.22, Category.viewpoint), None),
            (lugar("Reserva", 13.7005, -89.22, Category.nature), None),
        ]
        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        dia = schedule_day(1, secuencia, restricciones)

        def minutos(parada):
            return (parada.departure.hour * 60 + parada.departure.minute) - (
                parada.arrival.hour * 60 + parada.arrival.minute
            )

        assert minutos(dia.stops[0]) == 30
        assert minutos(dia.stops[1]) == 105


class TestVerificacion:
    def _itinerario(self, stops, restricciones):
        dia = Day(number=1, stops=stops)
        return Itinerary(days=[dia]), restricciones

    def test_un_itinerario_correcto_no_reporta_violaciones(self):
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(10, 0)
        )
        stops = [
            Stop(lugar("A", 13.70, -89.22), time(10, 0), time(11, 0)),
            Stop(lugar("B", 13.705, -89.22), time(11, 20), time(12, 20), 20, 1.5),
        ]
        itinerario, _ = self._itinerario(stops, restricciones)
        assert validate(itinerario, restricciones) == []
        assert itinerario.satisfies_all_constraints

    def test_detecta_que_empieza_demasiado_temprano(self):
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(10, 0)
        )
        stops = [Stop(lugar("A", 13.70, -89.22), time(7, 30), time(8, 30))]
        itinerario, _ = self._itinerario(stops, restricciones)
        motivos = [v.constraint for v in validate(itinerario, restricciones)]
        assert "earliest_start" in motivos

    def test_detecta_que_termina_demasiado_tarde(self):
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, latest_end=time(19, 0)
        )
        stops = [Stop(lugar("A", 13.70, -89.22), time(18, 0), time(22, 0))]
        itinerario, _ = self._itinerario(stops, restricciones)
        motivos = [v.constraint for v in validate(itinerario, restricciones)]
        assert "latest_end" in motivos

    def test_detecta_que_se_paso_del_limite_de_traslado(self):
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=10
        )
        stops = [
            Stop(lugar("A", 13.70, -89.22), time(10, 0), time(11, 0)),
            Stop(lugar("B", 13.90, -89.22), time(12, 0), time(13, 0), 60, 25.0),
        ]
        itinerario, _ = self._itinerario(stops, restricciones)
        violaciones = validate(itinerario, restricciones)
        assert any(v.constraint == "max_travel_km_per_day" for v in violaciones)
        # La violacion informa la magnitud, no solo que fallo.
        assert "25.0" in next(
            v.detail for v in violaciones if v.constraint == "max_travel_km_per_day"
        )

    def test_detecta_una_categoria_que_se_pidio_evitar(self):
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            avoided_categories=[Category.food],
        )
        stops = [
            Stop(lugar("Comedor", 13.70, -89.22, Category.food), time(12, 0), time(13, 0))
        ]
        itinerario, _ = self._itinerario(stops, restricciones)
        motivos = [v.constraint for v in validate(itinerario, restricciones)]
        assert "avoided_categories" in motivos

    def test_detecta_que_faltaron_dias(self):
        restricciones = Constraints(days=3, center_lat=13.70, center_lon=-89.22)
        itinerario = Itinerary(days=[Day(number=1, stops=[])])
        violaciones = validate(itinerario, restricciones)
        assert any(v.constraint == "days" for v in violaciones)


class TestFranjasDeComida:
    """El bug que producia cenas a media tarde."""

    def test_la_cena_espera_a_su_franja(self):
        from app.services.itinerary import DINNER_WINDOW

        secuencia = [
            (lugar("Mirador", 13.70, -89.22, Category.viewpoint), None),
            (lugar("Restaurante", 13.7005, -89.22, Category.food), "dinner"),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(10, 0)
        )
        dia = schedule_day(1, secuencia, restricciones)
        cena = next(s for s in dia.stops if s.meal == "dinner")
        assert cena.arrival >= DINNER_WINDOW[0], (
            f"La cena quedo a las {cena.arrival:%H:%M}, antes de que abra la franja"
        )

    def test_un_dia_corto_no_lleva_cena(self):
        """Si el dia termina a media tarde, no se inventa una cena."""
        from app.services.itinerary import _insert_meals

        ruta = [lugar("Mirador", 13.70, -89.22, Category.viewpoint)]
        comidas = [
            lugar("Almuerzo", 13.7001, -89.22, Category.food),
            lugar("Otro", 13.7002, -89.22, Category.food),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(10, 0)
        )
        secuencia = _insert_meals(ruta, comidas, restricciones)
        assert not any(tipo == "dinner" for _, tipo in secuencia)

    def test_un_dia_largo_si_lleva_cena(self):
        from app.services.itinerary import _insert_meals

        ruta = [lugar(f"P{i}", 13.70 + i * 0.004, -89.22, Category.nature) for i in range(4)]
        comidas = [
            lugar(f"C{i}", 13.7001 + i * 0.001, -89.22, Category.food) for i in range(3)
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(10, 0)
        )
        secuencia = _insert_meals(ruta, comidas, restricciones)
        assert any(tipo == "dinner" for _, tipo in secuencia)

    def test_ninguna_comida_se_repite_en_el_dia(self):
        from app.services.itinerary import _insert_meals

        ruta = [lugar(f"P{i}", 13.70 + i * 0.004, -89.22, Category.nature) for i in range(4)]
        comidas = [
            lugar(f"C{i}", 13.7001 + i * 0.001, -89.22, Category.food) for i in range(3)
        ]
        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        secuencia = _insert_meals(ruta, comidas, restricciones)

        nombres = [p.name for p, tipo in secuencia if tipo]
        assert len(nombres) == len(set(nombres))


class TestAtractivo:
    """Los dos bugs que aparecieron con el catalogo real."""

    def test_un_volcan_vale_mas_que_una_plaza(self):
        from app.services.itinerary import appeal_of

        volcan = lugar("Volcan de Izalco", 13.81, -89.63, Category.nature)
        volcan.subcategory = "volcano"
        plaza = lugar("Plaza Fusion de las Razas", 13.81, -89.63, Category.nature)
        plaza.subcategory = "park"

        assert appeal_of(volcan) > appeal_of(plaza)

    def test_el_atractivo_pesa_mas_que_el_registro_completo(self):
        """Un volcan sin horarios sigue siendo mejor destino que una plaza
        bien documentada."""
        volcan = lugar("Volcan", 13.81, -89.63, Category.nature, calidad=0.4)
        volcan.subcategory = "volcano"
        plaza = lugar("Plaza Central", 13.81, -89.63, Category.nature, calidad=0.9)
        plaza.subcategory = "park"

        restricciones = Constraints(days=1, center_lat=13.81, center_lon=-89.63)
        from app.services.itinerary import score_candidate

        assert score_candidate(volcan, restricciones) > score_candidate(plaza, restricciones)

    def test_el_mobiliario_urbano_queda_bajo_el_umbral(self):
        from app.services.itinerary import MIN_APPEAL, appeal_of

        for subcategoria in ("park", "artwork", "memorial"):
            sitio = lugar("X", 13.81, -89.63, Category.nature)
            sitio.subcategory = subcategoria
            assert appeal_of(sitio) < MIN_APPEAL, (
                f"{subcategoria} deberia quedar fuera del itinerario"
            )

    def test_los_destinos_reales_superan_el_umbral(self):
        from app.services.itinerary import MIN_APPEAL, appeal_of

        for subcategoria in ("volcano", "waterfall", "beach", "museum", "viewpoint"):
            sitio = lugar("X", 13.81, -89.63, Category.nature)
            sitio.subcategory = subcategoria
            assert appeal_of(sitio) >= MIN_APPEAL


class TestPresupuestoConComidas:
    """El limite de traslado se violaba porque las comidas no se contaban."""

    def test_el_dia_respeta_el_limite_con_comidas_incluidas(self):
        from app.services.itinerary import _day_travel_km, _trim_to_budget

        destinos = [
            lugar(f"D{i}", 13.70 + i * 0.03, -89.22, Category.nature) for i in range(5)
        ]
        # Restaurante lejos del recorrido: es el que rompia el presupuesto.
        comidas = [lugar("Lejano", 13.90, -89.40, Category.food)]

        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=15
        )
        secuencia = _trim_to_budget(destinos, comidas, restricciones)
        km = _day_travel_km(secuencia, restricciones.mode)

        assert km <= 15, f"El dia recorre {km} km y el limite era 15"

    def test_quita_paradas_solo_lo_necesario(self):
        from app.services.itinerary import _trim_to_budget

        destinos = [
            lugar(f"D{i}", 13.70 + i * 0.002, -89.22, Category.nature) for i in range(4)
        ]
        comidas = [lugar("Cerca", 13.7005, -89.22, Category.food)]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=50
        )
        secuencia = _trim_to_budget(destinos, comidas, restricciones)

        # Con presupuesto de sobra no deberia sacrificar ningun destino.
        nombres = {p.name for p, tipo in secuencia if not tipo}
        assert nombres == {d.name for d in destinos}

    def test_siempre_queda_al_menos_una_parada(self):
        """Aunque el presupuesto sea imposible, el dia no queda vacio."""
        from app.services.itinerary import _trim_to_budget

        destinos = [lugar(f"D{i}", 13.70 + i * 0.5, -89.22, Category.nature) for i in range(3)]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=1
        )
        secuencia = _trim_to_budget(destinos, [], restricciones)
        assert len(secuencia) >= 1


class TestListaDePermitidos:
    """Lo desconocido no entra al itinerario."""

    def test_una_subcategoria_desconocida_queda_fuera(self):
        from app.services.itinerary import MIN_APPEAL, appeal_of

        sitio = lugar("Algo Nuevo", 13.81, -89.63, Category.nature)
        sitio.subcategory = "etiqueta_que_no_existia_antes"
        assert appeal_of(sitio) < MIN_APPEAL

    def test_el_detalle_del_paisaje_queda_fuera(self):
        from app.services.itinerary import MIN_APPEAL, appeal_of

        for subcategoria in ("wayside_cross", "boundary_stone", "stone", "building"):
            sitio = lugar("X", 13.81, -89.63, Category.culture)
            sitio.subcategory = subcategoria
            assert appeal_of(sitio) < MIN_APPEAL, f"{subcategoria} no deberia entrar"

    def test_el_patrimonio_menos_evidente_si_entra(self):
        from app.services.itinerary import MIN_APPEAL, appeal_of

        for subcategoria in ("pyramid", "manor", "wreck", "church"):
            sitio = lugar("X", 13.81, -89.63, Category.culture)
            sitio.subcategory = subcategoria
            assert appeal_of(sitio) >= MIN_APPEAL, f"{subcategoria} deberia entrar"
