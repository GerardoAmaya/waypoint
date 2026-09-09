"""Tests de la traduccion de una frase a restricciones.

El modelo se sustituye por uno falso que devuelve el JSON que uno le dicte.
Lo que se prueba no es que el modelo acierte —eso se mide en la fase 7— sino
que la capa que lo rodea aguante todo lo que un modelo puede devolver mal.
"""

import json
from datetime import time

import pytest

from app.models import Category
from app.services import interpret as modulo
from app.services.geocode import ResolvedArea, find_zone
from app.services.interpret import interpret


class BloqueTexto:
    type = "text"

    def __init__(self, text):
        self.text = text


class RespuestaFalsa:
    def __init__(self, texto):
        self.content = [BloqueTexto(texto)]


class ModeloFalso:
    """Devuelve el texto que se le dio y anota como lo llamaron."""

    def __init__(self, texto):
        self.texto = texto
        self.llamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        return RespuestaFalsa(self.texto)


def modelo(payload, crudo=None):
    return ModeloFalso(crudo if crudo is not None else json.dumps(payload))


@pytest.fixture(autouse=True)
def sin_catalogo(monkeypatch):
    """El nomenclator no necesita base; la busqueda por nombre si."""
    monkeypatch.setattr(modulo, "resolve_area", _resolver_solo_zonas)


def _resolver_solo_zonas(db, texto, **kwargs):
    zona = find_zone(texto)
    if zona is None:
        return None
    return ResolvedArea(zona.name, zona.lat, zona.lon, zona.radius_m, "zone")


BASE = {
    "area": "Suchitoto",
    "days": 2,
    "earliest_start": "10:00",
    "latest_end": "19:00",
    "max_travel_km_per_day": 30,
    "mode": "driving",
    "preferred_categories": ["culture"],
    "avoided_categories": [],
    "include_meals": True,
    "max_stops_per_day": 5,
    "unmapped": [],
}


class TestTraduccion:
    def test_traduce_una_frase_completa(self):
        resultado = interpret(None, "dos dias en Suchitoto, odio madrugar", modelo(BASE))

        assert resultado.ok
        assert resultado.request.days == 2
        assert resultado.request.earliest_start == time(10, 0)
        assert resultado.request.max_travel_km_per_day == 30
        assert resultado.area.name == "Suchitoto"

    def test_la_zona_define_el_centro_y_el_radio(self):
        resultado = interpret(None, "un dia en Suchitoto", modelo(BASE))

        assert resultado.request.center_lat == pytest.approx(13.9356)
        assert resultado.request.radius_m == 15_000

    def test_la_frase_llega_al_modelo_sin_tocar(self):
        falso = modelo(BASE)
        interpret(None, "tres dias por la Ruta de las Flores", falso)

        mensajes = falso.llamadas[0]["messages"]
        assert mensajes[0]["content"] == "tres dias por la Ruta de las Flores"


class TestLoQueNoSePuedeTraducir:
    def test_lo_no_mapeable_se_devuelve(self):
        """La decision central: se informa, no se descarta ni se disfraza."""
        payload = {**BASE, "unmapped": ["algo tranquilo", "presupuesto bajo"]}
        resultado = interpret(None, "un dia tranquilo en Suchitoto", modelo(payload))

        assert resultado.unmapped == ["algo tranquilo", "presupuesto bajo"]
        assert resultado.ok, "no traducir todo no impide armar el itinerario"

    def test_unmapped_ausente_no_rompe(self):
        payload = {k: v for k, v in BASE.items() if k != "unmapped"}
        resultado = interpret(None, "un dia en Suchitoto", modelo(payload))

        assert resultado.unmapped == []
        assert resultado.ok


class TestValoresFueraDeRango:
    def test_recorta_los_dias_y_lo_dice(self):
        """Recortar en silencio deja a alguien pidiendo diez y recibiendo siete."""
        resultado = interpret(None, "diez dias", modelo({**BASE, "days": 10}))

        assert resultado.request.days == 7
        assert any("days" in n for n in resultado.notes)

    def test_recorta_por_abajo(self):
        resultado = interpret(None, "cero dias", modelo({**BASE, "days": 0}))
        assert resultado.request.days == 1

    def test_una_categoria_inventada_se_ignora_con_aviso(self):
        payload = {**BASE, "preferred_categories": ["culture", "playas"]}
        resultado = interpret(None, "playas", modelo(payload))

        assert resultado.request.preferred_categories == [Category.culture]
        assert any("playas" in n for n in resultado.notes)

    def test_una_categoria_preferida_y_evitada_gana_evitarla(self):
        payload = {
            **BASE,
            "preferred_categories": ["culture", "nature"],
            "avoided_categories": ["nature"],
        }
        resultado = interpret(None, "sin naturaleza", modelo(payload))

        assert Category.nature not in resultado.request.preferred_categories
        assert Category.nature in resultado.request.avoided_categories
        assert any("nature" in n for n in resultado.notes)

    def test_un_horario_al_reves_vuelve_al_de_por_defecto(self):
        payload = {**BASE, "earliest_start": "20:00", "latest_end": "08:00"}
        resultado = interpret(None, "raro", modelo(payload))

        assert resultado.ok
        assert resultado.request.earliest_start == time(9, 0)
        assert any("inicio" in n for n in resultado.notes)

    def test_una_hora_ilegible_usa_la_de_por_defecto(self):
        resultado = interpret(None, "x", modelo({**BASE, "earliest_start": "tempranito"}))

        assert resultado.request.earliest_start == time(9, 0)
        assert any("tempranito" in n for n in resultado.notes)

    def test_un_modo_desconocido_cae_a_driving(self):
        resultado = interpret(None, "x", modelo({**BASE, "mode": "helicoptero"}))
        assert resultado.request.mode == "driving"


