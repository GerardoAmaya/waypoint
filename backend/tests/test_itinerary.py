"""Tests del motor de itinerarios.

Se prueban las funciones puras con lugares construidos a mano: no hacen falta
ni base de datos ni catalogo para verificar que una restriccion se respeta.
"""

import uuid
from datetime import time

import pytest

from app.models import Category
from app.services.geo import (
    DETOUR_FACTOR,
    EstimatedTravel,
    haversine_km,
    speed_kmh,
)
from app.services.itinerary import (
    Constraints,
    Day,
    Itinerary,
    Stop,
    _insert_meals,
    _route_km,
    _trim_to_budget,
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

    def test_un_dia_largo_reserva_para_las_dos_comidas(self):
        candidatos = [lugar(f"P{i}", 13.700 + i * 0.004, -89.220) for i in range(14)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=10,
            latest_end=time(21, 0),
            include_meals=True,
            max_travel_km_per_day=120,
        )

        dias = build_days(candidatos, restricciones, meal_options=4)

        assert len(dias[0]) == 8, "dos cupos quedan para almuerzo y cena"

    def test_sin_tiempo_hasta_la_cena_no_se_reserva_para_ella(self):
        """Un dia largo pero que cierra temprano tampoco llega a cenar."""
        candidatos = [lugar(f"P{i}", 13.700 + i * 0.004, -89.220) for i in range(14)]
        restricciones = Constraints(
            days=1,
            center_lat=13.70,
            center_lon=-89.22,
            max_stops_per_day=10,
            latest_end=time(16, 0),
            include_meals=True,
            max_travel_km_per_day=120,
        )

        dias = build_days(candidatos, restricciones, meal_options=4)

        assert len(dias[0]) == 9

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

        assert "no hay ningún lugar para comer" in consejos[0].detail

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

    def test_sin_regreso_el_ancla_vale_solo_el_primer_dia(self):
        """Partir de un sitio se hace una vez; dormir ahi, todas las noches."""
        pizzeria = lugar("Pizzeria", 13.6900, -89.2100, Category.food, 0.5)
        restricciones = Constraints(
            days=3,
            center_lat=13.70,
            center_lon=-89.22,
            start_place=pizzeria,
            return_to_start=False,
            include_meals=False,
        )

        assert restricciones.anchors_day(1)
        assert not restricciones.anchors_day(2)
        assert not restricciones.anchors_day(3)

    def test_sin_ancla_nada_cambia(self):
        restricciones = Constraints(days=1, center_lat=13.70, center_lon=-89.22)

        assert not restricciones.anchors_day(1)
