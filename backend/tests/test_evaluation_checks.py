"""Tests del comprobador de la evaluacion.

Este modulo juzga a todos los demas, asi que necesita sus propios tests. Se le
dan itinerarios con fallos puestos a mano y se comprueba que los encuentre, y
uno limpio que tiene que pasar.

Ojo con lo circular: los itinerarios de aqui se construyen a mano y no con el
motor, justamente para que un error del motor no se cuele en la prueba del
comprobador.
"""

import uuid
from datetime import time

import pytest

from app.models import Category
from app.services.itinerary import Constraints, Day, Itinerary, Stop
from app.services.places import PlaceHit
from scripts.evaluation.checks import check_all

CENTRO = (13.70, -89.22)


def lugar(nombre, lat=13.70, lon=-89.22, categoria=Category.attraction):
    return PlaceHit(
        id=uuid.uuid4(),
        name=nombre,
        category=categoria.value,
        subcategory=None,
        lat=lat,
        lon=lon,
        quality_score=0.5,
    )


def parada(place, llegada, salida, km=1.0, comida=None):
    return Stop(
        place=place,
        arrival=llegada,
        departure=salida,
        travel_minutes_from_previous=10,
        travel_km_from_previous=km,
        meal=comida,
    )


def restricciones(**extra):
    base = dict(
        days=1,
        center_lat=CENTRO[0],
        center_lon=CENTRO[1],
        radius_m=20_000,
        include_meals=False,
    )
    base.update(extra)
    return Constraints(**base)


def itinerario(*dias):
    return Itinerary(days=list(dias))


def dia_limpio(numero=1, lugares=None):
    lugares = lugares or [lugar("A"), lugar("B")]
    d = Day(number=numero)
    d.stops.append(parada(lugares[0], time(9, 0), time(10, 0), km=0.0))
    d.stops.append(parada(lugares[1], time(10, 15), time(11, 15), km=2.0))
    return d


def checks_de(reporte):
    return {f.check for f in reporte.failures}


class TestUnItinerarioLimpio:
    def test_no_reporta_nada(self):
        reporte = check_all(itinerario(dia_limpio()), restricciones())
        assert reporte.passed, [f.detail for f in reporte.failures]


class TestHorarios:
    def test_detecta_que_empieza_antes_de_la_hora(self):
        reporte = check_all(
            itinerario(dia_limpio()), restricciones(earliest_start=time(10, 0))
        )
        assert "earliest_start" in checks_de(reporte)

    def test_detecta_que_termina_despues_de_la_hora(self):
        reporte = check_all(itinerario(dia_limpio()), restricciones(latest_end=time(10, 30)))
        assert "latest_end" in checks_de(reporte)

    def test_detecta_que_el_tiempo_retrocede(self):
        """validate() no lo comprueba."""
        d = Day(number=1)
        d.stops.append(parada(lugar("A"), time(11, 0), time(10, 0), km=0.0))

        assert "chronology" in checks_de(check_all(itinerario(d), restricciones()))

    def test_detecta_paradas_solapadas(self):
        d = Day(number=1)
        d.stops.append(parada(lugar("A"), time(9, 0), time(12, 0), km=0.0))
        d.stops.append(parada(lugar("B"), time(10, 0), time(13, 0)))

        assert "overlap" in checks_de(check_all(itinerario(d), restricciones()))


class TestLimites:
    def test_detecta_demasiadas_paradas(self):
        reporte = check_all(itinerario(dia_limpio()), restricciones(max_stops_per_day=1))
        assert "max_stops_per_day" in checks_de(reporte)

    def test_suma_los_kilometros_por_su_cuenta(self):
        """No lee dia.travel_km: seria confiar en la cuenta del motor."""
        reporte = check_all(itinerario(dia_limpio()), restricciones(max_travel_km_per_day=1))
        assert "max_travel_km_per_day" in checks_de(reporte)

    def test_una_decima_de_margen_no_dispara(self):
        reporte = check_all(itinerario(dia_limpio()), restricciones(max_travel_km_per_day=2.0))
        assert "max_travel_km_per_day" not in checks_de(reporte)


class TestCategorias:
    def test_detecta_una_categoria_evitada(self):
        d = dia_limpio(lugares=[lugar("Volcan", categoria=Category.nature), lugar("B")])
        reporte = check_all(itinerario(d), restricciones(avoided_categories=[Category.nature]))
        assert "avoided_categories" in checks_de(reporte)


