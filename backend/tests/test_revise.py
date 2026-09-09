"""Tests de la revision de un dia.

Lo que hay que demostrar no es que el dia pedido cambie, sino que **los otros
no**. Un planificador que al retocar el dia 3 te mueve el 1 es peor que uno
que no deja retocar nada, porque rompe lo que ya habias aceptado.
"""

import uuid

import pytest

from app.models import Category
from app.services import itinerary as motor
from app.services.itinerary import Constraints, DayState, revise_day
from app.services.places import PlaceHit


def lugar(nombre, lat, lon, categoria=Category.attraction, subcategoria="museum"):
    return PlaceHit(
        id=uuid.uuid4(),
        name=nombre,
        category=categoria.value,
        subcategory=subcategoria,
        lat=lat,
        lon=lon,
        quality_score=0.7,
    )


DESTINOS = [
    lugar("Volcan", 13.735, -89.285, Category.nature, "volcano"),
    lugar("Cascada", 13.760, -89.250, Category.nature, "waterfall"),
    lugar("Museo", 13.700, -89.220, Category.culture, "museum"),
    lugar("Teatro", 13.698, -89.191, Category.culture, "theatre"),
    lugar("Mirador", 13.710, -89.230, Category.viewpoint, "viewpoint"),
    lugar("Ruinas", 13.720, -89.240, Category.culture, "archaeological_site"),
    lugar("Cerro", 13.745, -89.265, Category.nature, "peak"),
    lugar("Termales", 13.755, -89.275, Category.attraction, "attraction"),
]
COMIDAS = [
    lugar("Comedor", 13.702, -89.222, Category.food, "restaurant"),
    lugar("Cafe", 13.706, -89.226, Category.food, "cafe"),
]
TODOS = {p.id: p for p in DESTINOS + COMIDAS}


@pytest.fixture
def catalogo(monkeypatch):
    monkeypatch.setattr(motor, "select_candidates", lambda db, c: (COMIDAS, DESTINOS))
    monkeypatch.setattr(
        motor, "places_by_ids", lambda db, ids: {i: TODOS[i] for i in ids if i in TODOS}
    )


@pytest.fixture
def restricciones():
    return Constraints(
        days=3,
        center_lat=13.72,
        center_lon=-89.24,
        max_travel_km_per_day=80,
        include_meals=False,
        max_stops_per_day=2,
    )


def estado():
    """Tres dias con dos paradas cada uno, como los tendria el cliente."""
    return [
        DayState(1, [(DESTINOS[0].id, None), (DESTINOS[1].id, None)]),
        DayState(2, [(DESTINOS[2].id, None), (DESTINOS[3].id, None)]),
        DayState(3, [(DESTINOS[4].id, None), (DESTINOS[5].id, None)]),
    ]


def nombres_por_dia(itinerario):
    return {d.number: [s.place.name for s in d.stops] for d in itinerario.days}


class TestLosOtrosDiasNoSeMueven:
    def test_conserva_las_paradas_de_los_dias_no_pedidos(self, catalogo, restricciones):
        antes = nombres_por_dia(revise_day(None, restricciones, estado(), target=3).itinerary)

        assert antes[1] == ["Volcan", "Cascada"]
        assert antes[2] == ["Museo", "Teatro"]

    def test_conserva_tambien_los_horarios(self, catalogo, restricciones):
        resultado = revise_day(None, restricciones, estado(), target=3)
        dia1 = next(d for d in resultado.itinerary.days if d.number == 1)

        assert dia1.start == restricciones.earliest_start

    def test_el_dia_pedido_si_cambia(self, catalogo, restricciones):
        """Con menos paradas permitidas, el dia 3 tiene que encogerse."""
        apretado = Constraints(
            days=1,
            center_lat=13.72,
            center_lon=-89.24,
            max_travel_km_per_day=80,
            include_meals=False,
            max_stops_per_day=1,
        )
        resultado = revise_day(
            None, restricciones, estado(), target=3, day_constraints=apretado
        )

        por_dia = nombres_por_dia(resultado.itinerary)
        assert len(por_dia[3]) == 1
        assert por_dia[1] == ["Volcan", "Cascada"], "el dia 1 no se toca"


class TestSinRepetirLugares:
    def test_no_reasigna_lo_que_usan_los_otros_dias(self, catalogo, restricciones):
        resultado = revise_day(None, restricciones, estado(), target=3)
        por_dia = nombres_por_dia(resultado.itinerary)

        del_dia_3 = set(por_dia[3])
        assert not del_dia_3 & set(por_dia[1])
        assert not del_dia_3 & set(por_dia[2])

    def test_puede_tomar_lo_que_estaba_sin_usar(self, catalogo, restricciones):
        """Quedaron Cerro y Termales libres: el dia rehecho puede usarlos."""
        resultado = revise_day(None, restricciones, estado(), target=3)
        del_dia_3 = set(nombres_por_dia(resultado.itinerary)[3])

        assert del_dia_3 & {"Cerro", "Termales", "Mirador", "Ruinas"}


class TestExclusiones:
    def test_un_lugar_excluido_no_vuelve(self, catalogo, restricciones):
        """El caso de 'sacá el museo': tiene que desaparecer del dia rehecho."""
        sin_cerro = {DESTINOS[6].id}
        resultado = revise_day(None, restricciones, estado(), target=3, exclude=sin_cerro)

        assert "Cerro" not in nombres_por_dia(resultado.itinerary)[3]


class TestParadasQueDesaparecieron:
    def test_informa_las_que_ya_no_estan_en_el_catalogo(self, catalogo, restricciones):
        """Un lugar desactivado por el filtro de calidad, por ejemplo.

        Se informa en vez de omitirse: la parada desaparecio del plan y el
        usuario tiene que enterarse, no descubrir que su dia tiene una menos.
        """
        fantasma = uuid.uuid4()
        con_fantasma = estado()
        con_fantasma[1].stops.append((fantasma, None))

        resultado = revise_day(None, restricciones, con_fantasma, target=3)

        assert resultado.missing == [fantasma]
        assert nombres_por_dia(resultado.itinerary)[2] == ["Museo", "Teatro"]


class TestVerificacion:
    def test_el_itinerario_revisado_se_vuelve_a_verificar(self, catalogo):
        """Las violaciones se recalculan sobre el resultado, no se arrastran."""
        estrecho = Constraints(
            days=3,
            center_lat=13.72,
            center_lon=-89.24,
            max_travel_km_per_day=1,
            include_meals=False,
            max_stops_per_day=2,
        )
        resultado = revise_day(None, estrecho, estado(), target=3)

        assert any(
            v.constraint == "max_travel_km_per_day" for v in resultado.itinerary.violations
        )
