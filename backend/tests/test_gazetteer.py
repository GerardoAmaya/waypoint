"""El nomenclator: nombres de lugar, separados de los puntos de interes.

El fallo que lo justifica es concreto: "vivo en Mejicanos" no resolvia nada,
porque lo unico llamado Mejicanos en el catalogo son cuatro puestos de comida y
el motor —con razon— se niega a anclar un viaje en un cafe. Mejicanos no es un
destino, es un lugar donde la gente vive.

Los tests puros del cargador no tocan la red ni la base. Los de resolucion
corren contra la base de prueba con unas pocas filas insertadas a mano.
"""

import uuid

import pytest
from alembic import command
from sqlalchemy import text

from scripts.load_gazetteer import (
    MIN_DESTINOS,
    RADIO_MAX_KM,
    RADIO_MIN_KM,
    _radio_del_recuadro_km,
    parse_elements,
)
from tests.test_migrations import alembic_config


class TestRadioDelLimite:
    """El radio sale de la geometria y no de una constante.

    Un departamento y un barrio no se recorren igual: medido sobre los limites
    de El Salvador, la mediana da 37.8 km de radio para un departamento y 7.3
    para un municipio.
    """

    def test_un_recuadro_mas_grande_da_mas_radio(self):
        chico = {"minlat": 13.70, "maxlat": 13.75, "minlon": -89.25, "maxlon": -89.20}
        grande = {"minlat": 13.50, "maxlat": 14.00, "minlon": -89.60, "maxlon": -89.10}

        assert _radio_del_recuadro_km(grande) > _radio_del_recuadro_km(chico)

    def test_el_radio_es_media_diagonal(self):
        # Un grado de latitud son ~110.6 km; medio grado de alto y nada de
        # ancho da una diagonal de ~55.3 km y un radio de ~27.6.
        recuadro = {"minlat": 13.0, "maxlat": 13.5, "minlon": -89.0, "maxlon": -89.0}

        assert _radio_del_recuadro_km(recuadro) == pytest.approx(27.6, abs=0.3)


class TestLecturaDeOverpass:
    def test_un_limite_administrativo_usa_su_recuadro(self):
        elementos = [
            {
                "type": "relation",
                "id": 1,
                "tags": {"name": "Ahuachapan", "admin_level": "6"},
                "bounds": {
                    "minlat": 13.85,
                    "maxlat": 14.00,
                    "minlon": -89.90,
                    "maxlon": -89.75,
                },
            }
        ]

        [candidato] = parse_elements(elementos)

        assert candidato.kind == "admin6"
        assert candidato.name == "Ahuachapan"
        # El centro es el del recuadro.
        assert candidato.lat == pytest.approx(13.925)
        assert RADIO_MIN_KM * 1000 <= candidato.radius_m <= RADIO_MAX_KM * 1000

    def test_un_lugar_suelto_usa_el_radio_de_su_tipo(self):
        """Los nodos place=* no traen recuadro del que sacar el tamano."""
        elementos = [
            {
                "type": "node",
                "id": 2,
                "lat": 13.72,
                "lon": -89.19,
                "tags": {"name": "Mejicanos", "place": "town"},
            }
        ]

        [candidato] = parse_elements(elementos)

        assert candidato.kind == "town"
        assert candidato.radius_m == 8000

    def test_un_barrio_busca_en_menos_radio_que_un_pueblo(self):
        barrio = parse_elements(
            [
                {
                    "type": "node",
                    "id": 3,
                    "lat": 13.7,
                    "lon": -89.2,
                    "tags": {"name": "Barrio", "place": "neighbourhood"},
                }
            ]
        )[0]
        pueblo = parse_elements(
            [
                {
                    "type": "node",
                    "id": 4,
                    "lat": 13.7,
                    "lon": -89.2,
                    "tags": {"name": "Pueblo", "place": "town"},
                }
            ]
        )[0]

        assert barrio.radius_m < pueblo.radius_m

    def test_el_pais_entero_no_es_un_nombre_util(self):
        """admin_level=2 es El Salvador: centrar ahi no acota nada."""
        elementos = [
            {
                "type": "relation",
                "id": 5,
                "tags": {"name": "El Salvador", "admin_level": "2"},
                "bounds": {
                    "minlat": 13.1,
                    "maxlat": 14.5,
                    "minlon": -90.2,
                    "maxlon": -87.6,
                },
            }
        ]

        assert parse_elements(elementos) == []

    def test_sin_nombre_no_entra(self):
        elementos = [
            {
                "type": "node",
                "id": 6,
                "lat": 13.7,
                "lon": -89.2,
                "tags": {"place": "neighbourhood"},
            },
            {
                "type": "node",
                "id": 7,
                "lat": 13.7,
                "lon": -89.2,
                "tags": {"name": "   ", "place": "town"},
            },
        ]

        assert parse_elements(elementos) == []

    def test_el_radio_se_recorta_por_arriba(self):
        """Un departamento entero no puede buscar candidatos a 50 km."""
        elementos = [
            {
                "type": "relation",
                "id": 8,
                "tags": {"name": "Departamento", "admin_level": "4"},
                "bounds": {
                    "minlat": 13.0,
                    "maxlat": 14.4,
                    "minlon": -90.1,
                    "maxlon": -88.5,
                },
            }
        ]

        [candidato] = parse_elements(elementos)

        assert candidato.radius_m == int(RADIO_MAX_KM * 1000)


