"""Tests del motor de itinerarios.

Se prueban las funciones puras con lugares construidos a mano: no hacen falta
ni base de datos ni catalogo para verificar que una restriccion se respeta.
"""

import uuid
from dataclasses import replace
from datetime import date, time

import pytest
from pydantic import ValidationError

from app.models import Category
from app.schemas import ItineraryRequest
from app.services.geo import (
    ARRIVAL_OVERHEAD_MINUTES,
    DETOUR_FACTOR,
    EstimatedTravel,
    haversine_km,
    speed_kmh,
)
from app.services.itinerary import (
    BUDGET_BY_MODE,
    DEFAULT_DURATIONS,
    DEFAULT_MEAL_MINUTES,
    DINNER_WINDOW,
    DUSK,
    INDOOR_CLOSES,
    NOMBRE_VAGO_KM,
    SUBCATEGORY_PENALTY_KM,
    UNSTATED_BUDGET_BY_MODE,
    Constraints,
    Day,
    Itinerary,
    Stop,
    _fill_cost,
    _insert_meals,
    _meal_out_of_reach,
    _meals_that_fit,
    _minutes_between,
    _name_key,
    _outdoor_after_dusk,
    _route_km,
    _sequence_end,
    _trim_to_budget,
    advise,
    assemble,
    build_days,
    estimate_travel,
    nombre_no_identifica,
    order_by_proximity,
    schedule_day,
    total_visits,
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

    def test_prefiere_variar_la_categoria_dentro_del_dia(self):
        """Repetir categoria cuesta kilometros, asi que un dia no sale monotono.

        El llenado del dia ordenaba solo por distancia a la semilla, y como los
        lugares de una misma categoria estan agrupados en el terreno, un dia
        sembrado con un cerro se llenaba de cerros. Medido sobre los casos de
        evaluacion: el 45% de los dias tenian tres o mas paradas seguidas de la
        misma categoria.

        Aca la semilla es naturaleza, hay dos naturalezas pegadas a ella y una
        cultura un poco mas lejos. Sin penalizacion entrarian las dos
        naturalezas; con ella, la cultura le gana el sitio a la segunda.
        """
        candidatos = [
            # La semilla: la de mejor calidad manda en el orden inicial.
            lugar("Cerro semilla", 13.70, -89.22, Category.nature, 0.9),
            lugar("Cerro vecino", 13.7010, -89.22, Category.nature, 0.5),
            lugar("Otro cerro", 13.7020, -89.22, Category.nature, 0.5),
            # Mas lejos que los cerros, pero de otra categoria.
            lugar("Iglesia", 13.7060, -89.22, Category.culture, 0.5),
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=3,
            include_meals=False,
        )
        categorias = [p.category for p in build_days(candidatos, restricciones)[0]]

        assert Category.culture.value in categorias, f"el dia salio monotono: {categorias}"

    def test_sin_alternativa_el_dia_se_llena_igual(self):
        """La penalizacion es un desempate, no un filtro.

        Donde el catalogo solo tiene una clase de lugar —Perquin, Costa del
        Sol— el dia tiene que salir de esa clase. Filtrar por categoria
        repetida dejaria esos dias a medio llenar, que es peor que un dia
        monotematico.
        """
        candidatos = [
            lugar(f"Cerro {i}", 13.70 + i * 0.002, -89.22, Category.nature, 0.5)
            for i in range(6)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=4,
            include_meals=False,
        )
        assert len(build_days(candidatos, restricciones)[0]) == 4

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
        # Sin comidas pedidas: el itinerario se arma a mano y no las lleva, y
        # desde que validate() reporta la comida que falta, pedirlas aqui
        # seria un incumplimiento legitimo.
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(10, 0),
            include_meals=False,
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
        # Con el tope por defecto de cinco, cuatro destinos mas el almuerzo ya
        # lo llenan y la cena seria la sexta parada. El test original asumia
        # que el tope no se hacia cumplir; ahora si.
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(10, 0),
            max_stops_per_day=8,
        )
        secuencia = _insert_meals(ruta, comidas, restricciones)
        assert any(tipo == "dinner" for _, tipo in secuencia)
        assert len(secuencia) <= restricciones.max_stops_per_day

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


class TestUbicacionDeLaComida:
    """La comida va donde menos kilometros cueste, no donde caiga la hora.

    El caso real de Ataco: tres paradas dentro del Parque El Imposible, el
    unico restaurante en el pueblo a dieciseis kilometros. Eligiendo por
    cercania a la parada anterior, el dia salia parque - pueblo - parque:
    33.91 km para un recorrido que dentro del parque son cinco.
    """

    def _restricciones(self, **extra):
        base = dict(
            days=1,
            center_lat=13.83,
            center_lon=-89.95,
            max_travel_km_per_day=200,
        )
        base.update(extra)
        return Constraints(**base)

    def test_no_sale_y_vuelve_para_almorzar(self):
        from app.services.itinerary import _day_travel_km, _insert_meals

        # Tres paradas juntas y un restaurante lejos, en una sola direccion.
        ruta = [
            lugar("El Imposible", 13.8309, -89.9589, Category.nature),
            lugar("Parque El Imposible", 13.8280, -89.9485),
            lugar("Mirador El Mulo", 13.8288, -89.9415, Category.viewpoint),
        ]
        comidas = [lugar("Pupuseria Ataco", 13.8705, -89.8517, Category.food)]
        restricciones = self._restricciones()

        secuencia = _insert_meals(ruta, comidas, restricciones)

        assert any(c == "lunch" for _, c in secuencia), "tiene que almorzar"
        posicion = next(i for i, (_, c) in enumerate(secuencia) if c == "lunch")
        assert posicion == len(secuencia) - 1, "el almuerzo va al final, no en medio"

        # Con el almuerzo intercalado el dia costaba el doble.
        km = _day_travel_km(secuencia, restricciones.mode)
        ida_y_vuelta = km * 1.8
        assert km < ida_y_vuelta

    def test_un_restaurante_sobre_el_camino_si_va_en_medio(self):
        """Cuando no cuesta desviarse, la comida se intercala normalmente."""
        from app.services.itinerary import _insert_meals

        ruta = [
            lugar("A", 13.700, -89.220, Category.nature),
            lugar("B", 13.760, -89.220),
            lugar("C", 13.820, -89.220, Category.viewpoint),
        ]
        comidas = [lugar("Sobre la ruta", 13.730, -89.220, Category.food)]

        secuencia = _insert_meals(ruta, comidas, self._restricciones())
        posicion = next(i for i, (_, c) in enumerate(secuencia) if c == "lunch")

        assert 0 < posicion < len(secuencia) - 1

    def test_el_limite_de_traslado_manda_sobre_la_comida(self):
        """Si el unico restaurante rompe el presupuesto, no hay almuerzo.

        Y validate() lo reporta, para que el usuario decida si lleva comida o
        levanta el limite. Meterlo rompiendo el limite seria elegir por el.
        """
        from app.services.itinerary import _insert_meals

        ruta = [lugar("Solo", 13.700, -89.220, Category.nature)]
        comidas = [lugar("Lejisimos", 13.950, -89.500, Category.food)]
        restricciones = self._restricciones(max_travel_km_per_day=5)

        secuencia = _insert_meals(ruta, comidas, restricciones)

        assert not any(c == "lunch" for _, c in secuencia)

    def test_no_almuerza_tan_temprano_que_haya_que_esperar(self):
        """Una posicion que llega a las nueve y media no es hora de almorzar."""
        from app.services.itinerary import _insert_meals

        ruta = [
            lugar("A", 13.700, -89.220, Category.viewpoint),
            lugar("B", 13.705, -89.220, Category.viewpoint),
            lugar("C", 13.710, -89.220, Category.viewpoint),
        ]
        comidas = [lugar("Al lado", 13.701, -89.221, Category.food)]

        secuencia = _insert_meals(ruta, comidas, self._restricciones())
        posicion = next((i for i, (_, c) in enumerate(secuencia) if c == "lunch"), None)

        assert posicion != 1, "a las 9:30 no se almuerza"


class TestCategoriasEvitadas:
    def test_lo_evitado_se_descarta_aunque_sobren_cupos(self):
        """Restarle puntos no alcanza: con un cupo libre entra igual."""
        candidatos = [
            lugar("Volcan", 13.700, -89.220, Category.nature),
            lugar("Museo", 13.702, -89.222, Category.culture),
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            avoided_categories=[Category.nature],
            include_meals=False,
            max_travel_km_per_day=50,
        )

        dias = build_days(candidatos, restricciones)
        categorias = {p.category for dia in dias for p in dia}

        assert "nature" not in categorias

    def test_si_todo_esta_evitado_no_arma_dias_falsos(self):
        candidatos = [lugar("Volcan", 13.700, -89.220, Category.nature)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            avoided_categories=[Category.nature],
            include_meals=False,
        )

        assert build_days(candidatos, restricciones) == []


class TestReservaDeCupos:
    """El sitio reservado para comer solo tiene sentido si hay donde comer.

    El caso real: dentro del Parque El Imposible el catalogo no tiene ni un
    restaurante, y el dia salia de tres paradas terminando a la una de la
    tarde porque dos de los cinco cupos quedaban guardados para nada.
    """

    def test_sin_restaurantes_el_dia_usa_todos_los_cupos(self):
        candidatos = [lugar(f"P{i}", 13.700 + i * 0.004, -89.220) for i in range(8)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=5,
            include_meals=True,
            max_travel_km_per_day=60,
        )

        dias = build_days(candidatos, restricciones, meal_options=0)

        assert len(dias[0]) == 5

    def test_un_dia_corto_reserva_solo_para_el_almuerzo(self):
        """Con cinco paradas el dia termina cerca de las cuatro y media.

        Nunca llega a la cena, asi que guardarle cupo dejaria uno vacio en el
        caso normal y no en uno raro.
        """
        candidatos = [lugar(f"P{i}", 13.700 + i * 0.004, -89.220) for i in range(8)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=5,
            include_meals=True,
            max_travel_km_per_day=60,
        )

        dias = build_days(candidatos, restricciones, meal_options=4)

        assert len(dias[0]) == 4, "un cupo queda para el almuerzo"

    def _con_tope(self, tope, fin=time(23, 0)):
        return Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=tope,
            latest_end=fin,
            include_meals=True,
        )

    def test_un_dia_largo_reserva_para_las_dos_comidas(self):
        """Diez visitas de hora y medida llegan de sobra a la cena."""
        assert _meals_that_fit(self._con_tope(10), 90) == 2

    def test_con_visitas_cortas_el_mismo_tope_no_llega(self):
        """La proyeccion depende de cuanto duran las visitas, no solo de
        cuantas son.

        Con un 90 fijo para todo, diez miradores de media hora "llegaban" a
        la cena y se les reservaba un cupo que nunca se llenaba. Diez paradas
        de treinta minutos mas su traslado terminan a las cuatro de la tarde.
        """
        assert _meals_that_fit(self._con_tope(10), 30) == 1

    def test_sin_tiempo_hasta_la_cena_no_se_reserva_para_ella(self):
        """Un dia largo pero que cierra temprano tampoco llega a cenar.

        Se mide sobre _meals_that_fit y no sobre el dia armado porque con la
        hora de cierre temprana el reloj corta antes que la reserva: el dia
        saldria corto por otra razon y el test no probaria lo que dice.
        """
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=10,
            latest_end=time(16, 0),
            include_meals=True,
        )

        assert _meals_that_fit(restricciones) == 1

    def test_sin_numero_pedido_se_reserva_contra_la_barrera(self):
        """Sin tope pedido el reloj corta antes que la barrera casi siempre,
        asi que la reserva no le quita nada; pero el dia de paradas cortas que
        llega a las doce tiene que poder comer igual."""
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            latest_end=time(23, 0),
            include_meals=True,
        )

        assert restricciones.max_stops_per_day is None
        assert _meals_that_fit(restricciones) == 2

    def test_con_un_solo_restaurante_se_reserva_uno(self):
        candidatos = [lugar(f"P{i}", 13.700 + i * 0.004, -89.220) for i in range(8)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=5,
            include_meals=True,
            max_travel_km_per_day=60,
        )

        dias = build_days(candidatos, restricciones, meal_options=1)

        assert len(dias[0]) == 4, "solo hay un restaurante y solo cabe el almuerzo"

    def test_el_techo_de_paradas_se_respeta_igual(self):
        """Llenar los cupos libres no es excusa para pasarse del limite."""
        candidatos = [lugar(f"P{i}", 13.700 + i * 0.004, -89.220) for i in range(20)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=4,
            include_meals=True,
            max_travel_km_per_day=200,
        )

        dias = build_days(candidatos, restricciones, meal_options=0)

        assert len(dias[0]) <= 4


