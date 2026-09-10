"""Tests de la construccion por fases.

Lo que hay que demostrar no es que se emitan tres eventos, sino que **entre
ellos pase algo de verdad**. Un streaming que calcula todo y despues lo suelta
de a pedacitos emite los mismos tres eventos y no sirve para nada.
"""

import uuid

import pytest

from app.models import Category
from app.services import itinerary as motor
from app.services import routing
from app.services.itinerary import (
    CandidatesReady,
    Constraints,
    DraftReady,
    PlanReady,
    plan_streaming,
    plan_with_routing,
)
from app.services.places import PlaceHit
from app.services.routing import ORSQuotaExhausted


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


def catalogo():
    destinos = [
        lugar("Volcan", 13.735, -89.285, Category.nature, "volcano"),
        lugar("Museo", 13.700, -89.220, Category.culture, "museum"),
        lugar("Mirador", 13.710, -89.230, Category.viewpoint, "viewpoint"),
        lugar("Teatro", 13.698, -89.191, Category.culture, "theatre"),
        lugar("Cascada", 13.760, -89.250, Category.nature, "waterfall"),
    ]
    comidas = [
        lugar("Comedor", 13.702, -89.222, Category.food, "restaurant"),
        lugar("Cafe", 13.706, -89.226, Category.food, "cafe"),
    ]
    return comidas, destinos


class ClienteFalso:
    """Cliente de ORS que anota cuando lo llamaron.

    Implementa las dos capacidades del cliente real, matriz y direcciones,
    porque el pipeline usa las dos: la matriz para las distancias y las
    direcciones para el trazo de cada dia. Un doble que solo sepa una de las
    dos deja sin cubrir la mitad del costo en peticiones.
    """

    def __init__(self, falla_con=None):
        self.falla_con = falla_con
        self.request_count = 0
        self.directions_count = 0
        # El cliente real lleva un cupo por endpoint, y load_travel_matrix lo
        # consulta para separar "sin cupo" de "sin carretera".
        self.matrix_quota = routing.DailyQuota(45)

    def directions(self, coords, profile):
        self.request_count += 1
        self.directions_count += 1
        if self.falla_con is not None:
            raise self.falla_con
        # Un trazo recto entre paradas: alcanza para que el troceo funcione.
        trazo = []
        for a, b in zip(coords, coords[1:], strict=False):
            for paso in range(5):
                t = paso / 5
                trazo.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        trazo.append(coords[-1])
        return trazo

    def matrix(self, coords, profile, sources=None, destinations=None):
        self.request_count += 1
        if self.falla_con is not None:
            raise self.falla_con

        from app.services.geo import haversine_km

        distancias = [
            [haversine_km(o[0], o[1], d[0], d[1]) * 1.6 for d in coords] for o in coords
        ]
        duraciones = [[km / 40.0 * 60 for km in fila] for fila in distancias]
        return distancias, duraciones


@pytest.fixture
def catalogo_fijo(monkeypatch):
    monkeypatch.setattr(motor, "select_candidates", lambda db, c: catalogo())


@pytest.fixture
def restricciones():
    return Constraints(days=2, center_lat=13.70, center_lon=-89.22, max_travel_km_per_day=60)