@pytest.fixture
def base_con_nomenclator(clean_database):
    command.upgrade(alembic_config(), "head")
    clean_database.dispose()
    return clean_database


def insertar_nombre(conexion, nombre, kind, lat, lon, radio_m, destinos=20, activo=True):
    conexion.execute(
        text("""
            INSERT INTO place_names
                (id, osm_type, osm_id, name, kind, lat, lon, geom, radius_m,
                 destinations_nearby, is_active)
            VALUES
                (:id, 'node', :osm_id, :nombre, :kind, :lat, :lon,
                 ST_GeogFromText(:punto), :radio, :destinos, :activo)
        """),
        {
            "id": uuid.uuid4(),
            "osm_id": abs(hash((nombre, kind))) % 10_000_000,
            "nombre": nombre,
            "kind": kind,
            "lat": lat,
            "lon": lon,
            "punto": f"SRID=4326;POINT({lon} {lat})",
            "radio": radio_m,
            "destinos": destinos,
            "activo": activo,
        },
    )


class TestResolucionConNomenclator:
    def test_resuelve_un_municipio_que_no_es_zona_curada(self, base_con_nomenclator):
        """El caso que motivo todo: Mejicanos no estaba en ninguna parte."""
        from app.services.geocode import find_place_name

        with base_con_nomenclator.begin() as conexion:
            insertar_nombre(conexion, "Mejicanos", "town", 13.7225, -89.1870, 8000)

        from sqlalchemy.orm import Session

        with Session(base_con_nomenclator) as db:
            area = find_place_name(db, "Mejicanos")

        assert area is not None
        assert area.name == "Mejicanos"
        assert area.source == "gazetteer"
        # El radio viene del nomenclator, no de un valor por defecto.
        assert area.radius_m == 8000

    def test_gana_el_nombre_mas_especifico(self, base_con_nomenclator):
        """ "San Salvador" es departamento, municipio y ciudad a la vez.

        Quien lo nombra piensa en la ciudad, no en los treinta y cinco
        kilometros de radio del departamento.
        """
        from sqlalchemy.orm import Session

        from app.services.geocode import find_place_name

        with base_con_nomenclator.begin() as conexion:
            insertar_nombre(conexion, "Cuscatlan", "admin4", 13.8, -89.0, 35000)
            insertar_nombre(conexion, "Cuscatlan", "city", 13.7, -89.1, 12000)

        with Session(base_con_nomenclator) as db:
            area = find_place_name(db, "Cuscatlan")

        assert area is not None
        assert area.radius_m == 12000, "gano el departamento en vez de la ciudad"

    def test_un_nombre_marcado_no_se_ofrece(self, base_con_nomenclator):
        """Los pobres se guardan para poder medir el filtro, no para usarlos."""
        from sqlalchemy.orm import Session

        from app.services.geocode import find_place_name

        with base_con_nomenclator.begin() as conexion:
            insertar_nombre(
                conexion,
                "Caserio Vacio",
                "village",
                13.9,
                -88.5,
                5000,
                destinos=1,
                activo=False,
            )

        with Session(base_con_nomenclator) as db:
            assert find_place_name(db, "Caserio Vacio") is None

    def test_aguanta_un_error_de_escritura_pero_no_una_palabra_generica(
        self, base_con_nomenclator
    ):
        """El umbral esta medido y el margen es de cuatro centesimas.

        "Megicanos" se parece a "Mejicanos" en 0.538 y hay que aceptarlo;
        "volcan" se parece a "Volcancillo" en 0.462 y hay que rechazarlo.
        """
        from sqlalchemy.orm import Session

        from app.services.geocode import find_place_name

        with base_con_nomenclator.begin() as conexion:
            insertar_nombre(conexion, "Mejicanos", "town", 13.72, -89.19, 8000)
            insertar_nombre(conexion, "Volcancillo", "village", 13.9, -89.5, 5000)

        with Session(base_con_nomenclator) as db:
            assert find_place_name(db, "Megicanos") is not None
            assert find_place_name(db, "volcan") is None

    def test_un_nombre_que_no_existe_no_se_inventa(self, base_con_nomenclator):
        from sqlalchemy.orm import Session

        from app.services.geocode import find_place_name

        with base_con_nomenclator.begin() as conexion:
            insertar_nombre(conexion, "Mejicanos", "town", 13.72, -89.19, 8000)

        with Session(base_con_nomenclator) as db:
            assert find_place_name(db, "asdfghjkl") is None


def test_el_umbral_de_destinos_es_el_minimo_para_un_dia():
    """Cuatro paradas es el minimo con el que un dia tiene forma de dia."""
    assert MIN_DESTINOS == 4