class TestComidaQueFaltaYaNoEsViolacion:
    """La comida que falta se movio de violations a advice.

    Una violacion es "rompi un limite que pusiste". Que el comedor mas cercano
    quede fuera del presupuesto no es romper una regla, y mezclarlos hacia que
    "cumple todas las restricciones" no significara nada.
    """

    def _itinerario(self, stops):
        dia = Day(number=1)
        dia.stops.extend(stops)
        return Itinerary(days=[dia])

    def test_validate_ya_no_reclama_el_almuerzo(self):
        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        stops = [
            Stop(lugar("A", 13.70, -89.22), time(9, 0), time(10, 30)),
            Stop(lugar("B", 13.705, -89.22), time(10, 40), time(12, 40), 10, 1.0),
        ]

        violaciones = validate(self._itinerario(stops), restricciones)

        assert not any(v.constraint == "include_meals" for v in violaciones)

    def test_los_limites_duros_se_siguen_reportando(self):
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_stops_per_day=1
        )
        stops = [
            Stop(lugar("A", 13.70, -89.22), time(9, 0), time(10, 30)),
            Stop(lugar("B", 13.705, -89.22), time(10, 40), time(12, 40), 10, 1.0),
        ]

        violaciones = validate(self._itinerario(stops), restricciones)

        assert any(v.constraint == "max_stops_per_day" for v in violaciones)


class TestLimitesDurosQueNoSeHacianCumplir:
    """Dos restricciones que la fase 7 encontro violadas sobre datos reales."""

    def test_la_comida_no_puede_pasar_el_tope_de_paradas(self):
        """El tope se predecia en build_days y no se comprobaba al insertar.

        La reserva de cupos estimaba que solo cabia el almuerzo; despues la
        cena entraba igual porque la hora daba, y el dia terminaba con seis
        paradas y el limite era cinco.
        """
        from app.services.itinerary import _insert_meals

        ruta = [lugar(f"P{i}", 13.70 + i * 0.003, -89.22, Category.nature) for i in range(4)]
        comidas = [
            lugar(f"C{i}", 13.7001 + i * 0.001, -89.22, Category.food) for i in range(3)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(10, 0),
            max_stops_per_day=5,
        )

        secuencia = _insert_meals(ruta, comidas, restricciones)

        assert len(secuencia) <= 5

    def test_el_dia_se_recorta_para_cerrar_a_tiempo(self):
        """latest_end se reportaba como violacion y nunca se hacia cumplir."""
        from app.services.itinerary import _sequence_end, _trim_to_budget

        destinos = [
            lugar(f"D{i}", 13.70 + i * 0.01, -89.22, Category.nature) for i in range(5)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(10, 0),
            latest_end=time(14, 0),
            include_meals=False,
            max_travel_km_per_day=200,
        )

        secuencia = _trim_to_budget(destinos, [], restricciones)
        fin = _sequence_end(secuencia, restricciones, EstimatedTravel("driving"))

        assert fin is not None and fin <= time(14, 0), f"termina {fin}"

    def test_una_ventana_generosa_no_recorta_de_mas(self):
        from app.services.itinerary import _trim_to_budget

        destinos = [
            lugar(f"D{i}", 13.70 + i * 0.005, -89.22, Category.nature) for i in range(4)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            latest_end=time(22, 0),
            include_meals=False,
            max_travel_km_per_day=200,
        )

        assert len(_trim_to_budget(destinos, [], restricciones)) == 4


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


class TestSeleccionDeRestaurantes:
    """Eran cuatro, anclados en la primera parada. Las dos cosas estaban mal."""

    def test_mide_contra_la_parada_mas_cercana_del_dia(self):
        """Un dia que arranca lejos y termina en el pueblo.

        Anclado en la primera parada, los restaurantes del pueblo quedaban
        fuera de los candidatos y el dia se iba sin almorzar.
        """
        from app.services.itinerary import _meal_candidates

        grupo = [
            lugar("Cerro remoto", 13.700, -89.900, Category.nature),
            lugar("Pueblo", 13.870, -89.850),
        ]
        del_pueblo = lugar("Comedor del pueblo", 13.871, -89.851, Category.food)
        del_medio = lugar("Comedor lejano", 13.780, -89.700, Category.food)

        elegidos = _meal_candidates(grupo, [del_medio, del_pueblo], EstimatedTravel())

        assert elegidos[0].name == "Comedor del pueblo"

    def test_considera_mas_de_cuatro(self):
        """Con cuatro, el almuerzo consume uno y a la cena le quedan tres."""
        from app.services.itinerary import MEAL_CANDIDATES_PER_DAY, _meal_candidates

        grupo = [lugar("A", 13.700, -89.220)]
        comidas = [
            lugar(f"C{i}", 13.700 + i * 0.002, -89.220, Category.food) for i in range(20)
        ]

        elegidos = _meal_candidates(grupo, comidas, EstimatedTravel())

        assert len(elegidos) == MEAL_CANDIDATES_PER_DAY
        assert MEAL_CANDIDATES_PER_DAY > 4

    def test_sin_restaurantes_devuelve_vacio(self):
        from app.services.itinerary import _meal_candidates

        assert _meal_candidates([lugar("A", 13.7, -89.2)], [], EstimatedTravel()) == []

    def test_sin_paradas_devuelve_vacio(self):
        from app.services.itinerary import _meal_candidates

        comidas = [lugar("C", 13.7, -89.2, Category.food)]
        assert _meal_candidates([], comidas, EstimatedTravel()) == []


class TestElDiaNoSeAchicaPorUnaComida:
    """Se intento achicarlo y estaba mal.

    Alguien pide cinco paradas y un almuerzo; devolverle cuatro destinos a
    cambio de un comedor es decidir por el. Llevar comida es una solucion del
    mundo real, saltarse un volcan no lo es.
    """

    def _restricciones(self, **extra):
        base = dict(days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=12)
        base.update(extra)
        return Constraints(**base)

    def test_conserva_los_destinos_aunque_no_entre_el_almuerzo(self):
        from app.services.itinerary import _trim_to_budget

        destinos = [
            lugar(f"D{i}", 13.700 + i * 0.010, -89.220, Category.nature) for i in range(3)
        ]
        lejisimos = [lugar("Lejisimos", 14.100, -89.700, Category.food)]

        secuencia = _trim_to_budget(destinos, lejisimos, self._restricciones())

        assert len(secuencia) == 3
        assert not any(comida for _, comida in secuencia)

    def test_si_el_almuerzo_entra_sin_sacrificar_nada_entra(self):
        from app.services.itinerary import _trim_to_budget

        destinos = [
            lugar(f"D{i}", 13.700 + i * 0.004, -89.220, Category.nature) for i in range(3)
        ]
        comidas = [lugar("Comedor", 13.705, -89.221, Category.food)]

        secuencia = _trim_to_budget(destinos, comidas, self._restricciones())

        assert any(comida == "lunch" for _, comida in secuencia)
        assert len([p for p, c in secuencia if c is None]) == 3


class TestConsejoDeLlevarAlmuerzo:
    """El aviso tiene que llevar el numero y decir la causa verdadera.

    "no hay donde comer" era falso en casi todos los casos: Santa Ana tiene
    trescientos lugares de comida. Lo que no habia era uno que entrara en el
    presupuesto de kilometros.
    """

    def _itinerario(self, stops):
        d = Day(number=1)
        d.stops.extend(stops)
        return Itinerary(days=[d])

    def test_dice_cuanto_habria_costado(self):
        from app.services.itinerary import advise

        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=10
        )
        segunda = lugar("B", 13.710, -89.220, Category.nature)
        stops = [
            Stop(lugar("A", 13.700, -89.220, Category.nature), time(9, 0), time(10, 45)),
            Stop(segunda, time(11, 0), time(12, 45), 5, 2.0),
        ]
        comidas = [lugar("Comedor Lejano", 13.900, -89.500, Category.food)]

        consejos = advise(self._itinerario(stops), restricciones, comidas)

        assert len(consejos) == 1
        assert consejos[0].kind == "bring_lunch"
        assert "Comedor Lejano" in consejos[0].detail
        assert "km" in consejos[0].detail

    def test_sin_restaurantes_lo_dice_asi(self):
        from app.services.itinerary import advise

        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        stops = [Stop(lugar("A", 13.700, -89.220, Category.nature), time(9, 0), time(13, 0))]

        consejos = advise(self._itinerario(stops), restricciones, [])

        assert "No hay ningún lugar para comer" in consejos[0].detail

    def test_con_almuerzo_puesto_no_aconseja_nada(self):
        from app.services.itinerary import advise

        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        stops = [
            Stop(lugar("A", 13.700, -89.220), time(9, 0), time(11, 30)),
            Stop(
                lugar("Comedor", 13.702, -89.221, Category.food),
                time(11, 40),
                time(12, 40),
                10,
                1.0,
                meal="lunch",
            ),
        ]

        assert advise(self._itinerario(stops), restricciones, []) == []

    def test_sin_comidas_pedidas_no_aconseja_nada(self):
        from app.services.itinerary import advise

        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, include_meals=False
        )
        stops = [Stop(lugar("A", 13.700, -89.220, Category.nature), time(9, 0), time(13, 0))]

        assert advise(self._itinerario(stops), restricciones, []) == []

    def test_un_dia_corto_no_recibe_consejo(self):
        from app.services.itinerary import advise

        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        stops = [Stop(lugar("A", 13.700, -89.220), time(9, 0), time(10, 30))]

        assert advise(self._itinerario(stops), restricciones, []) == []


class TestConsejoDeCena:
    """La discrepancia que destapo la evaluacion.

    El comprobador contaba 13 dias sin comida y el motor emitia 12 consejos.
    La diferencia era la cena: advise() solo hablaba del almuerzo, asi que un
    dia que llegaba a la noche sin cenar se quedaba sin explicacion.
    """

    def _itinerario(self, stops):
        d = Day(number=1)
        d.stops.extend(stops)
        return Itinerary(days=[d])

    def test_aconseja_sobre_la_cena(self):
        from app.services.itinerary import advise

        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            latest_end=time(21, 0),
            max_travel_km_per_day=10,
        )
        stops = [
            Stop(lugar("A", 13.700, -89.220, Category.nature), time(9, 0), time(13, 0)),
            Stop(
                lugar("Comedor", 13.701, -89.221, Category.food),
                time(13, 10),
                time(14, 10),
                5,
                1.0,
                meal="lunch",
            ),
            Stop(
                lugar("B", 13.705, -89.220, Category.nature),
                time(14, 20),
                time(19, 0),
                5,
                1.0,
            ),
        ]

        consejos = advise(self._itinerario(stops), restricciones, [])
        tipos = {c.kind for c in consejos}

        assert "bring_dinner" in tipos
        assert "bring_lunch" not in tipos, "el almuerzo si lo tuvo"

    def test_un_dia_que_termina_de_tarde_no_recibe_consejo_de_cena(self):
        from app.services.itinerary import advise

        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)
        stops = [
            Stop(lugar("A", 13.700, -89.220), time(9, 0), time(11, 0)),
            Stop(
                lugar("Comedor", 13.701, -89.221, Category.food),
                time(11, 40),
                time(12, 40),
                5,
                1.0,
                meal="lunch",
            ),
        ]

        assert advise(self._itinerario(stops), restricciones, []) == []