class TestRespuestasMalas:
    def test_json_invalido_no_revienta(self):
        resultado = interpret(None, "un dia", modelo(None, crudo="lo siento, no puedo"))

        assert not resultado.ok
        assert "JSON" in resultado.error

    def test_tolera_las_marcas_de_bloque(self):
        """El modelo agrega ```json aunque se le pida que no."""
        crudo = "```json\n" + json.dumps(BASE) + "\n```"
        resultado = interpret(None, "un dia", modelo(None, crudo=crudo))

        assert resultado.ok

    def test_una_lista_en_vez_de_objeto_no_revienta(self):
        resultado = interpret(None, "un dia", modelo(None, crudo="[1, 2, 3]"))
        assert not resultado.ok


class TestZonaQueFalta:
    def test_sin_zona_pide_una(self):
        resultado = interpret(None, "dos dias", modelo({**BASE, "area": None}))

        assert not resultado.ok
        assert "a donde" in resultado.error or "dónde" in resultado.error

    def test_una_zona_desconocida_lista_las_que_hay(self):
        resultado = interpret(None, "quiero ir a Cancun", modelo({**BASE, "area": "Cancun"}))

        assert not resultado.ok
        assert "Suchitoto" in resultado.error

    def test_lo_no_traducido_sobrevive_al_error_de_zona(self):
        """Si el usuario tiene que reformular, no le hagamos repetir todo."""
        payload = {**BASE, "area": "Cancun", "unmapped": ["algo tranquilo"]}
        resultado = interpret(None, "algo tranquilo en Cancun", modelo(payload))

        assert not resultado.ok
        assert resultado.unmapped == ["algo tranquilo"]


class TestEntradaDelUsuario:
    def test_una_frase_vacia_no_llama_al_modelo(self):
        falso = modelo(BASE)
        resultado = interpret(None, "   ", falso)

        assert not resultado.ok
        assert falso.llamadas == [], "no se gastan tokens en una frase vacia"

    def test_una_frase_larguisima_se_rechaza_antes(self):
        falso = modelo(BASE)
        resultado = interpret(None, "a" * 5_000, falso)

        assert not resultado.ok
        assert falso.llamadas == []


# --------------------------------------------------------------------------
# Revision de un dia
# --------------------------------------------------------------------------

from app.services.interpret import interpret_revision  # noqa: E402

PARADAS = ["Museo Nacional", "Mirador del lago", "Cascada Los Tercios"]

SIN_CAMBIOS = {
    "earliest_start": None,
    "latest_end": None,
    "max_travel_km_per_day": None,
    "max_stops_per_day": None,
    "preferred_categories": None,
    "avoided_categories": None,
    "include_meals": None,
    "remove": [],
    "unmapped": [],
}


class TestRevision:
    def test_solo_viajan_los_campos_que_cambian(self):
        """Un valor donde no hubo pedido es un cambio que nadie pidio."""
        payload = {**SIN_CAMBIOS, "max_travel_km_per_day": 15}
        cambio = interpret_revision("menos carro", PARADAS, modelo(payload))

        assert cambio.changes == {"max_travel_km_per_day": 15.0}
        assert cambio.touches_anything

    def test_las_paradas_del_dia_van_en_el_contexto(self):
        falso = modelo(SIN_CAMBIOS)
        interpret_revision("sacá el museo", PARADAS, falso)

        contenido = falso.llamadas[0]["messages"][0]["content"]
        assert "Museo Nacional" in contenido
        assert "sacá el museo" in contenido

    def test_resuelve_un_nombre_parcial(self):
        payload = {**SIN_CAMBIOS, "remove": ["Museo Nacional"]}
        cambio = interpret_revision("sacá el museo", PARADAS, modelo(payload))

        assert cambio.remove == ["Museo Nacional"]

    def test_un_nombre_que_no_esta_en_el_dia_se_avisa(self):
        """Sacar 'el volcán' de un dia sin volcán es un malentendido, no un no-op."""
        payload = {**SIN_CAMBIOS, "remove": ["Volcán de Izalco"]}
        cambio = interpret_revision("sacá el volcán", PARADAS, modelo(payload))

        assert cambio.remove == []
        assert any("Volcán" in n for n in cambio.notes)

    def test_lo_que_no_se_puede_representar_vuelve(self):
        payload = {**SIN_CAMBIOS, "unmapped": ["se ve caro"]}
        cambio = interpret_revision("se ve caro", PARADAS, modelo(payload))

        assert cambio.unmapped == ["se ve caro"]
        assert not cambio.touches_anything, "sin cambio que aplicar, no se toca el dia"

    def test_recorta_un_valor_fuera_de_rango(self):
        payload = {**SIN_CAMBIOS, "max_stops_per_day": 40}
        cambio = interpret_revision("mucho más", PARADAS, modelo(payload))

        assert cambio.changes["max_stops_per_day"] == 12
        assert cambio.notes

    def test_json_invalido_no_revienta(self):
        cambio = interpret_revision("x", PARADAS, modelo(None, crudo="no puedo"))

        assert not cambio.ok
        assert "JSON" in cambio.error

    def test_un_mensaje_vacio_no_llama_al_modelo(self):
        falso = modelo(SIN_CAMBIOS)
        cambio = interpret_revision("  ", PARADAS, falso)

        assert not cambio.ok
        assert falso.llamadas == []
