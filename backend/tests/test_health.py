"""Tests del chequeo de salud.

Existen por un fallo concreto: el primer despliegue en Railway paso la
comprobacion con PostGIS instalado, cero tablas y cero lugares. El servicio
decia "ok" y no podia armar un solo itinerario. El error aparecio mucho
despues, al intentar cargar los datos.

Un chequeo que solo mira si hay conexion no comprueba nada util.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


class ConexionFalsa:
    """Devuelve lo que se le dicte para cada consulta del chequeo."""

    def __init__(self, postgis="3.6.0", revision="0006", lugares=5658):
        self.respuestas = {
            "postgis": postgis,
            "alembic_version": revision,
            "places": lugares,
        }

    def execute(self, sentencia):
        texto = str(sentencia)
        for clave, valor in self.respuestas.items():
            if clave in texto:
                if valor is RuntimeError:
                    raise RuntimeError("la tabla no existe")
                return type("R", (), {"scalar": lambda _self, v=valor: v})()
        return type("R", (), {"scalar": lambda _self: 1})()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def con_base(monkeypatch):
    def montar(**kwargs):
        falsa = ConexionFalsa(**kwargs)
        monkeypatch.setattr(
            "app.main.engine", type("E", (), {"connect": lambda _self: falsa})()
        )
        return TestClient(app)

    return montar


class TestServicioSano:
    def test_con_todo_en_su_lugar_dice_ok(self, con_base):
        cuerpo = con_base().get("/health").json()

        assert cuerpo["status"] == "ok"
        assert cuerpo["issues"] == []
        assert cuerpo["catalog_places"] == 5658


class TestLoQueAntesPasabaDesapercibido:
    def test_sin_migraciones_no_dice_ok(self, con_base):
        """El caso real: PostGIS instalado a mano, ni una tabla creada."""
        cuerpo = con_base(revision=None, lugares=RuntimeError).get("/health").json()

        assert cuerpo["status"] == "degraded"
        assert any("migraciones" in p for p in cuerpo["issues"])

    def test_con_el_catalogo_vacio_no_dice_ok(self, con_base):
        """Esquema al dia y cero lugares: los itinerarios saldrian vacios."""
        cuerpo = con_base(lugares=0).get("/health").json()

        assert cuerpo["status"] == "degraded"
        assert any("catalogo" in p for p in cuerpo["issues"])

    def test_sin_postgis_no_dice_ok(self, con_base):
        cuerpo = con_base(postgis=None).get("/health").json()

        assert cuerpo["status"] == "degraded"
        assert any("PostGIS" in p for p in cuerpo["issues"])

    def test_los_problemas_se_acumulan(self, con_base):
        cuerpo = con_base(postgis=None, revision=None, lugares=0).get("/health").json()
        assert len(cuerpo["issues"]) == 3


class TestSigueRespondiendo:
    def test_degradado_no_es_un_error_http(self, con_base):
        """Un 500 haria que el orquestador reinicie en bucle.

        Lo que falta son datos, no un proceso sano: reiniciar no arregla nada
        y esconde el problema detras de un contenedor que no para de morir.
        """
        respuesta = con_base(lugares=0).get("/health")

        assert respuesta.status_code == 200
        assert respuesta.json()["status"] == "degraded"

    def test_informa_la_revision_del_esquema(self, con_base):
        """Sirve para ver de un vistazo si al desplegar falto migrar."""
        assert con_base().get("/health").json()["schema_revision"] == "0006"