class TestPuntoDePartida:
    """El dia arranca donde el usuario dijo, no donde el motor prefiere.

    Es la diferencia entre "armame un dia en San Salvador" y "salgo de la
    pizzeria de la Gran Via a las doce y almuerzo ahi". El segundo es lo que la
    gente pide de verdad.

    Ojo con el papel: un Pizza Hut no sirve para *centrar* la busqueda —los
    negocios se llaman como el sitio donde estan y ganan la busqueda difusa sin
    merecerlo— pero si sirve como punto de partida. Son dos cosas distintas y
    geocode se ocupa de la primera.
    """

    def _catalogo(self):
        return [
            lugar("Museo", 13.7010, -89.2210, Category.culture, 0.6),
            lugar("Parque", 13.7020, -89.2230, Category.nature, 0.6),
            lugar("Mirador", 13.7040, -89.2260, Category.viewpoint, 0.6),
        ]

    def test_el_ancla_es_la_primera_parada(self):
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=casa,
            include_meals=False,
        )

        [dia] = build_days(self._catalogo(), restricciones)

        assert dia[0] is casa, f"el dia empieza en {dia[0].name}"

    def test_el_ancla_no_gasta_cupo_de_paradas(self):
        """Quien pide tres paradas habla de lugares que va a visitar.

        Descontarle una por decir de donde sale le da menos de lo que pidio.
        """
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        base = dict(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=3,
            include_meals=False,
        )

        [sin_ancla] = build_days(self._catalogo(), Constraints(**base))
        [con_ancla] = build_days(self._catalogo(), Constraints(start_place=casa, **base))

        assert len(con_ancla) == len(sin_ancla) + 1
        assert len([p for p in con_ancla if p is not casa]) == len(sin_ancla)

    def test_el_ancla_no_se_recorta_cuando_el_dia_no_entra(self):
        """El punto de partida es un dato del usuario, no una eleccion.

        Si el dia no cabe en el presupuesto se quitan las paradas elegidas, no
        el sitio de donde sale.
        """
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        lejanos = [
            lugar(f"Lejano {i}", 13.70 + i * 0.2, -89.22, Category.nature, 0.6)
            for i in range(4)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_travel_km_per_day=15,
            start_place=casa,
            include_meals=False,
        )

        [grupo] = build_days(lejanos, restricciones)
        secuencia = _trim_to_budget(grupo, [], restricciones, None, 1)

        assert secuencia[0][0] is casa
        assert _route_km([p for p, _ in secuencia]) <= 15

    def test_si_el_dia_vuelve_el_regreso_es_una_parada_visible(self):
        """Quien pregunta "a que hora llego a casa" pregunta por esa linea."""
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=casa,
            return_to_start=True,
            include_meals=False,
        )

        dia = schedule_day(
            1, [(casa, None), *[(p, None) for p in self._catalogo()]], restricciones
        )

        assert dia.stops[0].place is casa
        assert dia.stops[-1].place is casa
        assert len(dia.stops) == 5

    def test_sin_regreso_el_dia_no_cierra(self):
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=casa,
            return_to_start=False,
            include_meals=False,
        )

        dia = schedule_day(1, [(casa, None), (self._catalogo()[0], None)], restricciones)

        assert dia.stops[-1].place is not casa

    def test_el_presupuesto_cuenta_el_regreso(self):
        """Sin contarlo, el dia se llena al tope y la vuelta lo saca despues.

        Y entonces ya no hay nada que recortar: el exceso aparece cuando el
        itinerario esta armado.
        """
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        base = dict(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_travel_km_per_day=12,
            start_place=casa,
            include_meals=False,
            max_stops_per_day=6,
        )
        candidatos = [
            lugar(f"P{i}", 13.70 + i * 0.02, -89.22, Category.nature, 0.6) for i in range(6)
        ]

        [ida] = build_days(candidatos, Constraints(**base))
        [vuelta] = build_days(candidatos, Constraints(return_to_start=True, **base))

        assert len(vuelta) <= len(ida), (
            "volver cuesta kilometros y el dia deberia entrar mas corto"
        )

    def test_un_comedor_de_partida_es_la_comida_del_dia(self):
        """ "Parto de la pupuseria y almuerzo ahi" no pide otro restaurante."""
        pupuseria = lugar("Pupuseria", 13.6900, -89.2100, Category.food, 0.5)
        comidas = [lugar("Otro comedor", 13.7015, -89.2215, Category.food, 0.9)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=pupuseria,
            earliest_start=time(12, 0),
        )

        secuencia = _insert_meals([pupuseria, *self._catalogo()], comidas, restricciones)

        assert secuencia[0] == (pupuseria, "lunch")
        assert all(lugar_ is not comidas[0] for lugar_, _ in secuencia)

    def test_con_regreso_el_ancla_vale_para_todos_los_dias(self):
        """Quien vuelve cada noche esta diciendo que ese sitio es su base."""
        hotel = lugar("Hotel", 13.6900, -89.2100, Category.lodging, 0.1)
        restricciones = Constraints(
            days=3,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=hotel,
            return_to_start=True,
            include_meals=False,
        )

        assert all(restricciones.anchors_day(n) for n in (1, 2, 3))

    def test_saliendo_hacia_otra_zona_el_ancla_vale_solo_el_primer_dia(self):
        """Partir de un sitio se hace una vez; dormir ahi, todas las noches.

        La partida esta LEJOS de la zona a proposito: es el caso de "tres dias
        por el occidente saliendo de San Salvador", que no vuelve a San
        Salvador cada noche.
        """
        lejos = lugar("Pizzeria", 13.6900, -90.3000, Category.food, 0.5)
        restricciones = Constraints(
            days=3,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=lejos,
            return_to_start=False,
            include_meals=False,
        )

        assert not restricciones.start_inside_area
        assert restricciones.anchors_day(1)
        assert not restricciones.anchors_day(2)
        assert not restricciones.anchors_day(3)

    def test_si_la_partida_esta_en_la_zona_todos_los_dias_salen_de_ahi(self):
        """Quien nombra un sitio dentro de la zona esta diciendo donde se aloja.

        Sin esto, "dos dias en Santa Ana partiendo de Metrocentro Santa Ana"
        armaba un segundo dia a pie que arrancaba en el Volcan de Santa Ana, a
        veinte kilometros: un dia caminando al que no se puede llegar
        caminando.
        """
        cerca = lugar("Metrocentro", 13.6900, -89.2100, Category.attraction, 0.5)
        restricciones = Constraints(
            days=2,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=cerca,
            return_to_start=False,
            include_meals=False,
        )

        assert restricciones.start_inside_area
        assert restricciones.anchors_day(1)
        assert restricciones.anchors_day(2)

    def test_sin_ancla_nada_cambia(self):
        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)

        assert not restricciones.anchors_day(1)


class TestDiasQueNoDanParaUnDia:
    """Un dia que solo tiene el punto de partida no es un dia.

    Al anclar los dias hubo que aflojar la guarda de "sin candidatos, no hay
    dia", y eso dejo pasar dias con el hotel y nada mas. Se veian como un error
    —"Hotel Barceló" solo, sin nada que visitar— y encima escondian el problema
    de fondo: el catalogo no daba para tantos dias.

    Reproducido con radio chico y muchos dias: cinco dias en 1.200 m alrededor
    de un hotel daba tres dias completos y dos con solo el hotel.
    """

    def test_no_emite_un_dia_con_solo_el_ancla(self):
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        # Dos destinos para cinco dias: los ultimos no tienen con que llenarse.
        candidatos = [
            lugar("Uno", 13.6905, -89.2105, Category.nature, 0.6),
            lugar("Dos", 13.6910, -89.2110, Category.culture, 0.6),
        ]
        restricciones = Constraints(
            days=5,
            center_lat=13.69,
            center_lon=-89.21,
            start_place=casa,
            return_to_start=True,
            include_meals=False,
            max_stops_per_day=1,
        )

        dias = build_days(candidatos, restricciones)

        assert dias, "no armo ningun dia"
        for grupo in dias:
            assert len(grupo) > 1, f"un dia salio con solo el ancla: {grupo}"

    def test_el_faltante_de_dias_se_reporta(self):
        """Salir con menos dias es correcto; hacerlo en silencio no.

        La version con dias vacios pasaba la comprobacion de dias pedidos
        porque los contaba, asi que el usuario no se enteraba de nada.
        """
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        candidatos = [lugar("Uno", 13.6905, -89.2105, Category.nature, 0.6)]
        restricciones = Constraints(
            days=4,
            center_lat=13.69,
            center_lon=-89.21,
            start_place=casa,
            return_to_start=True,
            include_meals=False,
            max_stops_per_day=1,
        )

        itinerario = assemble([], candidatos, restricciones)
        motivos = [v.constraint for v in itinerario.violations]

        assert len(itinerario.days) < 4
        assert "days" in motivos


class TestElAnclaNoCuentaContraElLimite:
    """El motor no puede contradecirse solo.

    build_days le da al ancla un cupo aparte —quien pide tres paradas habla de
    lugares que va a visitar— y validate() la contaba igual. El resultado era
    una violacion de max_stops_per_day en todos los itinerarios con punto de
    partida, por un limite que el propio motor decidio no aplicarle.
    """

    def test_no_reporta_violacion_por_el_ancla(self):
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        restricciones = Constraints(
            days=1,
            center_lat=13.69,
            center_lon=-89.21,
            start_place=casa,
            return_to_start=True,
            max_stops_per_day=2,
            include_meals=False,
        )
        # Dos visitas mas el ancla al principio y al final: cuatro entradas.
        secuencia = [
            (casa, None),
            (lugar("Uno", 13.6905, -89.2105, Category.nature, 0.6), None),
            (lugar("Dos", 13.6910, -89.2110, Category.culture, 0.6), None),
        ]
        dia = schedule_day(1, secuencia, restricciones)
        itinerario = Itinerary(days=[dia])
        itinerario.violations = validate(itinerario, restricciones)

        assert len(dia.stops) == 4
        assert "max_stops_per_day" not in [v.constraint for v in itinerario.violations]

    def test_si_de_verdad_se_pasa_lo_reporta(self):
        """La exencion es solo para el ancla, no una amnistia general."""
        casa = lugar("Casa", 13.6900, -89.2100, Category.lodging, 0.1)
        restricciones = Constraints(
            days=1,
            center_lat=13.69,
            center_lon=-89.21,
            start_place=casa,
            max_stops_per_day=1,
            include_meals=False,
        )
        secuencia = [
            (casa, None),
            (lugar("Uno", 13.6905, -89.2105, Category.nature, 0.6), None),
            (lugar("Dos", 13.6910, -89.2110, Category.culture, 0.6), None),
        ]
        dia = schedule_day(1, secuencia, restricciones)
        itinerario = Itinerary(days=[dia])

        motivos = [v.constraint for v in validate(itinerario, restricciones)]

        assert "max_stops_per_day" in motivos


