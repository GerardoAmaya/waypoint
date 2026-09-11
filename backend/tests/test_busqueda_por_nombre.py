"""Tests de buscar un lugar por como la gente lo llama.

El reporte que los motiva: alguien escribió "Multiplaza San Salvador" y recibió
que no estaba en el catálogo. Sí estaba, como "Centro Comercial Multiplaza",
activo. `similarity` compara las cadenas enteras, así que el nombre correcto
ocupaba un tercio del texto y el resto contaba como diferencia: 0,41 contra un
umbral de 0,60.

Se prueba contra la base y no con dobles porque lo que se está probando es la
consulta: `word_similarity` y `unaccent` viven en Postgres, y un doble
comprobaría el doble.
"""

import uuid

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.geocode import buscar_lugar
from tests.test_migrations import alembic_config


@pytest.fixture
def sesion(clean_database):
    command.upgrade(alembic_config(), "head")
    clean_database.dispose()
    with Session(clean_database) as sesion:
        yield sesion


def insertar(conexion, nombre, categoria="attraction", calidad=0.6):
    conexion.execute(
        text("""
            INSERT INTO places
                (id, osm_type, osm_id, name, category, geom, lat, lon,
                 quality_score, is_active)
            VALUES
                (:id, 'node', :osm_id, :nombre, :categoria,
                 ST_GeogFromText('SRID=4326;POINT(-89.22 13.70)'), 13.70, -89.22,
                 :calidad, true)
        """),
        {
            "id": uuid.uuid4(),
            "osm_id": abs(hash(nombre)) % 10_000_000_000,
            "nombre": nombre,
            "categoria": categoria,
            "calidad": calidad,
        },
    )


@pytest.fixture
def catalogo(sesion):
    """Los nombres reales que hicieron falta para encontrar cada fallo."""
    conexion = sesion.connection()
    for nombre, categoria in [
        ("Centro Comercial Multiplaza", "attraction"),
        ("Centro Comercial Galerías", "attraction"),
        ("Go Green Galerias", "food"),
        ("Centro Comercial Las Cascadas", "attraction"),
        ("7 cascadas", "nature"),
        ("Metrocentro", "attraction"),
        ("Metrocentro Santa Ana", "attraction"),
        ("Metrocentro San Miguel", "attraction"),
        ("Hotel Barceló", "lodging"),
        ("Parque Central de California", "nature"),
        ("Volcán de Santa Ana", "nature"),
        ("Volcán de Izalco", "nature"),
    ]:
        insertar(conexion, nombre, categoria)
    sesion.flush()
    return sesion


class TestElNombreCortoEncuentraElLargo:
    """El fallo del reporte: el nombre con el que se conoce un sitio."""

    def test_multiplaza_encuentra_el_centro_comercial(self, catalogo):
        assert buscar_lugar(catalogo, "Multiplaza").hit.name == "Centro Comercial Multiplaza"

    def test_con_la_ciudad_pegada_tambien(self, catalogo):
        """El caso literal del reporte."""
        encontrado = buscar_lugar(catalogo, "Multiplaza San Salvador").hit

        assert encontrado.name == "Centro Comercial Multiplaza"

    def test_las_tildes_no_hacen_falta(self, catalogo):
        assert buscar_lugar(catalogo, "Volcan de Santa Ana").hit.name == "Volcán de Santa Ana"
        assert buscar_lugar(catalogo, "Hotel Barcelo").hit.name == "Hotel Barceló"


class TestLoQueYaFuncionabaSigueIgual:
    """La primera pasada no se tocó, y estos lo sujetan."""

    def test_el_nombre_completo_gana(self, catalogo):
        assert buscar_lugar(catalogo, "Metrocentro").hit.name == "Metrocentro"

    def test_un_nombre_mas_especifico_no_se_recorta(self, catalogo):
        """ "Metrocentro Santa Ana" existe tal cual.

        Es la razón de que quitar el nombre de la zona sea el último recurso y
        no el primero: recortándolo de entrada, esto quedaría ambiguo entre los
        tres Metrocentros.
        """
        assert (
            buscar_lugar(catalogo, "Metrocentro Santa Ana").hit.name == "Metrocentro Santa Ana"
        )


class TestNoSustituyeCuandoNoSabe:
    """La regla del proyecto: se dice, no se sustituye."""

    def test_un_empate_no_se_resuelve_a_dedo(self, catalogo):
        """ "Galerías" es el centro comercial y también un local que está dentro.

        Los dos encajan perfecto, así que elegir por calidad sería exactamente
        la sustitución silenciosa que el resto del módulo evita.
        """
        resultado = buscar_lugar(catalogo, "Galerias")

        assert resultado.hit is None
        assert {s.name for s in resultado.sugerencias} == {
            "Centro Comercial Galerías",
            "Go Green Galerias",
        }

    def test_un_mal_candidato_solo_tampoco_pasa(self, catalogo):
        """ "Hotel California de Santa Ana" no existe.

        Al quitarle la zona queda "hotel california de", y eso pesca "Parque
        Central de California" por una palabra, sin nadie que le dispute el
        puesto: el margen de desempate no lo veía. Lo ataja el encaje mínimo.
        """
        resultado = buscar_lugar(catalogo, "Hotel California de Santa Ana")

        assert resultado.hit is None
        assert resultado.sugerencias == []

    def test_un_nombre_que_no_esta_no_inventa_nada(self, catalogo):
        resultado = buscar_lugar(catalogo, "Restaurante que no existe")

        assert resultado.hit is None
        assert resultado.sugerencias == []


class TestLasSugerenciasSonUtiles:
    def test_ofrece_el_de_verdad_y_no_solo_los_que_riman(self, catalogo):
        """A "Metrocentro San Salvador" se le ofrecían los Metrocentros de San
        Miguel y Santa Ana —los que se parecen a la frase entera— y no el
        "Metrocentro" a secas, que es el de San Salvador y el que se buscaba."""
        resultado = buscar_lugar(catalogo, "Metrocentro San Salvador")

        assert resultado.hit is None
        assert "Metrocentro" in {s.name for s in resultado.sugerencias}

    def test_no_sugiere_cualquier_cosa(self, catalogo):
        """Una sugerencia equivocada es peor que ninguna: manda a la persona a
        escribir un nombre que no quería."""
        resultado = buscar_lugar(catalogo, "Hotel California de Santa Ana")

        assert "Parque Central de California" not in {s.name for s in resultado.sugerencias}
