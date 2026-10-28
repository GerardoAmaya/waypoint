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

    def test_sin_nadie_que_mida_degrada_en_vez_de_fallar(self, cliente, monkeypatch):
        """Ni llave de ORS ni OSRM propio: el caso de quien acaba de clonar.

        Las URLs de OSRM se apagan ademas porque el .env de desarrollo puede
        traerlas apuntando a un servicio levantado, y entonces este test salia
        a medir de verdad en vez de probar la degradacion.
        """
        from app.core.config import settings
        from app.services import routing

        routing.client_from_settings.cache_clear()
        monkeypatch.setattr(settings, "ors_api_key", None)
        monkeypatch.setattr(settings, "osrm_car_url", None)
        monkeypatch.setattr(settings, "osrm_foot_url", None)

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


class TestConsejos:
    def test_la_respuesta_trae_los_consejos_aparte(self, cliente):
        """El viajero ve por que no hubo almuerzo y que puede hacer."""
        cuerpo = cliente.post(
            "/itinerary",
            json={**SAN_SALVADOR, "real_routes": False, "max_travel_km_per_day": 1},
        ).json()

        assert "advice" in cuerpo
        assert isinstance(cuerpo["advice"], list)

    def test_un_dia_sin_almuerzo_ya_no_es_violacion(self, cliente):
        cuerpo = cliente.post(
            "/itinerary",
            json={**SAN_SALVADOR, "real_routes": False, "max_travel_km_per_day": 1},
        ).json()

        assert not any(v["constraint"] == "include_meals" for v in cuerpo["violations"])


class TestLoQueElDiaLeCuentaALaPantalla:
    """Dos datos que el motor ya calculaba y antes se quedaban en el servidor.

    Los dos se dibujan en la linea de tiempo: el ocaso parte el hilo en dia y
    noche, y `rained_on` marca la parada que se moja. Se prueban en la
    traduccion a schema porque es ahi donde se pierden sin que nada reviente:
    el motor sigue calculandolos y la pantalla deja de recibirlos.
    """

    def _dia(self, paradas, fecha, clima=None):
        from datetime import date as _date

        from app.api.itinerary import _to_day

        restricciones = motor.Constraints(
            days=1, start_date=fecha, center_lat=13.99, center_lon=-89.55
        )
        assert restricciones.date_of_day(1) == _date.fromisoformat(str(fecha))
        return _to_day(
            motor.Day(number=1, stops=paradas),
            {},
            restricciones,
            clima,
        )

    def test_el_ocaso_del_dia_viaja_con_el_dia(self):
        from datetime import date, time

        cerro = lugar("Cerro Verde", 13.99, -89.55, Category.viewpoint, "viewpoint")
        parada = motor.Stop(place=cerro, arrival=time(15, 0), departure=time(17, 0))

        # Junio y noviembre no anochecen a la misma hora, y el campo tiene que
        # notarlo: si devolviera la constante, el hilo mentiria medio ano.
        junio = self._dia([parada], date(2026, 6, 21)).sunset
        noviembre = self._dia([parada], date(2026, 11, 21)).sunset

        assert junio is not None and noviembre is not None
        assert junio > noviembre

    def test_sin_fecha_no_hay_ocaso_inventado(self):
        from datetime import time

        from app.api.itinerary import _to_day

        cerro = lugar("Cerro Verde", 13.99, -89.55, Category.viewpoint, "viewpoint")
        parada = motor.Stop(place=cerro, arrival=time(15, 0), departure=time(17, 0))
        dia = _to_day(
            motor.Day(number=1, stops=[parada]),
            {},
            motor.Constraints(days=1, center_lat=13.99, center_lon=-89.55),
            None,
        )

        assert dia.sunset is None

    def test_la_parada_mojada_llega_marcada_y_la_de_al_lado_no(self):
        """El dato que antes se quedaba en el consejo, ahora por parada."""
        from datetime import date, time

        from app.services.clima import ClimaDelViaje
        from tests.test_clima import dia_de, lluviosa

        cuando = date(2026, 6, 21)
        cerro = lugar("Cerro Verde", 13.99, -89.55, Category.viewpoint, "viewpoint")
        museo = lugar("Museo", 13.99, -89.55, Category.culture, "museum")
        dia = self._dia(
            [
                motor.Stop(place=cerro, arrival=time(15, 0), departure=time(16, 0)),
                motor.Stop(place=museo, arrival=time(16, 30), departure=time(17, 30)),
            ],
            cuando,
            clima=ClimaDelViaje(dias={cuando: dia_de(cuando, [lluviosa(15), lluviosa(17)])}),
        )

        # Al cerro le llueve a las 15:00. Al museo tambien le llueve encima a
        # las 17:00, y da igual: esta bajo techo.
        assert [p.rained_on for p in dia.stops] == [True, False]

    def test_sin_pronostico_ninguna_parada_se_marca(self):
        """No saber se parece mas a no marcar nada que a marcarlo todo."""
        from datetime import date, time

        cerro = lugar("Cerro Verde", 13.99, -89.55, Category.viewpoint, "viewpoint")
        parada = motor.Stop(place=cerro, arrival=time(15, 0), departure=time(17, 0))

        dia = self._dia([parada], date(2026, 6, 21), clima=None)

        assert [p.rained_on for p in dia.stops] == [False]