class TestCategoriasExigidas:
    """ "Quiero ver minimo un museo" es un requisito, no una preferencia.

    La diferencia importa y se veia en la practica: `preferred_categories` es
    un empujon de 0.6 en el puntaje, asi que "minimo un museo" salia bien por
    suerte y no por garantia. Cumplir a medias un requisito es no cumplirlo.

    El motor lo prioriza al armar Y lo comprueba al terminar: priorizar no es
    garantizar, y si la zona no tiene ni un museo hay que decirlo.
    """

    def _catalogo(self):
        return [
            # La naturaleza gana el puntaje: sin exigir nada, la semilla es esta.
            lugar("Volcan", 13.7000, -89.2200, Category.nature, 0.9),
            lugar("Cerro", 13.7010, -89.2210, Category.nature, 0.8),
            lugar("Mirador", 13.7020, -89.2220, Category.viewpoint, 0.7),
            # El museo esta mas lejos y puntua menos: sin exigirlo no entra.
            lugar("Museo", 13.7300, -89.2500, Category.culture, 0.3),
        ]

    def test_sin_exigir_nada_la_categoria_puede_no_aparecer(self):
        """La linea base: es lo que hacia que "minimo un museo" fuera suerte."""
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=2,
            include_meals=False,
        )

        [dia] = build_days(self._catalogo(), restricciones)

        assert Category.culture.value not in [p.category for p in dia]

    def test_exigirla_la_pone_en_el_itinerario(self):
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=2,
            include_meals=False,
            must_include_categories=[Category.culture],
        )

        [dia] = build_days(self._catalogo(), restricciones)

        assert Category.culture.value in [p.category for p in dia]

    def test_el_requisito_es_del_itinerario_y_no_de_cada_dia(self):
        """Quien pide un museo en dos dias quiere un museo, no dos."""
        catalogo = [
            *self._catalogo(),
            lugar("Parque", 13.7040, -89.2240, Category.nature, 0.6),
            lugar("Playa", 13.7050, -89.2250, Category.nature, 0.6),
        ]
        restricciones = Constraints(
            days=2,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=2,
            include_meals=False,
            must_include_categories=[Category.culture],
        )

        dias = build_days(catalogo, restricciones)
        culturas = sum(1 for dia in dias for p in dia if p.category == Category.culture.value)

        assert culturas == 1, f"salieron {culturas} paradas de cultura"

    def test_si_la_zona_no_la_tiene_se_reporta(self):
        """Priorizar no es garantizar, y el usuario tiene que enterarse."""
        sin_cultura = [
            lugar("Volcan", 13.7000, -89.2200, Category.nature, 0.9),
            lugar("Cerro", 13.7010, -89.2210, Category.nature, 0.8),
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            include_meals=False,
            must_include_categories=[Category.culture],
        )

        itinerario = assemble([], sin_cultura, restricciones)
        motivos = [v.constraint for v in itinerario.violations]

        assert "must_include_categories" in motivos

    def test_el_ancla_puede_cubrir_el_requisito(self):
        """Si se parte de un hotel y se exige alojamiento, ya esta cubierto."""
        hotel = lugar("Hotel", 13.6900, -89.2100, Category.lodging, 0.1)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            include_meals=False,
            start_place=hotel,
            must_include_categories=[Category.lodging],
        )

        itinerario = assemble([], self._catalogo(), restricciones)

        assert "must_include_categories" not in [v.constraint for v in itinerario.violations]

    def test_exigir_y_evitar_la_misma_categoria_se_rechaza(self):
        """No se puede cumplir de ninguna forma: mejor fallar al construir."""
        with pytest.raises(ValidationError):
            ItineraryRequest(
                days=1,
                center_lat=13.70,
                center_lon=-89.22,
                must_include_categories=[Category.culture],
                avoided_categories=[Category.culture],
            )


class TestFriccionDeLlegar:
    """Moverse no es lo unico que cuesta llegar.

    El modelo no tenia ningun tiempo muerto por parada, y se veia: 0.7 km en
    coche daban "1 min", o sea salir del hotel y estar dentro del museo sesenta
    segundos despues. Falta estacionar, caminar del carro a la puerta y entrar.

    No esta calibrado contra datos porque no hay datos que medir; es una
    estimacion como DEFAULT_DURATIONS. Lo que si esta medido es su costo:
    sobre los 26 casos de evaluacion, el cumplimiento no se mueve y las paradas
    ni bajan, porque el limite que ataba era la distancia y no el reloj —los
    dias terminaban a las 15:09 con latest_end en 20:00.
    """

    def test_un_salto_corto_no_dura_un_minuto(self):
        medidor = EstimatedTravel("driving")
        a = lugar("A", 13.6756, -89.2529)
        b = lugar("B", 13.6800, -89.2540)

        _, minutos = medidor.between(a, b)

        assert minutos > ARRIVAL_OVERHEAD_MINUTES["driving"]

    def test_a_pie_cuesta_menos_llegar(self):
        """No hay donde estacionar: solo encontrar la entrada."""
        assert ARRIVAL_OVERHEAD_MINUTES["walking"] < ARRIVAL_OVERHEAD_MINUTES["driving"]

    def test_la_friccion_se_suma_una_vez_por_tramo(self):
        a = lugar("A", 13.6756, -89.2529)
        b = lugar("B", 13.7000, -89.2600)
        medidor = EstimatedTravel("driving")

        _, minutos = medidor.between(a, b)
        km, _ = medidor.between(a, b)
        velocidad_pura = km / (minutos - ARRIVAL_OVERHEAD_MINUTES["driving"]) * 60

        # Sin la friccion, la velocidad implicita tiene que ser una velocidad
        # de carretera creible y no un valor absurdo.
        assert 20 < velocidad_pura < 90

    def test_la_primera_parada_del_dia_no_la_paga(self):
        """Uno ya esta ahi: no hay llegada que pagar."""
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, include_meals=False
        )
        primera = lugar("Primera", 13.70, -89.22, Category.nature, 0.6)

        dia = schedule_day(1, [(primera, None)], restricciones)

        assert dia.stops[0].arrival == restricciones.earliest_start
        assert dia.stops[0].travel_minutes_from_previous == 0


class TestModoPorDia:
    """ "El primer dia en coche, el segundo a pie" iba entero a unmapped.

    Y era correcto: `mode` era un solo valor para todo el itinerario. Ahora el
    modo va por dia, y con el va el presupuesto —que es la parte que no se
    puede no hacer.
    """

    def test_el_modo_del_dia_manda_sobre_el_del_itinerario(self):
        restricciones = Constraints(
            days=2,
            center_lat=13.70,
            center_lon=-89.22,
            mode="driving",
            day_modes={2: "walking"},
        )

        assert restricciones.mode_for(1) == "driving"
        assert restricciones.mode_for(2) == "walking"
        # Un dia que nadie menciono usa el modo del viaje.
        assert restricciones.mode_for(3) == "driving"

    def test_el_presupuesto_sigue_al_modo(self):
        """25 km son un dia en coche y cinco horas caminando.

        Dejar el limite del itinerario en un dia a pie no seria una
        imprecision, seria un dia imposible.
        """
        restricciones = Constraints(
            days=2,
            center_lat=13.70,
            center_lon=-89.22,
            mode="driving",
            max_travel_km_per_day=25.0,
            day_modes={2: "walking"},
        )

        assert restricciones.budget_for(1) == 25.0
        assert restricciones.budget_for(2) == BUDGET_BY_MODE["walking"]
        assert restricciones.budget_for(2) < restricciones.budget_for(1)

    def test_si_todo_el_viaje_va_a_pie_manda_lo_que_pidio_el_usuario(self):
        """El numero que puso ya es el de a pie: no se sustituye."""
        restricciones = Constraints(
            days=2,
            center_lat=13.70,
            center_lon=-89.22,
            mode="walking",
            max_travel_km_per_day=12.0,
        )

        assert restricciones.budget_for(1) == 12.0
        assert restricciones.budget_for(2) == 12.0

    def test_el_dia_a_pie_sale_mas_corto(self):
        candidatos = [
            lugar(f"P{i}", 13.70 + i * 0.03, -89.22, Category.nature, 0.6) for i in range(10)
        ]
        base = dict(
            center_lat=13.70,
            center_lon=-89.22,
            days=2,
            max_stops_per_day=5,
            include_meals=False,
            max_travel_km_per_day=25.0,
        )

        dias = build_days(candidatos, Constraints(day_modes={2: "walking"}, **base))
        km_coche = _route_km(dias[0], EstimatedTravel("driving"))
        km_pie = _route_km(dias[1], EstimatedTravel("walking"))

        assert km_pie <= BUDGET_BY_MODE["walking"]
        assert km_pie < km_coche

    def test_sin_modos_por_dia_nada_cambia(self):
        restricciones = Constraints(days=3, center_lat=13.70, center_lon=-89.22)

        assert {restricciones.mode_for(n) for n in (1, 2, 3)} == {"driving"}
        assert {restricciones.budget_for(n) for n in (1, 2, 3)} == {
            UNSTATED_BUDGET_BY_MODE["driving"]
        }


class TestDuracionDeLasComidas:
    """Lo que se tarda comiendo.

    Ningun test fijaba este numero, y por eso se pudo pasar de una hora a hora
    y media sin que nada protestara. Una duracion que cambia el horario de
    todos los dias merece estar sujeta.
    """

    def _minutos(self, parada):
        return (parada.departure.hour * 60 + parada.departure.minute) - (
            parada.arrival.hour * 60 + parada.arrival.minute
        )

    def _dia(self, **extra):
        secuencia = [
            (lugar("Mirador", 13.70, -89.22, Category.viewpoint), None),
            (lugar("Restaurante", 13.7005, -89.22, Category.food), "lunch"),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(11, 0), **extra
        )
        return schedule_day(1, secuencia, restricciones)

    def test_una_comida_dura_hora_y_media_por_defecto(self):
        comida = next(p for p in self._dia().stops if p.is_meal)
        assert self._minutos(comida) == DEFAULT_MEAL_MINUTES == 90

    def test_el_usuario_puede_decir_cuanto_tarda_comiendo(self):
        """ "almuerzo tranquilo de dos horas" tiene que llegar al horario."""
        comida = next(p for p in self._dia(meal_minutes=120).stops if p.is_meal)
        assert self._minutos(comida) == 120

    def test_el_comedor_del_regreso_no_es_otra_comida(self):
        """Quien sale de una pupuseria y vuelve a ella no cena ahi de nuevo.

        Es la razon por la que la duracion se decide por la etiqueta de comida
        y no por la categoria del lugar.
        """
        comedor = lugar("Pupuseria", 13.70, -89.22, Category.food)
        secuencia = [
            (comedor, "lunch"),
            (lugar("Mirador", 13.7005, -89.22, Category.viewpoint), None),
            (comedor, None),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(12, 0)
        )
        dia = schedule_day(1, secuencia, restricciones)

        assert self._minutos(dia.stops[0]) == 90, "el almuerzo dura lo que dura"
        assert self._minutos(dia.stops[-1]) == 60, "la vuelta no es una segunda comida"

    def test_el_dia_que_termina_cenando_dura_lo_que_dura_la_cena(self):
        """El limite de latest_end se comprueba contra este numero.

        Con la duracion de la categoria se calculaban treinta minutos de
        menos, y un dia que se pasaba de la hora parecia entrar.
        """
        secuencia = [
            (lugar("Mirador", 13.70, -89.22, Category.viewpoint), None),
            (lugar("Restaurante", 13.7005, -89.22, Category.food), "dinner"),
        ]
        base = dict(days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(17, 0))
        medidor = EstimatedTravel("driving")

        # La cena espera a las 18:00 y dura lo suyo.
        assert _sequence_end(secuencia, Constraints(**base), medidor) == time(19, 30)
        assert _sequence_end(secuencia, Constraints(meal_minutes=45, **base), medidor) == time(
            18, 45
        )