class TestFases:
    def test_emite_las_tres_fases_en_orden(self, catalogo_fijo, restricciones):
        eventos = list(plan_streaming(None, restricciones, client=ClienteFalso()))

        assert [e.phase for e in eventos] == ["candidates", "draft", "plan"]

    def test_el_borrador_llega_sin_tocar_la_red(self, catalogo_fijo, restricciones):
        """La prueba de que el streaming no es teatro.

        Si las dos primeras fases salieran despues de la llamada a ORS, el
        progreso seria fingido: todo calculado y soltado de a pedacitos.
        """
        cliente = ClienteFalso()
        fases = plan_streaming(None, restricciones, client=cliente)

        candidatos = next(fases)
        assert cliente.request_count == 0
        assert isinstance(candidatos, CandidatesReady)

        borrador = next(fases)
        assert cliente.request_count == 0, "el borrador no puede depender de la red"
        assert isinstance(borrador, DraftReady)

        final = next(fases)
        assert isinstance(final, PlanReady)

        # Una peticion de matriz para las distancias del itinerario entero, y
        # una de direcciones por cada dia que tenga tramos que dibujar. El
        # desglose se fija aparte porque el numero de peticiones es el recurso
        # escaso: son 45 diarias, y que este total suba sin querer se paga en
        # itinerarios que ya no se pueden armar.
        #
        # Un dia de una sola parada no tiene tramos, asi que no gasta nada.
        con_tramos = sum(1 for dia in final.itinerary.days if len(dia.stops) > 1)
        assert cliente.directions_count == con_tramos
        assert cliente.request_count == 1 + con_tramos

    def test_los_candidatos_llegan_separados_en_destinos_y_comidas(
        self, catalogo_fijo, restricciones
    ):
        candidatos = next(plan_streaming(None, restricciones, client=ClienteFalso()))

        assert {p.name for p in candidatos.meals} == {"Comedor", "Cafe"}
        assert "Volcan" in {p.name for p in candidatos.destinations}


class TestBorrador:
    def test_el_borrador_ya_es_un_itinerario_completo(self, catalogo_fijo, restricciones):
        """No es un adelanto parcial: esta armado, ordenado y verificado."""
        fases = plan_streaming(None, restricciones, client=ClienteFalso())
        next(fases)
        borrador = next(fases)

        assert borrador.itinerary.days
        assert borrador.itinerary.total_stops > 0
        for dia in borrador.itinerary.days:
            assert dia.start and dia.end
            assert dia.start < dia.end

    def test_el_borrador_sobrevive_a_que_ors_falle(self, catalogo_fijo, restricciones):
        """Sin cupo, el usuario se queda con el borrador y no con un error."""
        cliente = ClienteFalso(falla_con=ORSQuotaExhausted("sin cupo"))
        eventos = list(plan_streaming(None, restricciones, client=cliente))

        borrador = next(e for e in eventos if isinstance(e, DraftReady))
        final = next(e for e in eventos if isinstance(e, PlanReady))

        assert borrador.itinerary.total_stops > 0
        assert final.itinerary.total_stops > 0
        assert final.stats.fetched == 0
        assert final.stats.estimated > 0

    def test_sin_cliente_las_tres_fases_salen_igual(self, catalogo_fijo, restricciones):
        eventos = list(plan_streaming(None, restricciones, client=None))
        assert [e.phase for e in eventos] == ["candidates", "draft", "plan"]


class TestCompatibilidad:
    def test_plan_with_routing_devuelve_la_ultima_fase(self, catalogo_fijo, restricciones):
        eventos = list(plan_streaming(None, restricciones, client=ClienteFalso()))
        final = next(e for e in eventos if isinstance(e, PlanReady))

        itinerario, stats = plan_with_routing(None, restricciones, client=ClienteFalso())

        assert itinerario.total_stops == final.itinerary.total_stops
        assert stats.fetched == final.stats.fetched


class TestAlcanceDeLaMatriz:
    def test_solo_se_miden_los_lugares_que_pueden_entrar(self, monkeypatch):
        """Medir los ciento cincuenta candidatos gastaria nueve peticiones.

        La matriz se acota a lo que el borrador realmente eligio, que ademas
        deja el conteo por debajo de cincuenta y lo resuelve en una peticion.
        """
        muchos = [lugar(f"D{i}", 13.70 + i * 0.01, -89.22) for i in range(60)]
        comidas = [lugar(f"C{i}", 13.70 + i * 0.01, -89.23, Category.food) for i in range(20)]
        monkeypatch.setattr(motor, "select_candidates", lambda db, c: (comidas, muchos))

        medidos = {}

        def espia(lugares, mode="driving", **kwargs):
            medidos["cuantos"] = len({p.id for p in lugares})
            from app.services.routing import TravelMatrix

            return TravelMatrix()

        monkeypatch.setattr("app.services.routing.load_travel_matrix", espia)

        restricciones = Constraints(
            days=1, center_lat=13.70, center_lon=-89.22, max_stops_per_day=5
        )
        list(plan_streaming(None, restricciones))

        assert medidos["cuantos"] < 20, f"midio {medidos['cuantos']} lugares de 80"