class TestCosasQueValidateNoMira:
    def test_detecta_un_lugar_repetido_entre_dias(self):
        """El fallo que una evaluacion hecha con el motor nunca encontraria."""
        repetido = lugar("Repetido")
        d1 = dia_limpio(1, [repetido, lugar("B")])
        d2 = dia_limpio(2, [repetido, lugar("C")])

        reporte = check_all(itinerario(d1, d2), restricciones(days=2))

        assert "repeated_place" in checks_de(reporte)

    def test_detecta_una_parada_fuera_del_radio(self):
        lejos = lugar("Lejos", lat=14.30, lon=-89.90)
        reporte = check_all(
            itinerario(dia_limpio(lugares=[lugar("A"), lejos])),
            restricciones(radius_m=5_000),
        )
        assert "radius" in checks_de(reporte)

    def test_detecta_un_lugar_que_no_esta_en_el_catalogo(self):
        d = dia_limpio()
        conocidos = {d.stops[0].place.id}

        reporte = check_all(itinerario(d), restricciones(), catalog_ids=conocidos)

        assert "invented_place" in checks_de(reporte)

    def test_sin_catalogo_no_comprueba_lugares_inventados(self):
        reporte = check_all(itinerario(dia_limpio()), restricciones(), catalog_ids=None)
        assert "invented_place" not in checks_de(reporte)

    def test_detecta_un_dia_vacio(self):
        assert "empty_day" in checks_de(check_all(itinerario(Day(number=1)), restricciones()))


class TestDiasFaltantes:
    def test_detecta_que_se_armaron_menos_dias(self):
        reporte = check_all(itinerario(dia_limpio()), restricciones(days=3))
        assert "days" in checks_de(reporte)

    def test_no_reclama_si_estan_todos(self):
        reporte = check_all(itinerario(dia_limpio(1), dia_limpio(2)), restricciones(days=2))
        assert "days" not in checks_de(reporte)


class TestComidas:
    def test_detecta_el_almuerzo_que_falta(self):
        d = Day(number=1)
        d.stops.append(parada(lugar("A"), time(9, 0), time(13, 0), km=0.0))

        reporte = check_all(itinerario(d), restricciones(include_meals=True))

        assert "include_meals" in checks_de(reporte)

    def test_con_el_almuerzo_puesto_no_reclama(self):
        d = Day(number=1)
        d.stops.append(parada(lugar("A"), time(9, 0), time(11, 30), km=0.0))
        d.stops.append(
            parada(
                lugar("Comedor", categoria=Category.food),
                time(11, 45),
                time(12, 45),
                comida="lunch",
            )
        )

        reporte = check_all(itinerario(d), restricciones(include_meals=True))

        assert "include_meals" not in checks_de(reporte)

    def test_si_no_se_pidieron_comidas_no_reclama(self):
        d = Day(number=1)
        d.stops.append(parada(lugar("A"), time(9, 0), time(14, 0), km=0.0))

        reporte = check_all(itinerario(d), restricciones(include_meals=False))

        assert "include_meals" not in checks_de(reporte)


class TestCorpusDeCasos:
    def test_todos_los_casos_nombran_una_zona_real(self):
        from app.services.geocode import find_zone
        from scripts.evaluation.cases import CASES

        for caso in CASES:
            assert find_zone(caso.zone) is not None, caso.name

    def test_los_nombres_de_los_casos_no_se_repiten(self):
        from scripts.evaluation.cases import CASES

        nombres = [c.name for c in CASES]
        assert len(nombres) == len(set(nombres))

    @pytest.mark.parametrize(
        "zona_dificil", ["Perquin", "Costa del Sol", "Alegria", "Metapan"]
    )
    def test_el_corpus_incluye_las_zonas_flacas(self, zona_dificil):
        """Una muestra que solo tome zonas densas mide un sistema mas facil."""
        from scripts.evaluation.cases import CASES

        assert any(c.zone == zona_dificil for c in CASES)


class TestDurasYRecomendaciones:
    """Un limite incumplido y un consejo no son la misma clase de cosa.

    Con los dos en el mismo porcentaje, la mitad de los "fallos" eran zonas
    rurales sin restaurante cerca y el numero dejaba de significar algo.
    """

    def test_una_comida_que_falta_no_hace_fallar_el_caso(self):
        d = Day(number=1)
        d.stops.append(parada(lugar("A"), time(9, 0), time(13, 0), km=0.0))

        reporte = check_all(itinerario(d), restricciones(include_meals=True))

        assert reporte.soft, "tiene que registrarse"
        assert reporte.passed, "pero no cuenta como limite incumplido"

    def test_un_limite_duro_si_hace_fallar_el_caso(self):
        reporte = check_all(itinerario(dia_limpio()), restricciones(max_stops_per_day=1))

        assert reporte.hard
        assert not reporte.passed

    def test_los_dos_conviven_sin_mezclarse(self):
        d = Day(number=1)
        d.stops.append(parada(lugar("A"), time(9, 0), time(11, 0), km=0.0))
        d.stops.append(parada(lugar("B"), time(11, 10), time(13, 0), km=50.0))

        reporte = check_all(
            itinerario(d),
            restricciones(include_meals=True, max_travel_km_per_day=10),
        )

        assert {f.check for f in reporte.hard} == {"max_travel_km_per_day"}
        assert {f.check for f in reporte.soft} == {"include_meals"}