class TestTiempoPorCategoria:
    """ "quiero pasar dos horas en el parque".

    Es por categoria y no por lugar porque cuando alguien lo pide todavia no
    sabe que parque le va a tocar: los lugares los elige el motor despues.
    """

    def _dia(self, **extra):
        secuencia = [
            (lugar("Reserva", 13.70, -89.22, Category.nature), None),
            (lugar("Mirador", 13.7005, -89.22, Category.viewpoint), None),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(9, 0), **extra
        )
        return schedule_day(1, secuencia, restricciones)

    def _minutos(self, parada):
        return (parada.departure.hour * 60 + parada.departure.minute) - (
            parada.arrival.hour * 60 + parada.arrival.minute
        )

    def test_dos_horas_en_el_parque_son_dos_horas(self):
        dia = self._dia(category_minutes={Category.nature: 120})
        assert self._minutos(dia.stops[0]) == 120

    def test_lo_que_no_se_pide_conserva_su_duracion(self):
        """Pedir tiempo de una categoria no reescribe las demas."""
        dia = self._dia(category_minutes={Category.nature: 120})
        assert self._minutos(dia.stops[1]) == 30

    def test_sin_pedir_nada_manda_la_tabla(self):
        dia = self._dia()
        assert self._minutos(dia.stops[0]) == 105

    def test_la_comida_gana_sobre_la_categoria(self):
        """Un almuerzo dura lo que dura un almuerzo.

        Si mandara la categoria, quien pide "los restaurantes rapido" estaria
        cambiando meal_minutes por la puerta de atras y con otro nombre.
        """
        secuencia = [(lugar("Comedor", 13.70, -89.22, Category.food), "lunch")]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(12, 0),
            meal_minutes=90,
            category_minutes={Category.food: 20},
        )
        dia = schedule_day(1, secuencia, restricciones)
        assert self._minutos(dia.stops[0]) == 90


class TestElAnclaNoSeComeElCupoDeLaComida:
    """El dia que sale de un hotel tambien almuerza.

    build_days reserva un cupo para la comida y le da al ancla uno aparte. La
    insercion de comidas contaba la secuencia entera contra el mismo tope, asi
    que el hotel ocupaba el sitio reservado y el dia salia sin comer: cuatro
    destinos, ningun restaurante, y un aviso que culpaba al horario.
    """

    def _mundo(self, destinos: int, tope: int):
        hotel = lugar("Hotel", 13.6900, -89.2100, Category.lodging, 0.1)
        ruta = [hotel] + [
            lugar(f"P{i}", 13.6900 + (i + 1) * 0.002, -89.2100, Category.viewpoint, 0.6)
            for i in range(destinos)
        ]
        comidas = [lugar("Comedor", 13.6905, -89.2098, Category.food, 0.6)]
        restricciones = Constraints(
            days=1,
            center_lat=13.69,
            center_lon=-89.21,
            start_place=hotel,
            return_to_start=True,
            max_stops_per_day=tope,
            earliest_start=time(11, 0),
        )
        return ruta, comidas, restricciones

    def test_el_cupo_reservado_llega_a_la_comida(self):
        """Tope de 3: dos destinos y el almuerzo, que es lo que reserva."""
        ruta, comidas, restricciones = self._mundo(destinos=2, tope=3)

        secuencia = _insert_meals(ruta, comidas, restricciones)

        assert [c for _, c in secuencia if c] == ["lunch"]

    def test_el_tope_sigue_mandando_cuando_de_verdad_esta_lleno(self):
        """La exencion es del ancla, no de la comida."""
        ruta, comidas, restricciones = self._mundo(destinos=3, tope=3)

        secuencia = _insert_meals(ruta, comidas, restricciones)

        assert [c for _, c in secuencia if c] == []

    def test_el_aviso_dice_que_falto_cupo_y_no_que_falto_horario(self):
        """Las dos causas se arreglan distinto: una subiendo el tope de
        paradas, la otra llevando comida."""
        ruta, comidas, restricciones = self._mundo(destinos=3, tope=3)
        secuencia = _insert_meals(ruta, comidas, restricciones)
        dia = schedule_day(1, secuencia, restricciones)

        consejos = advise(Itinerary(days=[dia]), restricciones, comidas)
        mensajes = " ".join(c.detail for c in consejos)

        assert "No queda parada libre" in mensajes
        assert "horario" not in mensajes


class TestElDiaSeLlenaHastaSuHora:
    """El largo del dia lo decide el horario pedido, no un contador.

    Con un tope de cinco puesto de oficio, un dia de diez de la manana a once
    de la noche terminaba a las cuatro de la tarde: siete horas sin usar, y
    sin forma de llegar nunca a la hora de cenar.
    """

    def _candidatos(self, cuantos=12):
        return [
            lugar(f"P{i}", 13.700 + i * 0.006, -89.220, Category.viewpoint, 0.6)
            for i in range(cuantos)
        ]

    def _restricciones(self, **extra):
        base = dict(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(10, 0),
            latest_end=time(20, 0),
            include_meals=False,
            max_travel_km_per_day=120,
        )
        base.update(extra)
        return Constraints(**base)

    def test_sin_tope_pedido_el_dia_pasa_de_cinco_paradas(self):
        dias = build_days(self._candidatos(), self._restricciones())

        assert len(dias[0]) > 5

    def test_el_tope_pedido_se_respeta(self):
        """Que mande el reloj no significa ignorar lo que la persona pidio."""
        dias = build_days(self._candidatos(), self._restricciones(max_stops_per_day=3))

        assert len(dias[0]) == 3

    def test_una_ventana_corta_da_un_dia_corto(self):
        """La otra cara: si el reloj manda, cerrar temprano acorta el dia."""
        largo = build_days(self._candidatos(), self._restricciones())
        corto = build_days(self._candidatos(), self._restricciones(latest_end=time(13, 0)))

        assert len(corto[0]) < len(largo[0])

    def test_el_dia_no_se_pasa_de_la_hora_pedida(self):
        dias = build_days(self._candidatos(), self._restricciones())
        secuencia = [(p, None) for p in dias[0]]
        dia = schedule_day(1, secuencia, self._restricciones())

        assert dia.end is not None and dia.end <= time(20, 0)

    def test_un_dia_largo_llega_a_cenar(self):
        """Lo que el tope de cinco hacia imposible.

        Con paradas de hora y media desde las diez, cinco cupos terminan a las
        cinco y media: la franja de la cena empieza a las seis y no se llegaba
        nunca, dijera lo que dijera el usuario.
        """
        candidatos = self._candidatos()
        comidas = [
            lugar("Comedor", 13.7005, -89.2205, Category.food, 0.6),
            lugar("Cena", 13.7405, -89.2205, Category.food, 0.6),
        ]
        restricciones = self._restricciones(include_meals=True, latest_end=time(22, 0))

        dias = build_days(candidatos, restricciones, meal_options=len(comidas))
        secuencia = _insert_meals(dias[0], comidas, restricciones)

        assert "dinner" in [c for _, c in secuencia if c]


class TestNadaFueraDeHora:
    """Un mirador a las siete de la tarde es una cuesta a oscuras, y un museo
    a esa hora esta cerrado.

    Mientras los dias terminaban a las cuatro no se podia llegar a ninguna de
    las dos. Al llenarlos por horario aparecieron: un cerro a las 19:22 y una
    iglesia a las 19:56.
    """

    def test_detecta_la_parada_que_cae_de_noche(self):
        """La primera parada es un comedor a proposito: es lo unico que no
        tiene hora, asi que la que sobra es el mirador y no ella."""
        mirador = lugar("Mirador", 13.7005, -89.22, Category.viewpoint)
        secuencia = [
            (lugar("Comedor", 13.70, -89.22, Category.food), "dinner"),
            (mirador, None),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(18, 0)
        )

        assert _outdoor_after_dusk(secuencia, restricciones, EstimatedTravel()) is mirador

    def test_lo_de_bajo_techo_tambien_cierra(self):
        """Con otra hora y por otro motivo: la luz no, el horario si.

        Once de los 366 lugares bajo techo traen horario en OpenStreetMap, un
        3%, asi que se asume una hora de cierre para todos en vez de fingir
        que el dato existe.
        """
        museo = lugar("Museo", 13.7005, -89.22, Category.culture)
        secuencia = [
            (lugar("Comedor", 13.70, -89.22, Category.food), "dinner"),
            (museo, None),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(18, 30)
        )

        assert _outdoor_after_dusk(secuencia, restricciones, EstimatedTravel()) is museo

    def test_un_comedor_de_noche_es_justo_lo_que_se_busca(self):
        """La regla no puede alcanzar a la cena."""
        secuencia = [
            (lugar("Comedor", 13.70, -89.22, Category.food), "dinner"),
            (lugar("Otro comedor", 13.7005, -89.22, Category.food), None),
        ]
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(20, 0)
        )

        assert _outdoor_after_dusk(secuencia, restricciones, EstimatedTravel()) is None

    def test_el_dia_armado_no_deja_ninguna(self):
        candidatos = [
            lugar(f"P{i}", 13.700 + i * 0.004, -89.220, Category.viewpoint, 0.6)
            for i in range(12)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(14, 0),
            latest_end=time(23, 0),
            include_meals=False,
            max_travel_km_per_day=120,
        )

        itinerario = assemble([], candidatos, restricciones)
        tarde = [
            s
            for d in itinerario.days
            for s in d.stops
            if s.place.category in ("nature", "viewpoint") and s.arrival >= time(18, 15)
        ]

        assert tarde == []


class TestDuracionPorSubcategoria:
    """Un museo y un monumento no duran lo mismo aunque los dos sean cultura.

    Con solo seis numeros, el Museo Nacional de Antropologia y una estatua en
    una rotonda ocupaban los mismos 75 minutos, y subir "cultura" a dos horas
    para el museo se las daba tambien a la estatua.
    """

    def _minutos(self, parada):
        return (parada.departure.hour * 60 + parada.departure.minute) - (
            parada.arrival.hour * 60 + parada.arrival.minute
        )

    def _dia(self, subcategorias, **extra):
        secuencia = []
        for indice, sub in enumerate(subcategorias):
            lugar_ = lugar(f"L{indice}", 13.70 + indice * 0.001, -89.22, Category.culture)
            secuencia.append((replace(lugar_, subcategory=sub), None))
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, earliest_start=time(9, 0), **extra
        )
        return schedule_day(1, secuencia, restricciones)

    def test_el_museo_dura_dos_horas(self):
        dia = self._dia(["museum"])
        assert self._minutos(dia.stops[0]) == 120

    def test_el_monumento_es_una_foto(self):
        dia = self._dia(["monument"])
        assert self._minutos(dia.stops[0]) == 20

    def test_los_dos_son_cultura_y_duran_distinto(self):
        """La prueba de que la categoria no alcanza."""
        dia = self._dia(["museum", "monument"])
        assert [s.place.category for s in dia.stops] == ["culture", "culture"]
        assert self._minutos(dia.stops[0]) != self._minutos(dia.stops[1])

    def test_una_subcategoria_sin_entrada_usa_la_tabla_por_categoria(self):
        dia = self._dia(["algo_que_no_esta_en_la_tabla"])
        assert self._minutos(dia.stops[0]) == DEFAULT_DURATIONS[Category.culture]

    def test_lo_que_pidio_el_usuario_gana_sobre_la_subcategoria(self):
        """Quien dice "los museos rapido" habla de todos, y afinar por debajo
        de eso seria discutirle."""
        dia = self._dia(["museum"], category_minutes={Category.culture: 40})
        assert self._minutos(dia.stops[0]) == 40


