"""Tests del filtro de calidad del catalogo.

Los casos salen de la muestra real de El Salvador que devolvio Overpass, no de
ejemplos inventados: los nombres que aparecen aqui existen en los datos.
"""

import pytest

from app.models import Category
from app.services.places_quality import (
    classify,
    evaluate,
    normalize,
    score_quality,
)


class TestClassify:
    @pytest.mark.parametrize(
        "tags,esperada",
        [
            ({"tourism": "viewpoint"}, Category.viewpoint),
            ({"tourism": "museum"}, Category.culture),
            ({"tourism": "attraction"}, Category.attraction),
            ({"tourism": "hotel"}, Category.lodging),
            ({"historic": "ruins"}, Category.culture),
            ({"amenity": "restaurant"}, Category.food),
            ({"amenity": "marketplace"}, Category.food),
            ({"natural": "volcano"}, Category.nature),
            ({"natural": "beach"}, Category.nature),
            ({"leisure": "nature_reserve"}, Category.nature),
            ({"waterway": "waterfall"}, Category.nature),
        ],
    )
    def test_asigna_la_categoria_correcta(self, tags, esperada):
        resultado = classify(tags)
        assert resultado is not None
        assert resultado[0] is esperada

    def test_lo_no_turistico_no_se_clasifica(self):
        assert classify({"amenity": "bank"}) is None
        assert classify({"shop": "supermarket"}) is None
        assert classify({"highway": "bus_stop"}) is None

    def test_historic_acepta_cualquier_valor(self):
        """La regla sin valores acepta todo lo etiquetado como historico."""
        for valor in ("monument", "memorial", "archaeological_site", "castle"):
            resultado = classify({"historic": valor})
            assert resultado == (Category.culture, valor)


class TestRechazos:
    """Cada caso viene de basura encontrada en los datos reales."""

    @pytest.mark.parametrize(
        "nombre,motivo",
        [
            ("Mirador", "nombre_generico"),
            ("El Museo", "nombre_generico"),
            ("Cascada", "nombre_generico"),
            ("Panorámico", "nombre_generico"),
            ("Letrero de Sonsonate", "no_es_destino"),
            ("Deslave de las Colinas 2001", "no_es_destino"),
            ("Acceso Desprendimiento de las Colinas", "no_es_destino"),
            ("Río", "nombre_muy_corto"),
            ("", "sin_nombre"),
            ("2001", "nombre_sin_letras"),
        ],
    )
    def test_descarta_con_motivo(self, nombre, motivo):
        v = evaluate({"name": nombre, "tourism": "attraction"})
        assert not v.accepted
        assert v.reason == motivo

    def test_descarta_categoria_no_soportada(self):
        v = evaluate({"name": "Banco Agrícola Centro", "amenity": "bank"})
        assert not v.accepted
        assert v.reason == "categoria_no_soportada"

    def test_el_nombre_generico_ignora_acentos_y_mayusculas(self):
        for variante in ("MIRADOR", "mirador", "Mirador", "Miradór"):
            assert not evaluate({"name": variante, "tourism": "viewpoint"}).accepted


class TestAceptados:
    """Lugares reales de El Salvador que deben entrar."""

    @pytest.mark.parametrize(
        "nombre,tags,categoria",
        [
            ("Mirador de la Cruz de Ataco", {"tourism": "attraction"}, Category.attraction),
            ("Salto Malacatiupán", {"tourism": "attraction"}, Category.attraction),
            ("Parque El Imposible", {"leisure": "nature_reserve"}, Category.nature),
            ("Museo de la Revolución", {"tourism": "museum"}, Category.culture),
            ("Cascada Los Tercios", {"waterway": "waterfall"}, Category.nature),
            ("Volcán de Izalco", {"natural": "volcano"}, Category.nature),
            ("Apaneca Canopy Tour", {"tourism": "attraction"}, Category.attraction),
        ],
    )
    def test_acepta_lugares_reales(self, nombre, tags, categoria):
        v = evaluate({"name": nombre, **tags})
        assert v.accepted, f"Se rechazo un lugar valido: {nombre}"
        assert v.category is categoria
        assert 0 < v.score <= 1

    def test_un_nombre_generico_con_apellido_si_pasa(self):
        """ "Mirador" solo se rechaza; "Mirador de Juayúa" identifica un lugar."""
        assert evaluate({"name": "Mirador de Juayúa", "tourism": "viewpoint"}).accepted


