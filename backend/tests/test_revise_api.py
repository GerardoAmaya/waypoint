"""Tests del endpoint de revision.

El modelo y el catalogo se sustituyen. Lo que se comprueba es el contrato: que
un cambio se aplique al dia pedido, que los otros no se muevan, y que un
pedido que el sistema no puede cumplir se diga en vez de ignorarse.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Category
from app.services import itinerary as motor
from app.services.interpret import Revision
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
]
TODOS = {p.id: p for p in DESTINOS}


class _SesionFalsa:
    def execute(self, *args, **kwargs):
        return type("R", (), {"all": lambda _self: [], "scalar": lambda _self: None})()

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(motor, "select_candidates", lambda db, c: ([], DESTINOS))
    por_ids = lambda db, ids: {i: TODOS[i] for i in ids if i in TODOS}  # noqa: E731
    monkeypatch.setattr(motor, "places_by_ids", por_ids)
    monkeypatch.setattr("app.api.plan.places_by_ids", por_ids)
    monkeypatch.setattr("app.api.plan.SessionLocal", lambda: _SesionFalsa())
    with TestClient(app) as c:
        yield c


def con_revision(monkeypatch, revision):
    monkeypatch.setattr("app.api.plan.interpret_revision", lambda f, s: revision)


def cuerpo(**extra):
    base = {
        "message": "menos carro el día 2",
        "day": 2,
        "constraints": {
            "days": 2,
            "center_lat": 13.72,
            "center_lon": -89.24,
            "max_travel_km_per_day": 80,
            "include_meals": False,
            "max_stops_per_day": 2,
        },
        "days": [
            {
                "number": 1,
                "stops": [
                    {"place_id": str(DESTINOS[0].id)},
                    {"place_id": str(DESTINOS[1].id)},
                ],
            },
            {
                "number": 2,
                "stops": [
                    {"place_id": str(DESTINOS[2].id)},
                    {"place_id": str(DESTINOS[3].id)},
                ],
            },
        ],
    }
    base.update(extra)
    return base


def nombres(respuesta, numero):
    dia = next(d for d in respuesta["itinerary"]["days"] if d["number"] == numero)
    return [s["place"]["name"] for s in dia["stops"]]


class TestAplicaElCambio:
    def test_el_dia_pedido_cambia(self, cliente, monkeypatch):
        con_revision(monkeypatch, Revision(changes={"max_stops_per_day": 1}))

        respuesta = cliente.post("/plan/revise", json=cuerpo())

        assert respuesta.status_code == 200
        assert len(nombres(respuesta.json(), 2)) == 1

    def test_el_otro_dia_no_se_mueve(self, cliente, monkeypatch):
        """Lo que ya aceptaste no se te puede mover por tocar otra cosa."""
        con_revision(monkeypatch, Revision(changes={"max_stops_per_day": 1}))

        cuerpo_json = cliente.post("/plan/revise", json=cuerpo()).json()

        assert nombres(cuerpo_json, 1) == ["Volcan", "Cascada"]

    def test_dice_que_cambio_aplico(self, cliente, monkeypatch):
        con_revision(monkeypatch, Revision(changes={"max_travel_km_per_day": 15.0}))

        respuesta = cliente.post("/plan/revise", json=cuerpo()).json()

        assert "max_travel_km_per_day" in respuesta["applied"]

    def test_saca_la_parada_pedida(self, cliente, monkeypatch):
        con_revision(monkeypatch, Revision(changes={"max_stops_per_day": 2}, remove=["Museo"]))

        respuesta = cliente.post("/plan/revise", json=cuerpo()).json()

        assert "Museo" not in nombres(respuesta, 2)
        assert respuesta["removed"] == ["Museo"]


class TestLoQueNoSePuedeCumplir:
    def test_un_pedido_sin_cambios_se_rechaza_con_explicacion(self, cliente, monkeypatch):
        """El caso de 'se ve caro': no hay dimension de costo en el motor.

        Rehacer el dia sin ningun cambio que aplicar lo moveria por nada, y el
        usuario creeria que su pedido se atendio.
        """
        con_revision(monkeypatch, Revision(unmapped=["se ve caro"]))

        respuesta = cliente.post("/plan/revise", json=cuerpo(message="el día 2 se ve caro"))

        assert respuesta.status_code == 422
        assert "se ve caro" in respuesta.json()["detail"]

    def test_el_rechazo_sugiere_lo_que_si_se_puede(self, cliente, monkeypatch):
        con_revision(monkeypatch, Revision())

        detalle = cliente.post("/plan/revise", json=cuerpo()).json()["detail"]

        assert "kilómetros" in detalle or "paradas" in detalle

    def test_un_error_del_modelo_sale_como_422(self, cliente, monkeypatch):
        con_revision(monkeypatch, Revision(error="el modelo no devolvió JSON válido"))

        assert cliente.post("/plan/revise", json=cuerpo()).status_code == 422


class TestValidacion:
    def test_rechaza_un_dia_que_no_existe(self, cliente):
        respuesta = cliente.post("/plan/revise", json=cuerpo(day=5))

        assert respuesta.status_code == 422

    def test_rechaza_un_mensaje_vacio(self, cliente):
        assert cliente.post("/plan/revise", json=cuerpo(message="")).status_code == 422

    def test_rechaza_un_itinerario_sin_dias(self, cliente):
        assert cliente.post("/plan/revise", json=cuerpo(days=[])).status_code == 422


class TestLasRestriccionesLleganEnteras:
    """El cliente devuelve las restricciones y el servidor las reconstruye.

    Se reconstruian campo por campo y faltaban tres, los tres duros: sin
    day_modes el dia a pie se rehacia en coche, sin must_include_categories
    "minimo un museo" dejaba de exigirse, y sin el punto de partida el dia
    revisado ya no salia ni volvia al hotel. Nada de eso lo pidio quien
    revisa, y ninguna prueba lo miraba porque el olvido esta en la copia.
    """

    def test_ningun_limite_duro_se_queda_por_el_camino(self, monkeypatch):
        from app.api.plan import _to_constraints
        from app.schemas import ItineraryRequest

        casa = lugar("Casa", 13.72, -89.24, Category.lodging, "hotel")
        monkeypatch.setattr("app.api.plan.places_by_ids", lambda db, ids: {casa.id: casa})

        peticion = ItineraryRequest(
            days=2,
            center_lat=13.72,
            center_lon=-89.24,
            must_include_categories=[Category.culture],
            day_modes={"2": "walking"},
            start_place_id=casa.id,
            return_to_start=True,
        )

        restricciones = _to_constraints(peticion, None)

        assert restricciones.must_include_categories == [Category.culture]
        assert restricciones.start_place is not None
        assert restricciones.return_to_start is True
        # La consecuencia, que es lo que de verdad importaba: el dia 2 se
        # rehace a pie y con el presupuesto de a pie.
        assert restricciones.mode_for(2) == "walking"
        # Contra la constante y no contra el numero: lo que importa es que el
        # dia a pie reciba el presupuesto de a pie y no el del coche, no cual
        # sea el valor de ese presupuesto hoy.
        assert restricciones.budget_for(2) == motor.UNSTATED_BUDGET_BY_MODE["walking"]
        assert restricciones.budget_for(2) < motor.UNSTATED_BUDGET_BY_MODE["driving"]
        assert restricciones.anchors_day(2) is True