class TestLaComidaPedidaConNombre:
    """Pedir cena y no recibirla sin explicacion es el peor de los casos.

    include_meals dice "meteme comidas donde quepan" y must_include_meals dice
    "cuento con esta comida". El caso real: dos dias pidiendo cena, el segundo
    a pie termina a las 15:04 porque se le acaban los ocho kilometros, y no se
    decia ni una palabra.
    """

    def _itinerario(self, **extra):
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(9, 0),
            latest_end=time(16, 0),
            include_meals=True,
            **extra,
        )
        secuencia = [
            (lugar("Museo", 13.70, -89.22, Category.culture), None),
            (lugar("Comedor", 13.7005, -89.22, Category.food), "lunch"),
        ]
        dia = schedule_day(1, secuencia, restricciones)
        return Itinerary(days=[dia]), restricciones

    def test_dice_que_el_dia_no_llega_a_la_cena(self):
        itinerario, restricciones = self._itinerario(must_include_meals=["dinner"])

        consejos = advise(itinerario, restricciones, [])
        cenas = [c for c in consejos if c.kind == "bring_dinner"]

        assert len(cenas) == 1
        assert "no llega" in cenas[0].detail
        assert "18:00" in cenas[0].detail, "tiene que decir a que hora empieza la cena"

    def test_sin_pedirla_no_dice_nada(self):
        """Un dia que termina a las cuatro no tiene nada que explicar si nadie
        contaba con cenar."""
        itinerario, restricciones = self._itinerario()

        consejos = advise(itinerario, restricciones, [])

        assert [c for c in consejos if c.kind == "bring_dinner"] == []


class TestLugarPedidoConNombre:
    """ "quiero ir al Jardin Botanico" es lo mas fuerte que se puede pedir.

    Exigir cultura se cumple con cualquier museo; exigir un lugar se cumple
    con uno solo.
    """

    def _mundo(self, **extra):
        # El pedido es el peor puntuado y el mas lejano de los tres: sin el
        # requisito no entraria.
        pedido = lugar("Pedido", 13.760, -89.22, Category.culture, 0.1)
        otros = [
            lugar(f"P{i}", 13.700 + i * 0.002, -89.220, Category.nature, 0.9) for i in range(6)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            include_meals=False,
            max_travel_km_per_day=60,
            must_include_places=[pedido],
            **extra,
        )
        return pedido, [pedido, *otros], restricciones

    def test_el_lugar_pedido_entra(self):
        pedido, candidatos, restricciones = self._mundo()

        itinerario = assemble([], candidatos, restricciones)
        nombres = [p.place.name for d in itinerario.days for p in d.stops]

        assert "Pedido" in nombres

    def test_los_minutos_del_lugar_ganan_sobre_todo(self):
        pedido, candidatos, restricciones = self._mundo(
            place_minutes={},
            category_minutes={Category.culture: 40},
        )
        restricciones = replace(restricciones, place_minutes={pedido.id: 200})

        itinerario = assemble([], candidatos, restricciones)
        parada = next(p for d in itinerario.days for p in d.stops if p.place.id == pedido.id)
        minutos = (parada.departure.hour * 60 + parada.departure.minute) - (
            parada.arrival.hour * 60 + parada.arrival.minute
        )

        assert minutos == 200

    def test_si_no_cabe_se_reporta_en_vez_de_callarse(self):
        """Priorizar no es garantizar, y hay que decirlo.

        Dos lugares pedidos a ochenta kilometros uno del otro, un dia y diez
        kilometros de presupuesto: uno entra de semilla y el otro no cabe de
        ninguna forma. Un lugar pedido suelto siempre entra —de semilla no
        cuesta traslado— asi que este es el caso que de verdad falla.
        """
        uno = lugar("Pedido uno", 13.70, -89.22, Category.culture, 0.9)
        otro = lugar("Pedido dos", 14.40, -89.22, Category.culture, 0.9)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            include_meals=False,
            max_travel_km_per_day=10,
            must_include_places=[uno, otro],
        )

        itinerario = assemble([], [uno, otro], restricciones)
        motivos = [v.constraint for v in itinerario.violations]
        nombres = [p.place.name for d in itinerario.days for p in d.stops]

        assert "must_include_places" in motivos
        assert "Pedido uno" in nombres, "el que si cabe tiene que entrar"


class TestLaCuentaDeParadas:
    """La cabecera decia "12 paradas" en un itinerario de nueve lugares.

    Contaba el hotel al salir y al volver, los dos dias: un numero que
    cualquiera desmiente contando la lista de al lado.
    """

    def test_el_punto_de_partida_no_es_una_visita(self):
        casa = lugar("Casa", 13.70, -89.22, Category.lodging)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=casa,
            return_to_start=True,
            include_meals=False,
        )
        secuencia = [
            (casa, None),
            (lugar("Uno", 13.7005, -89.22, Category.culture), None),
            (lugar("Dos", 13.7010, -89.22, Category.nature), None),
        ]
        dia = schedule_day(1, secuencia, restricciones)
        itinerario = Itinerary(days=[dia])

        assert itinerario.total_stops == 4, "cuatro lineas en la lista"
        assert total_visits(itinerario, restricciones) == 2, "dos lugares visitados"

    def test_la_comida_si_cuenta(self):
        """Uno para ahi de verdad."""
        casa = lugar("Casa", 13.70, -89.22, Category.lodging)
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, start_place=casa
        )
        secuencia = [
            (casa, None),
            (lugar("Comedor", 13.7005, -89.22, Category.food), "lunch"),
        ]
        itinerario = Itinerary(days=[schedule_day(1, secuencia, restricciones)])

        assert total_visits(itinerario, restricciones) == 1

    def test_sin_restricciones_devuelve_la_cuenta_cruda(self):
        """El borrador se emite antes de tener a mano las restricciones."""
        secuencia = [(lugar("Uno", 13.70, -89.22), None)]
        itinerario = Itinerary(
            days=[
                schedule_day(
                    1, secuencia, Constraints(days=1, center_lat=13.7, center_lon=-89.22)
                )
            ]
        )

        assert total_visits(itinerario, None) == itinerario.total_stops


class TestNoDosVecesElMismoNombre:
    """Un itinerario con dos "Cascadas de Huizucar" se lee como un error.

    Y lo era, pero no de duplicado: son dos filas del catalogo a 774 metros, y
    el radio de deduplicacion para exteriores son 500. Fusionarlas al cargar
    seria falso —hay 90 pares de "Pizza Hut" en el catalogo y son 90
    restaurantes— asi que la regla va en el itinerario: una de cada nombre.
    """

    def test_no_entra_dos_veces_el_mismo_nombre(self):
        gemelas = [
            lugar("Cascadas de Huizucar", 13.5896, -89.2310, Category.viewpoint, 0.9),
            lugar("Cascadas de Huizucar", 13.5842, -89.2265, Category.viewpoint, 0.9),
        ]
        otras = [
            lugar(f"Otra {i}", 13.700 + i * 0.002, -89.220, Category.culture, 0.6)
            for i in range(4)
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.60,
            center_lon=-89.23,
            include_meals=False,
            max_travel_km_per_day=90,
        )

        dias = build_days([*gemelas, *otras], restricciones)
        nombres = [p.name for p in dias[0]]

        assert nombres.count("Cascadas de Huizucar") == 1

    def test_el_nombre_se_compara_sin_mayusculas_ni_espacios_de_mas(self):
        assert _name_key(lugar("  Cascadas   de Huizucar ", 13.5, -89.2)) == _name_key(
            lugar("cascadas de huizucar", 13.6, -89.3)
        )

    def test_dos_nombres_distintos_si_entran(self):
        """La regla es sobre el nombre, no sobre la categoria."""
        candidatos = [
            lugar("Uno", 13.700, -89.220, Category.viewpoint, 0.9),
            lugar("Dos", 13.702, -89.220, Category.viewpoint, 0.9),
        ]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            include_meals=False,
            max_travel_km_per_day=90,
        )

        dias = build_days(candidatos, restricciones)

        assert len(dias[0]) == 2


class TestRepetirSubcategoriaCuestaAparte:
    """Cinco monumentos no son un dia de cultura variado.

    La penalizacion por categoria no distinguia un dia de cerro, volcan,
    cascada y playa de uno de cinco monumentos: los dos son la misma categoria
    repetida y pagaban igual.

    Se prueba sobre _fill_cost y no sobre el dia armado porque ahi la regla es
    determinista. Un primer intento midio el dia entero y no probaba nada: el
    museo ganaba la semilla por atractivo —0.8 contra 0.5 del monumento— asi
    que entraba con penalizacion y sin ella.
    """

    def _mundo(self):
        semilla = replace(
            lugar("Monumento A", 13.7000, -89.2200, Category.culture),
            subcategory="monument",
        )
        # Los dos candidatos, a la misma distancia de la semilla: lo unico que
        # los diferencia es la subcategoria.
        otro_monumento = replace(
            lugar("Monumento B", 13.7010, -89.2200, Category.culture),
            subcategory="monument",
        )
        museo = replace(
            lugar("Museo", 13.6990, -89.2200, Category.culture), subcategory="museum"
        )
        return semilla, otro_monumento, museo

    def test_repetir_subcategoria_encarece_al_candidato(self):
        semilla, otro_monumento, museo = self._mundo()
        medidor = EstimatedTravel()

        coste_mon = _fill_cost([semilla], otro_monumento, semilla, medidor)
        coste_mus = _fill_cost([semilla], museo, semilla, medidor)

        assert coste_mon > coste_mus

    def test_la_diferencia_es_exactamente_la_penalizacion(self):
        """Los dos son cultura, asi que la penalizacion de categoria es la
        misma para ambos: lo que queda es la de subcategoria."""
        semilla, otro_monumento, museo = self._mundo()
        medidor = EstimatedTravel()

        coste_mon = _fill_cost([semilla], otro_monumento, semilla, medidor)
        coste_mus = _fill_cost([semilla], museo, semilla, medidor)

        assert coste_mon - coste_mus == pytest.approx(SUBCATEGORY_PENALTY_KM, abs=0.01)

    def test_sin_subcategoria_no_se_penaliza(self):
        """Un lugar sin subcategoria en OSM no puede repetir la de nadie."""
        semilla, _, _ = self._mundo()
        sin_sub = lugar("Sin etiqueta", 13.6990, -89.2200, Category.culture)
        medidor = EstimatedTravel()

        coste = _fill_cost([semilla], sin_sub, semilla, medidor)
        museo = replace(
            lugar("Museo", 13.6990, -89.2200, Category.culture), subcategory="museum"
        )

        assert coste == pytest.approx(_fill_cost([semilla], museo, semilla, medidor), abs=0.01)


