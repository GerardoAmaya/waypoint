"""Tests del endpoint conversacional.

Se sustituyen el modelo y la seleccion de candidatos, asi que nada sale a la
red ni toca Postgres. Lo que se comprueba es el contrato del flujo: que
eventos salen, en que orden, y que pasa cuando algo falla a mitad de camino.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Category
from app.schemas import ItineraryRequest
from app.services import interpret as interpretador
from app.services import itinerary as motor
from app.services.geocode import ResolvedArea
from app.services.interpret import Interpretation
from app.services.places import PlaceHit

SUCHITOTO = ResolvedArea("Suchitoto", 13.9356, -89.0272, 15_000, "zone")


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
        lugar("Iglesia Santa Lucia", 13.936, -89.028, Category.culture, "church"),
        lugar("Mirador del lago", 13.940, -89.030, Category.viewpoint, "viewpoint"),
        lugar("Cascada Los Tercios", 13.945, -89.020, Category.nature, "waterfall"),
    ]
    comidas = [lugar("Comedor Suchitoto", 13.937, -89.029, Category.food, "restaurant")]
    return comidas, destinos


def interpretacion_buena(**extra):
    peticion = ItineraryRequest(
        days=1,
        center_lat=SUCHITOTO.lat,
        center_lon=SUCHITOTO.lon,
        radius_m=SUCHITOTO.radius_m,
    )
    base = dict(request=peticion, area=SUCHITOTO, area_text="Suchitoto")
    base.update(extra)
    return Interpretation(**base)


def leer_eventos(respuesta) -> list[tuple[str, dict]]:
    """Parsea el cuerpo SSE a una lista de (nombre, datos)."""
    eventos = []
    nombre = None
    for linea in respuesta.text.splitlines():
        if linea.startswith("event: "):
            nombre = linea[len("event: ") :]
        elif linea.startswith("data: ") and nombre:
            eventos.append((nombre, json.loads(linea[len("data: ") :])))
            nombre = None
    return eventos


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(motor, "select_candidates", lambda db, c: catalogo())
    monkeypatch.setattr("app.api.plan.SessionLocal", lambda: _SesionFalsa())
    with TestClient(app) as c:
        yield c


class _SesionFalsa:
    """Base minima: sin cache de traslados guardada y sin nada que escribir.

    El resultado falso trae `rowcount` ademas de `all` y `scalar` porque el
    resultado real de execute() lo trae: persist_geometry lo lee para saber
    cuantas aristas quedaron con su trazo, y un doble sin ese atributo hace
    fallar el endpoint por una carencia del doble y no del codigo.
    """

    def execute(self, *args, **kwargs):
        return type(
            "R",
            (),
            {
                "all": lambda _self: [],
                "scalar": lambda _self: None,
                "rowcount": 0,
            },
        )()

    def commit(self):
        pass

    def close(self):
        self.cerrada = True


def con_interpretacion(monkeypatch, resultado):
    monkeypatch.setattr("app.api.plan.interpret", lambda db, frase: resultado)


class TestFlujoCompleto:
    def test_emite_las_cuatro_fases_en_orden(self, cliente, monkeypatch):
        con_interpretacion(monkeypatch, interpretacion_buena())

        respuesta = cliente.post("/plan", json={"message": "un dia en Suchitoto"})
        nombres = [n for n, _ in leer_eventos(respuesta)]

        assert respuesta.status_code == 200
        assert nombres == ["interpretation", "candidates", "draft", "plan"]

    def test_el_tipo_de_contenido_es_de_eventos(self, cliente, monkeypatch):
        con_interpretacion(monkeypatch, interpretacion_buena())
        respuesta = cliente.post("/plan", json={"message": "un dia en Suchitoto"})

        assert respuesta.headers["content-type"].startswith("text/event-stream")

    def test_la_interpretacion_dice_que_se_entendio(self, cliente, monkeypatch):
        con_interpretacion(
            monkeypatch,
            interpretacion_buena(
                unmapped=["algo tranquilo"], notes=["se pidió days=10 y el máximo es 7"]
            ),
        )

        eventos = dict(leer_eventos(cliente.post("/plan", json={"message": "x"})))
        interpretacion = eventos["interpretation"]

        assert interpretacion["area"]["name"] == "Suchitoto"
        assert interpretacion["unmapped"] == ["algo tranquilo"]
        assert interpretacion["notes"]

    def test_el_borrador_y_el_plan_traen_itinerario(self, cliente, monkeypatch):
        con_interpretacion(monkeypatch, interpretacion_buena())
        eventos = dict(leer_eventos(cliente.post("/plan", json={"message": "x"})))

        assert eventos["draft"]["days"]
        assert eventos["plan"]["days"]
        assert eventos["draft"]["travel"]["source"] == "estimated"

    def test_los_candidatos_traen_solo_lo_que_el_mapa_dibuja(self, cliente, monkeypatch):
        """Mandar el catalogo entero serian cientos de kilobytes descartados."""
        con_interpretacion(monkeypatch, interpretacion_buena())
        eventos = dict(leer_eventos(cliente.post("/plan", json={"message": "x"})))

        primero = eventos["candidates"]["destinations"][0]
        assert set(primero) == {"id", "name", "lat", "lon", "category"}
        assert isinstance(eventos["candidates"]["meals"], int)


class TestErrores:
    def test_una_zona_desconocida_sale_como_evento(self, cliente, monkeypatch):
        """Con bytes ya enviados no se puede cambiar el codigo a 4xx."""
        con_interpretacion(
            monkeypatch,
            Interpretation(error="no encontré 'Cancun' en el catálogo"),
        )

        respuesta = cliente.post("/plan", json={"message": "quiero ir a Cancun"})
        eventos = leer_eventos(respuesta)

        assert respuesta.status_code == 200
        assert [n for n, _ in eventos] == ["error"]
        assert "Cancun" in eventos[0][1]["message"]

    def test_el_error_conserva_lo_que_si_se_entendio(self, cliente, monkeypatch):
        """Si hay que reformular, que no se repita todo desde cero."""
        con_interpretacion(
            monkeypatch,
            Interpretation(error="no encontré esa zona", unmapped=["algo tranquilo"]),
        )

        eventos = dict(leer_eventos(cliente.post("/plan", json={"message": "x"})))
        assert eventos["error"]["unmapped"] == ["algo tranquilo"]

    def test_un_fallo_a_mitad_de_camino_termina_en_error(self, cliente, monkeypatch):
        con_interpretacion(monkeypatch, interpretacion_buena())

        def explota(db, c):
            raise RuntimeError("la base se cayo")

        monkeypatch.setattr(motor, "select_candidates", explota)

        eventos = leer_eventos(cliente.post("/plan", json={"message": "x"}))
        nombres = [n for n, _ in eventos]

        assert nombres[-1] == "error"
        assert "interpretation" in nombres, "lo ya emitido no se pierde"


class TestValidacion:
    def test_rechaza_un_mensaje_vacio(self, cliente):
        assert cliente.post("/plan", json={"message": ""}).status_code == 422

    def test_rechaza_un_mensaje_larguisimo(self, cliente):
        respuesta = cliente.post("/plan", json={"message": "a" * 5_000})
        assert respuesta.status_code == 422


class TestSesion:
    def test_la_sesion_se_cierra_al_terminar(self, monkeypatch):
        """Con Depends(get_db) el cierre queda para despues de la respuesta.

        En una respuesta que se transmite eso deja sesiones colgadas, asi que
        el generador la abre y la cierra el mismo.
        """
        sesiones = []

        def fabrica():
            sesion = _SesionFalsa()
            sesiones.append(sesion)
            return sesion

        monkeypatch.setattr(motor, "select_candidates", lambda db, c: catalogo())
        monkeypatch.setattr("app.api.plan.SessionLocal", fabrica)
        monkeypatch.setattr("app.api.plan.interpret", lambda db, frase: interpretacion_buena())

        with TestClient(app) as c:
            c.post("/plan", json={"message": "x"})

        assert sesiones and all(getattr(s, "cerrada", False) for s in sesiones)


class TestInterpretadorReal:
    def test_el_endpoint_usa_el_interpretador(self, cliente, monkeypatch):
        """Sin llave configurada el flujo corta con un error entendible."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "anthropic_api_key", None)
        monkeypatch.setattr(interpretador, "resolve_area", lambda db, t, **k: SUCHITOTO)

        eventos = leer_eventos(cliente.post("/plan", json={"message": "un dia"}))

        assert [n for n, _ in eventos] == ["error"]
        assert "ANTHROPIC_API_KEY" in eventos[0][1]["message"]


