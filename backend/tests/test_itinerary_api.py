"""Tests del endpoint del planificador.

No tocan Postgres: se sustituye la seleccion de candidatos por una lista
armada a mano. Asi se ejercita el motor completo y la traduccion de schemas,
que es lo que este endpoint aporta, sin depender de que haya catalogo cargado.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from app.models import Category
from app.services import itinerary as motor
from app.services.places import PlaceHit

SAN_SALVADOR = {"center_lat": 13.6929, "center_lon": -89.2182}


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


def catalogo_cercano():
    destinos = [
        lugar("Museo Nacional", 13.700, -89.220),
        lugar("Mirador Planes", 13.710, -89.230, subcategoria="viewpoint"),
        lugar("Volcan de San Salvador", 13.735, -89.285, Category.nature, "volcano"),
        lugar("Teatro Nacional", 13.698, -89.191, Category.culture, "theatre"),
    ]
    comidas = [
        lugar("Comedor Lupita", 13.702, -89.222, Category.food, "restaurant"),
        lugar("Cafe Ataco", 13.706, -89.226, Category.food, "cafe"),
    ]
    return comidas, destinos


@pytest.fixture
def cliente(monkeypatch):
    """TestClient con la base desconectada y candidatos fijos."""
    monkeypatch.setattr(motor, "select_candidates", lambda db, c: catalogo_cercano())
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestValidacion:
    def test_rechaza_un_horario_al_reves(self, cliente):
        respuesta = cliente.post(
            "/itinerary",
            json={**SAN_SALVADOR, "earliest_start": "18:00", "latest_end": "09:00"},
        )
        assert respuesta.status_code == 422

    def test_rechaza_una_categoria_preferida_y_evitada_a_la_vez(self, cliente):
        respuesta = cliente.post(
            "/itinerary",
            json={
                **SAN_SALVADOR,
                "preferred_categories": ["nature"],
                "avoided_categories": ["nature"],
            },
        )
        assert respuesta.status_code == 422

    def test_rechaza_mas_dias_de_los_permitidos(self, cliente):
        respuesta = cliente.post("/itinerary", json={**SAN_SALVADOR, "days": 30})
        assert respuesta.status_code == 422

    def test_rechaza_coordenadas_imposibles(self, cliente):
        respuesta = cliente.post("/itinerary", json={"center_lat": 200, "center_lon": -89.2})
        assert respuesta.status_code == 422


class TestRespuesta:
    def test_arma_un_itinerario_con_distancias_estimadas(self, cliente):
        respuesta = cliente.post(
            "/itinerary", json={**SAN_SALVADOR, "days": 1, "real_routes": False}
        )
        assert respuesta.status_code == 200

        cuerpo = respuesta.json()
        assert cuerpo["days"], "tiene que armar al menos un dia"
        assert cuerpo["total_stops"] > 0
        assert cuerpo["travel"]["real_ratio"] == 0.0

    def test_cada_parada_trae_lugar_horas_y_traslado(self, cliente):
        cuerpo = cliente.post("/itinerary", json={**SAN_SALVADOR, "real_routes": False}).json()

        parada = cuerpo["days"][0]["stops"][0]
        assert parada["place"]["name"]
        assert parada["arrival"] and parada["departure"]
        assert "travel_km_from_previous" in parada

    def test_la_primera_parada_no_tiene_traslado_previo(self, cliente):
        cuerpo = cliente.post("/itinerary", json={**SAN_SALVADOR, "real_routes": False}).json()

        primera = cuerpo["days"][0]["stops"][0]
        assert primera["travel_km_from_previous"] == 0
        assert primera["travel_minutes_from_previous"] == 0

    def test_respeta_la_hora_minima_de_inicio(self, cliente):
        cuerpo = cliente.post(
            "/itinerary",
            json={**SAN_SALVADOR, "earliest_start": "11:00", "real_routes": False},
        ).json()

        assert cuerpo["days"][0]["stops"][0]["arrival"] >= "11:00"

    def test_una_categoria_evitada_no_aparece(self, cliente):
        cuerpo = cliente.post(
            "/itinerary",
            json={**SAN_SALVADOR, "avoided_categories": ["nature"], "real_routes": False},
        ).json()

        categorias = {p["place"]["category"] for d in cuerpo["days"] for p in d["stops"]}
        assert "nature" not in categorias


class TestViolaciones:
    def test_una_restriccion_incumplida_viaja_con_200(self, cliente):
        """Un itinerario parcial es util; un 422 lo tiraria entero."""
        respuesta = cliente.post(
            "/itinerary", json={**SAN_SALVADOR, "days": 6, "real_routes": False}
        )

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["satisfies_all_constraints"] is False
        assert any(v["constraint"] == "days" for v in cuerpo["violations"])

    def test_la_violacion_dice_su_magnitud(self, cliente):
        cuerpo = cliente.post(
            "/itinerary", json={**SAN_SALVADOR, "days": 6, "real_routes": False}
        ).json()

        detalle = next(v["detail"] for v in cuerpo["violations"] if v["constraint"] == "days")
        assert "6" in detalle


class TestOrigenDeLasDistancias:
    def test_la_respuesta_dice_de_donde_salieron(self, cliente):
        """El usuario ve horas de llegada y merece saber si son aproximadas."""
        cuerpo = cliente.post("/itinerary", json={**SAN_SALVADOR, "real_routes": False}).json()

        assert cuerpo["travel"]["source"] == "estimated"
        assert cuerpo["travel"]["real_ratio"] == 0.0

    def test_sin_llave_de_ors_degrada_en_vez_de_fallar(self, cliente, monkeypatch):
        from app.core.config import settings
        from app.services import routing

        routing.client_from_settings.cache_clear()
        monkeypatch.setattr(settings, "ors_api_key", None)

        respuesta = cliente.post("/itinerary", json={**SAN_SALVADOR, "real_routes": True})

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["days"]
        # Sin cliente no hay pares reales, pero el itinerario sale igual.
        assert cuerpo["travel"]["source"] == "estimated"
        assert cuerpo["travel"]["fetched"] == 0
        assert cuerpo["travel"]["estimated"] > 0
        routing.client_from_settings.cache_clear()

    def test_distingue_estimado_de_mezclado(self, cliente, monkeypatch):
        """Un itinerario a medias medido no puede presentarse como real."""
        from app.api.itinerary import _to_travel_source
        from app.services.routing import MatrixStats

        assert _to_travel_source(MatrixStats(estimated=6)).source == "estimated"
        assert _to_travel_source(MatrixStats(fetched=4, estimated=2)).source == "mixed"
        assert _to_travel_source(MatrixStats(cached=6)).source == "real"