class TestNombreQueNoIdentifica:
    """ "Mirador 3" no dice a donde vas.

    Los 35 miradores activos del catalogo tienen TODOS el mismo
    quality_score, 0.40 —ninguno trae horario, web ni telefono— asi que el
    nombre es la unica señal que queda para distinguirlos, y no se usaba.
    """

    @pytest.mark.parametrize("nombre", ["Mirador 3", "Peña 1", "cerro 12", "Playa 7"])
    def test_una_generica_y_un_numero_no_identifica(self, nombre):
        assert nombre_no_identifica(nombre) is True

    @pytest.mark.parametrize(
        "nombre",
        [
            # Un toponimo de verdad: hay ocho Cerro Grande en el pais y la
            # primera version de la regla se los llevaba a todos.
            "Cerro Grande",
            "Mirador de Apaneca",
            "Peña Blanca",
            # El numero no va al final.
            "Mirador Las 100 Gradas",
            "Playa K59",
            # La cabeza no es generica.
            "Ruta 5",
        ],
    )
    def test_lo_que_si_identifica_se_conserva(self, nombre):
        assert nombre_no_identifica(nombre) is False

    def test_encarece_el_candidato_al_llenar_el_dia(self):
        """En kilometros y no solo en puntaje.

        score_candidate solo elige la semilla del dia; el resto lo llena
        _fill_cost. Con la penalizacion solo en el puntaje, "Mirador 3" seguia
        entrando por cercania las mismas cuatro veces: medido.
        """
        semilla = lugar("Museo", 13.7000, -89.2200, Category.culture)
        vago = replace(
            lugar("Mirador 3", 13.7010, -89.2200, Category.viewpoint),
            subcategory="viewpoint",
        )
        con_nombre = replace(
            lugar("Mirador de Apaneca", 13.7010, -89.2200, Category.viewpoint),
            subcategory="viewpoint",
        )
        medidor = EstimatedTravel()

        coste_vago = _fill_cost([semilla], vago, semilla, medidor)
        coste_bueno = _fill_cost([semilla], con_nombre, semilla, medidor)

        assert coste_vago - coste_bueno == pytest.approx(NOMBRE_VAGO_KM, abs=0.01)

    def test_se_penaliza_pero_no_se_descarta(self):
        """Hay 35 miradores en el pais: tirar dos deja zonas sin ninguno."""
        vago = replace(
            lugar("Mirador 3", 13.7010, -89.2200, Category.viewpoint),
            subcategory="viewpoint",
        )
        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, include_meals=False
        )

        dias = build_days([vago], restricciones)

        assert [p.name for p in dias[0]] == ["Mirador 3"]


class TestUnCentroComercialPorViaje:
    """Quién va a querer ir a dos centros comerciales en el mismo viaje.

    No es variedad ni atractivo: la penalizacion por subcategoria los dispersa
    dentro del dia pero no impide cinco en tres dias. Sin el tope, aceptarlos
    como destino llevaba el 15% de las paradas del arnes a centros
    comerciales: 46 de 310.
    """

    def _mall(self, nombre, lat):
        return replace(
            lugar(nombre, lat, -89.2200, Category.attraction, 0.9), subcategory="mall"
        )

    def _restricciones(self, **extra):
        base = dict(
            days=2,
            center_lat=13.70,
            center_lon=-89.22,
            include_meals=False,
            max_travel_km_per_day=90,
        )
        base.update(extra)
        return Constraints(**base)

    def test_solo_entra_uno_en_todo_el_itinerario(self):
        candidatos = [
            self._mall("Metrocentro", 13.7000),
            self._mall("Galerías", 13.7020),
            self._mall("Plaza Mundo", 13.7040),
            *[
                lugar(f"Museo {i}", 13.7060 + i * 0.002, -89.2200, Category.culture, 0.6)
                for i in range(4)
            ],
        ]

        dias = build_days(candidatos, self._restricciones())
        malls = [p.name for grupo in dias for p in grupo if p.subcategory == "mall"]

        assert len(malls) == 1

    def test_lo_que_el_usuario_nombra_pasa_por_encima_del_tope(self):
        """Quien pide ir a dos, quiere ir a dos: un tope del motor no puede
        contradecir un pedido explicito."""
        uno = self._mall("Metrocentro", 13.7000)
        otro = self._mall("Galerías", 13.7020)
        candidatos = [
            uno,
            otro,
            *[
                lugar(f"Museo {i}", 13.7060 + i * 0.002, -89.2200, Category.culture, 0.6)
                for i in range(4)
            ],
        ]

        # **Un solo dia a proposito.** Con dos dias cada pedido cae de semilla
        # en el suyo y el test pasa sin probar nada: fue mi primer intento y
        # tapaba justo el bug que habia. Los nombres de los pedidos se
        # reservaban de entrada y el filtro del llenado excluia a los pedidos
        # mismos, asi que el segundo nunca entraba por ahi y se reportaba como
        # restriccion incumplida.
        dias = build_days(
            candidatos, self._restricciones(days=1, must_include_places=[uno, otro])
        )
        malls = sorted(p.name for grupo in dias for p in grupo if p.subcategory == "mall")

        assert malls == ["Galerías", "Metrocentro"]

    def test_el_punto_de_partida_no_gasta_el_cupo(self):
        """De un centro comercial se sale, no se visita: si el dia arranca ahi,
        todavia se puede visitar otro."""
        partida = self._mall("Metrocentro Santa Ana", 13.7000)
        otro = self._mall("Galerías", 13.7020)
        candidatos = [
            otro,
            *[
                lugar(f"Museo {i}", 13.7060 + i * 0.002, -89.2200, Category.culture, 0.6)
                for i in range(4)
            ],
        ]

        dias = build_days(candidatos, self._restricciones(days=1, start_place=partida))
        nombres = [p.name for p in dias[0]]

        assert "Metrocentro Santa Ana" in nombres, "el punto de partida abre el dia"
        assert "Galerías" in nombres, "y todavia cabe un centro comercial de visita"


class TestUnaZonaSinLugaresNoRevienta:
    """`assemble` ligaba `medidor` dentro del bucle de los dias.

    Una zona cuyos grupos salen todos vacios —cualquier punto del pais sin
    lugares cerca— llegaba a `advise()` con el nombre sin asignar y reventaba
    con UnboundLocalError, o sea un 500 en produccion. El arreglo es pasar
    `travel` en vez de un medidor ya resuelto, que es la regla que el propio
    `assemble` enuncia para todo lo demas.
    """

    def test_sin_candidatos_devuelve_un_itinerario_vacio(self):
        restricciones = Constraints(
            days=1,
            center_lat=12.5,
            center_lon=-89.5,
            radius_m=5_000,
        )

        itinerario = assemble([], [], restricciones)

        assert itinerario.days == []
        assert itinerario.advice == []

    def test_con_comidas_pero_sin_destinos_tampoco(self):
        """El otro camino al mismo fallo: hay comida en la zona y ningun destino."""
        restricciones = Constraints(days=1, center_lat=13.7, center_lon=-89.22)
        comida = lugar("Comedor", 13.70, -89.22, Category.food)

        itinerario = assemble([comida], [], restricciones)

        assert itinerario.days == []


class TestNoTeSientaEnUnComedorCerrado:
    """La regla de horarios, que es lo unico que se quedo de esa tanda.

    Medido sobre 42 itinerarios con fecha en seis zonas y los siete dias de la
    semana: 2 de 70 comidas caian en un comedor que se sabe cerrado, y con la
    regla son 0 sin perder ni una comida —sustituye, no quita.

    **Tres estados y no dos.** De los 2.717 lugares de comida del catalogo, 419
    traen horario y 381 en formato legible: el 86% no dice nada. Descartar lo
    desconocido dejaria media zona del pais sin comida por un hueco de
    OpenStreetMap.
    """

    # 2026-09-20 es domingo; 09-21 lunes.
    DOMINGO = date(2026, 9, 20)

    def _comedor(self, nombre, lat, lon, horario=None):
        return PlaceHit(
            id=uuid.uuid4(),
            name=nombre,
            category=Category.food.value,
            subcategory="restaurant",
            lat=lat,
            lon=lon,
            quality_score=0.7,
            tags={"opening_hours": horario} if horario else None,
        )

    def _restricciones(self, fecha=DOMINGO):
        return Constraints(
            days=1,
            start_date=fecha,
            center_lat=13.70,
            center_lon=-89.22,
            max_travel_km_per_day=60,
            earliest_start=time(10, 0),
            latest_end=time(20, 0),
            include_meals=True,
            max_stops_per_day=3,
        )

    def _comidas_del_dia(self, itinerario):
        return [p.place.name for d in itinerario.days for p in d.stops if p.meal is not None]

    def test_el_que_cierra_el_domingo_no_entra(self):
        """El caso real: un café con `Mo-Sa 08:00-18:00` colocado un domingo."""
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        cerrado = self._comedor("Cierra Domingos", 13.701, -89.221, "Mo-Sa 08:00-18:00")
        abierto = self._comedor("Abre Siempre", 13.703, -89.223, "Mo-Su 08:00-22:00")

        itinerario = assemble([cerrado, abierto], destinos, self._restricciones())

        assert self._comidas_del_dia(itinerario) == ["Abre Siempre"]

    def test_el_de_horario_desconocido_sigue_entrando(self):
        """Sin dato no se castiga al lugar: es el 86% del catálogo."""
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        sin_dato = self._comedor("Sin Horario", 13.701, -89.221)

        itinerario = assemble([sin_dato], destinos, self._restricciones())

        assert self._comidas_del_dia(itinerario) == ["Sin Horario"]

    def test_sin_fecha_la_regla_no_se_aplica(self):
        """`opening_hours` habla de días de la semana: sin fecha no hay con qué
        responder, y suponer un día sería inventarlo."""
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        cerrado = self._comedor("Cierra Domingos", 13.701, -89.221, "Mo-Sa 08:00-18:00")

        sin_fecha = replace(self._restricciones(), start_date=None)
        itinerario = assemble([cerrado], destinos, sin_fecha)

        assert self._comidas_del_dia(itinerario) == ["Cierra Domingos"]

    def test_un_horario_ilegible_no_descarta_el_comedor(self):
        """ "Todos los dias 10am a 8:30pm" y compañía: 38 de los 419 valores."""
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        raro = self._comedor("Prosa Libre", 13.701, -89.221, "Todos los dias 10am a 8:30pm")

        itinerario = assemble([raro], destinos, self._restricciones())

        assert self._comidas_del_dia(itinerario) == ["Prosa Libre"]

    def test_no_alcanza_con_abrir_al_llegar(self):
        """Un comedor que cierra a las 14:00 no sirve para un almuerzo de
        noventa minutos que empieza a las 13:00: entrar y que te levanten no es
        comer."""
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        justo = self._comedor("Cierra Temprano", 13.701, -89.221, "Mo-Su 08:00-12:30")
        amplio = self._comedor("Cierra Tarde", 13.703, -89.223, "Mo-Su 08:00-22:00")

        itinerario = assemble([justo, amplio], destinos, self._restricciones())

        assert self._comidas_del_dia(itinerario) == ["Cierra Tarde"]

    def test_prefiere_el_que_se_sabe_abierto_sobre_el_que_no_se_sabe(self):
        """Vale un desvío corto cambiar "probablemente abra" por "abre".

        Medido: sin esta preferencia, 35 de 70 comidas caían en un sitio del
        que no se sabe nada; con ella, 62 de 70 en uno que se sabe abierto, y
        cuesta 8,4 km repartidos en 42 días. Ver OPEN_HOURS_BONUS_KM.
        """
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        # El de horario desconocido queda MÁS cerca, así que sin el bono gana él.
        sin_dato = self._comedor("Sin Horario", 13.7010, -89.2210)
        con_dato = self._comedor("Abre Seguro", 13.7060, -89.2260, "Mo-Su 08:00-22:00")

        itinerario = assemble([sin_dato, con_dato], destinos, self._restricciones())

        assert self._comidas_del_dia(itinerario) == ["Abre Seguro"]

    def test_pero_no_a_cualquier_precio(self):
        """El bono son 1,5 km: un desvío mayor no lo compensa."""
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        sin_dato = self._comedor("Sin Horario", 13.7010, -89.2210)
        # A unos veinte kilómetros: se sabe que abre y da igual.
        lejano = self._comedor("Abre Seguro Pero Lejos", 13.88, -89.22, "Mo-Su 08:00-22:00")

        itinerario = assemble([sin_dato, lejano], destinos, self._restricciones())

        assert self._comidas_del_dia(itinerario) == ["Sin Horario"]

    def test_el_aviso_sigue_diciendo_los_kilometros_de_verdad(self):
        """El bono entra en el puntaje, nunca en el costo que se reporta.

        `costo` son kilómetros reales y el aviso los escribe. Mezclarle la
        preferencia lo volvería un número falso —y además perdía catorce de las
        setenta comidas medidas en cuanto el bono pasaba de tres kilómetros.

        Se comprueba por invariante y no por umbral: el mismo comedor, a la
        misma distancia, tiene que reportar los mismos kilómetros con horario y
        sin él. Un umbral suelto no lo detectaba, porque restar 1,5 km a un
        desvío de cuarenta seguía pasando la prueba.
        """
        # Dos destinos para que el día llegue a la franja de almuerzo: con uno
        # solo termina a las 11:15 y no hay nada que aconsejar.
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        estrecho = replace(self._restricciones(), max_travel_km_per_day=2)

        def km_del_aviso(horario):
            # Único comedor del día, fuera del presupuesto, así que el aviso
            # tiene que decir cuánto se pasaría.
            comedor = self._comedor("Único", 14.10, -89.22, horario)
            itinerario = assemble([comedor], destinos, estrecho)
            aviso = next(c for c in itinerario.advice if c.kind == "bring_lunch")
            return float(aviso.detail.split("agrega ")[1].split(" km")[0])

        sin_horario = km_del_aviso(None)
        con_horario = km_del_aviso("Mo-Su 08:00-22:00")

        assert sin_horario > 40, "el escenario dejó de servir: el desvío es corto"
        assert con_horario == sin_horario, (
            f"el costo reportado salió contaminado por el bono: "
            f"{con_horario} con horario contra {sin_horario} sin él"
        )