class TestLimitePorIP:
    """El limite corta antes de que salga un solo byte.

    Importa que sea antes: una vez que empezo el flujo de eventos el codigo de
    estado ya se mando y no hay forma de responder 429.
    """

    def _con_limite(self, requests: int):
        """Reemplaza la dependencia por una mas estrecha, y la devuelve.

        La clave del reemplazo tiene que ser la funcion que la ruta capturo al
        importarse. Cambiar el atributo del modulo con monkeypatch no alcanza:
        la ruta guarda su propia referencia y ya no mira el modulo.
        """
        from app.api import plan as modulo
        from app.core.ratelimit import Limit, RateLimiter, limiter_dependency

        original = modulo.limitar
        estrecho = RateLimiter([Limit(requests, 60, "por minuto")])
        app.dependency_overrides[original] = limiter_dependency(estrecho, False)
        return original

    def test_rechaza_con_429_al_pasarse(self, cliente, monkeypatch):
        con_interpretacion(monkeypatch, interpretacion_buena())
        original = self._con_limite(2)
        try:
            codigos = [
                cliente.post("/plan", json={"message": "un dia"}).status_code for _ in range(3)
            ]
        finally:
            app.dependency_overrides.pop(original, None)

        assert codigos[:2] == [200, 200]
        assert codigos[2] == 429

    def test_el_rechazo_dice_cuanto_esperar(self, cliente, monkeypatch):
        con_interpretacion(monkeypatch, interpretacion_buena())
        original = self._con_limite(1)
        try:
            cliente.post("/plan", json={"message": "un dia"})
            respuesta = cliente.post("/plan", json={"message": "otro"})
        finally:
            app.dependency_overrides.pop(original, None)

        assert respuesta.status_code == 429
        assert "Retry-After" in respuesta.headers
        assert "segundos" in respuesta.json()["detail"]