class TestPuntaje:
    def test_mas_informacion_da_mas_puntaje(self):
        minimo = score_quality({"name": "X"}, Category.culture)
        completo = score_quality(
            {
                "name": "X",
                "opening_hours": "Mo-Su 09:00-17:00",
                "website": "https://ejemplo.sv",
                "phone": "+503 2222 2222",
                "wikipedia": "es:X",
                "addr:city": "Santa Ana",
            },
            Category.culture,
        )
        assert completo > minimo
        assert completo <= 1.0

    def test_el_puntaje_nunca_pasa_de_uno(self):
        todo = {
            "opening_hours": "x",
            "website": "x",
            "phone": "x",
            "description": "x",
            "wikipedia": "x",
            "addr:city": "x",
            "addr:street": "x",
            "cuisine": "pupusas",
        }
        assert score_quality(todo, Category.food) <= 1.0


def test_normalize_ignora_acentos_mayusculas_y_puntuacion():
    assert normalize("Volcán de Izalco") == normalize("VOLCAN DE IZALCO")
    # La puntuacion se vuelve espacio y los espacios se colapsan: sin eso,
    # "Cafe, S.A." quedaria con huecos dobles y no compararia igual.
    assert normalize("Café,  S.A.") == "cafe s a"
    assert normalize("  Parque   El   Imposible  ") == "parque el imposible"


class TestNombresQueSonDescripciones:
    """En OSM el campo name se usa a veces como texto libre.

    El caso real: "Feria Gastronomica sàbado y domingo 0800 a 1700" entro al
    catalogo y termino como parada de un itinerario.
    """

    @pytest.mark.parametrize(
        "nombre",
        [
            "Feria Gastronomica sàbado y domingo 0800 a 1700",
            "Restaurante abierto de 8:00 a 17:00",
            "Comedor abierto lunes a viernes",
            "Tour 0900 a 1600",
            "Cafe domingo 0800",
        ],
    )
    def test_rechaza_los_horarios_metidos_en_el_nombre(self, nombre):
        veredicto = evaluate({"name": nombre, "tourism": "attraction"})

        assert not veredicto.accepted
        assert veredicto.reason == "nombre_es_horario"

    @pytest.mark.parametrize(
        "nombre",
        [
            # Igual de largo que la basura, pero es un nombre de verdad. Por eso
            # la regla mira el horario y no cuenta palabras.
            "Finca y Mirador La Providencia de Concepción de Ataco",
            "Hotel Villa Serena 2",
            "Ruta 5 Cafe",
            "Parque Nacional El Imposible",
        ],
    )
    def test_no_se_lleva_puesto_un_nombre_largo_legitimo(self, nombre):
        assert evaluate({"name": nombre, "tourism": "attraction"}).accepted

    def test_detecta_la_hora_aunque_lleve_acento_raro(self):
        """normalize() borra los dos puntos, asi que la hora se busca aparte."""
        veredicto = evaluate({"name": "Museo sábado 9:00", "tourism": "museum"})
        assert veredicto.reason == "nombre_es_horario"

    @pytest.mark.parametrize(
        "nombre",
        [
            "Hostal Villa Santo Domingo",
            "Cerro Santo Domingo",
            "Hostal Las Terrazas de Santo Domingo",
            "Iglesia Santo Domingo de Guzman",
            "Restaurante Los Martes",
        ],
    )
    def test_un_dia_suelto_no_es_evidencia_de_horario(self, nombre):
        """La primera version se llevaba medio santoral por delante.

        En un pais catolico "Santo Domingo" esta en todos lados. Rechazar por
        contener un dia de la semana borraba lugares reales, y lo encontro la
        corrida en seco de refilter_places antes de escribir nada.
        """
        assert evaluate({"name": nombre, "tourism": "attraction"}).accepted


class TestGenericosQueFaltaban:
    @pytest.mark.parametrize(
        "nombre", ["Piscina", "Turicentro", "Balneario", "Cerro", "Ruinas", "Cementerio"]
    )
    def test_rechaza_los_genericos_nuevos(self, nombre):
        veredicto = evaluate({"name": nombre, "tourism": "attraction"})

        assert not veredicto.accepted
        assert veredicto.reason == "nombre_generico"

    @pytest.mark.parametrize(
        "nombre", ["Balneario Atzumpa", "Cerro Las Ninfas", "Ruinas de Tazumal"]
    )
    def test_el_generico_con_apellido_si_entra(self, nombre):
        assert evaluate({"name": nombre, "tourism": "attraction"}).accepted