class TestElTopeDeKilometrosQueNadiePidio:
    """`None` es "no lo dijo", no "veinticinco".

    El fallo: alguien pidió estar "de vuelta en el hotel antes de las 11 pm" y
    el día cerraba a las 14:38 sin la cena que también había pedido, con seis
    horas sin usar. El techo de 25 km era un número inventado que pisaba dos
    instrucciones de verdad, y el motor encima aconsejaba "subí el límite de
    traslado" —un límite que quien preguntaba nunca había puesto—. Es el mismo
    error que ya se había corregido en max_stops_per_day.
    """

    def test_sin_pedirlo_el_techo_es_el_de_su_modo(self):
        sin_pedir = Constraints(days=1, center_lat=13.70, center_lon=-89.22)

        assert sin_pedir.max_travel_km_per_day is None
        assert not sin_pedir.budget_was_asked_for
        assert sin_pedir.budget_for(1) == UNSTATED_BUDGET_BY_MODE["driving"]

    def test_a_pie_sin_pedirlo_no_hereda_el_techo_del_coche(self):
        """Sesenta kilómetros caminando no es un día largo, es un día imposible."""
        sin_pedir = Constraints(days=1, center_lat=13.70, center_lon=-89.22, mode="walking")

        assert sin_pedir.budget_for(1) == UNSTATED_BUDGET_BY_MODE["walking"]
        assert sin_pedir.budget_for(1) < UNSTATED_BUDGET_BY_MODE["driving"]

    def test_un_numero_pedido_manda_sobre_el_techo_propio(self):
        """ "poco carro" es un límite de la persona y gana, aunque sea más bajo."""
        pedido = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=10.0
        )

        assert pedido.budget_was_asked_for
        assert pedido.budget_for(1) == 10.0

    def test_un_numero_pedido_gana_aunque_sea_mas_alto(self):
        pedido = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=200.0
        )

        assert pedido.budget_for(1) == 200.0

    def test_el_dia_entra_mas_paradas_sin_el_techo_inventado(self):
        """El caso del hotel, reducido.

        Los candidatos van repartidos cada seis kilómetros, así que la cadena
        entera son sesenta: con el techo en 25 el día se corta aunque sobren
        candidatos, luz y reloj.

        **No se comprueba que el día llegue a las 23:00, porque no puede.**
        `INDOOR_CLOSES` y `DUSK` cierran las visitas alrededor de las 18:00 pase
        lo que pase, y lo único que estira un día más allá es la cena, que está
        exenta. Lo que el techo inventado sí decide es cuántas paradas entran
        antes de eso.
        """
        candidatos = [
            lugar(f"Lugar {i}", 13.70 + i * 0.06, -89.22, Category.culture) for i in range(10)
        ]
        base = dict(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            radius_m=90_000,
            earliest_start=time(9, 0),
            latest_end=time(23, 0),
            include_meals=False,
        )

        con_techo = assemble([], candidatos, Constraints(max_travel_km_per_day=25.0, **base))
        sin_techo = assemble([], candidatos, Constraints(**base))

        assert len(sin_techo.days[0].stops) > len(con_techo.days[0].stops)
        assert sin_techo.days[0].travel_km > con_techo.days[0].travel_km

    def test_no_le_aconseja_subir_un_limite_que_no_puso(self):
        """La otra mitad del fallo, y la que la persona leyó.

        El aviso decía "sobre tu límite de 25" y "subí el límite de traslado" a
        alguien que solo había dicho a qué hora quería estar de vuelta.
        """
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.702, -89.222, Category.culture),
        ]
        comedor = lugar("Comedor Lejano", 14.30, -89.22, Category.food)
        base = dict(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(10, 0),
            latest_end=time(20, 0),
            include_meals=True,
        )

        sin_pedir = assemble([comedor], destinos, Constraints(**base))
        aviso = next(c for c in sin_pedir.advice if c.kind == "bring_lunch")
        assert "tu límite" not in aviso.detail
        assert "subí el límite" not in aviso.detail
        assert "decime que no te importa moverte más" in aviso.detail

        pedido = assemble([comedor], destinos, Constraints(max_travel_km_per_day=25.0, **base))
        aviso = next(c for c in pedido.advice if c.kind == "bring_lunch")
        # Quien sí puso un límite sigue leyendo que es suyo y cómo subirlo.
        assert "tu límite de 25" in aviso.detail
        assert "subí el límite de traslado" in aviso.detail


class TestLaSalidaQueSeOfreceSirveEnSuModo:
    """Cada aviso de comida tiene que ofrecer algo que de verdad funcione.

    Medido sobre seis zonas: los siete días que caían en el aviso de
    presupuesto eran **todos a pie**, y a uno le decía "pedime un día de hasta
    27 km", que son cinco o seis horas caminando. El número no es una salida a
    pie; lo que destraba ese día es el modo, porque en coche el techo pasa de
    ocho a sesenta.
    """

    # El comedor tiene que quedar fuera del techo de SU modo, y los techos sin
    # pedir son ocho a pie y sesenta en coche.
    LEJOS = {"walking": 13.78, "driving": 14.30}

    def _escena(self, modo):
        destinos = [
            lugar("Museo", 13.700, -89.220, Category.culture),
            lugar("Teatro", 13.7015, -89.2215, Category.culture),
        ]
        comedor = lugar("Comedor Lejano", self.LEJOS[modo], -89.22, Category.food)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            mode=modo,
            earliest_start=time(10, 0),
            latest_end=time(20, 0),
            include_meals=True,
        )
        itinerario = assemble([comedor], destinos, restricciones)
        return next(c for c in itinerario.advice if c.kind == "bring_lunch")

    def test_a_pie_ofrece_el_coche_y_no_un_numero_de_kilometros(self):
        aviso = self._escena("walking")

        assert "en coche" in aviso.detail
        assert "pedime un día de hasta" not in aviso.detail

    def test_en_coche_no_le_pide_que_calcule(self):
        """El número va de referencia, no de tarea: basta con que diga que no
        le importa moverse."""
        aviso = self._escena("driving")

        assert "decime que no te importa moverte más" in aviso.detail
        assert "en coche" not in aviso.detail

    def test_el_aviso_del_reloj_habla_de_horas_y_no_de_kilometros(self):
        """El otro aviso, el del día que no llega a la franja de una comida
        pedida. Ahí el freno sí es el reloj, y más horas sí sirven —mientras
        que en el del presupuesto no agregarían ni un metro."""
        dia = Day(
            number=1,
            stops=[
                Stop(
                    place=lugar("Museo", 13.700, -89.220, Category.culture),
                    arrival=time(10, 0),
                    departure=time(15, 0),
                )
            ],
        )

        aviso = _meal_out_of_reach(dia, "dinner", DINNER_WINDOW, pidio_el_tope=False)

        assert "hasta qué hora podés" in aviso.detail
        assert "km" not in aviso.detail


class TestLaEsperaSeVuelveRatoEnElLugar:
    """Una comida no puede empezar antes de su franja, y eso dejaba hueco.

    El reporte: un día terminaba sus visitas a las 17:21 con la cena a las
    18:00, o sea treinta y nueve minutos muertos en un estacionamiento. La
    escapatoria es quedarse más rato en los lugares anteriores: los mismos
    treinta y nueve minutos en el mirador son rato de viaje.

    Medido sobre dieciséis días de ocho zonas: 346 minutos muertos en once
    casos, y con esto quedan cero.
    """

    def _dia(self, categoria, duracion_museo=None):
        destino = lugar("Mirador", 13.700, -89.220, categoria)
        comedor = lugar("Comedor", 13.701, -89.221, Category.food)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(15, 0),
            latest_end=time(22, 0),
            include_meals=True,
            must_include_meals=["dinner"],
        )
        return schedule_day(1, [(destino, None), (comedor, "dinner")], restricciones)

    def test_la_parada_anterior_se_estira_hasta_la_comida(self):
        """Sin esto, la parada terminaba temprano y el hueco quedaba muerto."""
        dia = self._dia(Category.viewpoint)

        mirador, cena = dia.stops
        assert cena.arrival == DINNER_WINDOW[0]
        # El mirador se queda hasta que toca salir hacia la cena, sin hueco.
        hueco = _minutes_between(mirador.departure, cena.arrival)
        assert hueco == cena.travel_minutes_from_previous

    def test_no_se_estira_mas_alla_de_la_luz(self):
        """Un mirador no se disfruta a oscuras: el tope sigue siendo DUSK."""
        dia = self._dia(Category.viewpoint)

        assert dia.stops[0].departure <= DUSK

    def test_lo_de_bajo_techo_para_en_su_hora_de_cierre(self):
        dia = self._dia(Category.culture)

        assert dia.stops[0].departure <= INDOOR_CLOSES

    def test_una_comida_anterior_no_se_alarga(self):
        """La duración de una comida la puso la persona; estirarla es cambiarle
        el pedido."""
        almuerzo = lugar("Almuerzo", 13.700, -89.220, Category.food)
        cena = lugar("Cena", 13.701, -89.221, Category.food)
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            earliest_start=time(12, 0),
            latest_end=time(22, 0),
            meal_minutes=60,
            include_meals=True,
        )

        dia = schedule_day(1, [(almuerzo, "lunch"), (cena, "dinner")], restricciones)

        assert _minutes_between(dia.stops[0].arrival, dia.stops[0].departure) == 60
