"""Tests de la deduplicacion del catalogo.

Los duplicados son reales: en El Salvador OpenStreetMap tiene dos "Cascadas de
Huizucar" y dos variantes del mirador del volcan de Izalco. Sin unirlos, un
itinerario puede mandar al usuario dos veces al mismo lugar.

Corren contra la base de prueba con datos de ejemplo, sin tocar Overpass.
"""

import uuid

import pytest
from sqlalchemy import text

from alembic import command
from tests.test_migrations import alembic_config


@pytest.fixture
def base_con_esquema(clean_database):
    command.upgrade(alembic_config(), "head")
    # Segundo descarte del pool: la migracion recreo PostGIS y con ella el tipo
    # geography, que vuelve a cambiar de OID. Sin esto los operadores
    # espaciales fallan con "no spatial operator found".
    clean_database.dispose()
    return clean_database


def insertar(conexion, nombre, lat, lon, calidad=0.4):
    identificador = uuid.uuid4()
    conexion.execute(
        text("""
            INSERT INTO places
                (id, osm_type, osm_id, name, category, geom, lat, lon,
                 quality_score, is_active)
            VALUES
                (:id, 'node', :osm_id, :nombre, 'nature',
                 ST_GeogFromText(:punto), :lat, :lon, :calidad, true)
        """),
        {
            "id": identificador,
            "osm_id": abs(hash((nombre, lat, lon))) % 10_000_000_000,
            "nombre": nombre,
            "punto": f"SRID=4326;POINT({lon} {lat})",
            "lat": lat,
            "lon": lon,
            "calidad": calidad,
        },
    )
    return identificador


def ejecutar_dedupe(conexion, radio=150, umbral=0.55):
    conexion.execute(
        text("""
            UPDATE places
            SET duplicate_of = NULL,
                -- Solo se reactiva lo que estaba desactivado por duplicado.
                -- Un lugar rechazado por el filtro de calidad sigue fuera.
                is_active = CASE
                    WHEN rejected_reason IS NULL OR rejected_reason = 'duplicado'
                        THEN true
                    ELSE false
                END,
                rejected_reason = NULLIF(rejected_reason, 'duplicado')
            -- Mirar duplicate_of y no solo rejected_reason: una recarga previa
            -- pudo limpiar el motivo al reprocesar el lugar como aceptado,
            -- dejando duplicate_of huerfano y el registro activo a la vez.
            WHERE duplicate_of IS NOT NULL OR rejected_reason = 'duplicado'
        """)
    )
    return conexion.execute(
        text("""
            WITH pares AS (
                SELECT a.id AS perdedor, b.id AS ganador
                FROM places a
                JOIN places b
                  ON a.id <> b.id
                 AND a.is_active AND b.is_active
                 AND a.duplicate_of IS NULL AND b.duplicate_of IS NULL
                 AND ST_DWithin(a.geom, b.geom, :radio)
                 AND similarity(a.name, b.name) >= :umbral
                 AND (b.quality_score, b.id) > (a.quality_score, a.id)
            )
            UPDATE places
            SET duplicate_of = pares.ganador,
                is_active = false,
                rejected_reason = 'duplicado'
            FROM pares
            WHERE places.id = pares.perdedor
        """),
        {"radio": radio, "umbral": umbral},
    ).rowcount


def activos(conexion) -> int:
    return conexion.execute(text("SELECT COUNT(*) FROM places WHERE is_active")).scalar()


def test_une_el_mismo_lugar_escrito_distinto(base_con_esquema):
    """Caso real: dos variantes del mirador del volcan de Izalco."""
    with base_con_esquema.begin() as conexion:
        insertar(conexion, "Mirador al Volcan de Izalco", 13.8134, -89.6331)
        insertar(conexion, "Mirador Volcán de Izalco", 13.8135, -89.6332, calidad=0.7)
        assert ejecutar_dedupe(conexion) == 1
        assert activos(conexion) == 1


def test_gana_el_registro_con_mas_informacion(base_con_esquema):
    with base_con_esquema.begin() as conexion:
        pobre = insertar(conexion, "Cascadas de Huizucar", 13.6100, -89.2050, calidad=0.4)
        rico = insertar(conexion, "Cascadas de Huizucar", 13.6101, -89.2051, calidad=0.9)
        ejecutar_dedupe(conexion)

        sobreviviente = conexion.execute(
            text("SELECT id FROM places WHERE is_active")
        ).scalar()
        assert sobreviviente == rico

        apunta_a = conexion.execute(
            text("SELECT duplicate_of FROM places WHERE id = :id"), {"id": pobre}
        ).scalar()
        assert apunta_a == rico


def test_no_une_nombres_iguales_en_municipios_distintos(base_con_esquema):
    """La cercania es tan necesaria como el nombre.

    Todos los municipios tienen un "Parque Central" y son lugares distintos.
    Deduplicar solo por nombre los fundiria en uno.
    """
    with base_con_esquema.begin() as conexion:
        insertar(conexion, "Parque Central", 13.6929, -89.2182)  # San Salvador
        insertar(conexion, "Parque Central", 13.9942, -89.5597)  # Santa Ana
        assert ejecutar_dedupe(conexion) == 0
        assert activos(conexion) == 2


def test_no_une_negocios_distintos_de_la_misma_cuadra(base_con_esquema):
    with base_con_esquema.begin() as conexion:
        insertar(conexion, "Pupuseria La Ceiba", 13.6929, -89.2182)
        insertar(conexion, "Restaurante El Zocalo", 13.6930, -89.2183)
        assert ejecutar_dedupe(conexion) == 0
        assert activos(conexion) == 2


def test_es_idempotente(base_con_esquema):
    """El bug que dejo el catalogo inconsistente.

    Correr el cargador dos veces reactivaba los duplicados sin volver a
    marcarlos, dejando lugares activos y marcados como duplicados a la vez.
    """
    with base_con_esquema.begin() as conexion:
        insertar(conexion, "Cascada Los Tercios", 13.7300, -88.9300)
        insertar(conexion, "Cascada Los Tercios", 13.7301, -88.9301, calidad=0.8)

        primera = ejecutar_dedupe(conexion)
        activos_primera = activos(conexion)

        segunda = ejecutar_dedupe(conexion)
        activos_segunda = activos(conexion)

        assert primera == segunda == 1
        assert activos_primera == activos_segunda == 1

        # Nadie puede estar activo y marcado como duplicado al mismo tiempo.
        inconsistentes = conexion.execute(
            text("SELECT COUNT(*) FROM places WHERE is_active AND duplicate_of IS NOT NULL")
        ).scalar()
        assert inconsistentes == 0


def test_una_cadena_de_tres_deja_uno_solo(base_con_esquema):
    with base_con_esquema.begin() as conexion:
        insertar(conexion, "Playa El Tunco", 13.4940, -89.3830, calidad=0.3)
        insertar(conexion, "Playa El Tunco", 13.4941, -89.3831, calidad=0.5)
        insertar(conexion, "Playa el Tunco", 13.4942, -89.3832, calidad=0.9)
        ejecutar_dedupe(conexion)
        assert activos(conexion) == 1


def test_repara_el_estado_corrupto_de_una_recarga(base_con_esquema):
    """El caso que dejo 207 registros activos y marcados como duplicados.

    Una recarga previa reprocesaba el lugar como aceptado y le borraba el
    motivo, pero dejaba duplicate_of apuntando a otro registro. El reinicio
    buscaba por motivo, no encontraba nada, y la inconsistencia sobrevivia a
    cada nueva corrida.
    """
    with base_con_esquema.begin() as conexion:
        ganador = insertar(conexion, "Lago de Coatepeque", 13.8700, -89.5500, calidad=0.9)
        huerfano = insertar(conexion, "Lago de Coatepeque", 13.8701, -89.5501, calidad=0.4)

        # Estado corrupto: activo y con duplicate_of, sin motivo.
        conexion.execute(
            text("""
                UPDATE places
                SET duplicate_of = :ganador, is_active = true, rejected_reason = NULL
                WHERE id = :huerfano
            """),
            {"ganador": ganador, "huerfano": huerfano},
        )

        ejecutar_dedupe(conexion)

        inconsistentes = conexion.execute(
            text("SELECT COUNT(*) FROM places WHERE is_active AND duplicate_of IS NOT NULL")
        ).scalar()
        assert inconsistentes == 0
        assert activos(conexion) == 1


def test_el_reinicio_no_resucita_lo_rechazado_por_calidad(base_con_esquema):
    """Reactivar todo al reiniciar meteria basura de vuelta al catalogo."""
    with base_con_esquema.begin() as conexion:
        malo = insertar(conexion, "Mirador", 13.7000, -89.2000)
        conexion.execute(
            text("""
                UPDATE places
                SET is_active = false, rejected_reason = 'nombre_generico'
                WHERE id = :id
            """),
            {"id": malo},
        )

        ejecutar_dedupe(conexion)

        sigue_fuera = conexion.execute(
            text("SELECT is_active FROM places WHERE id = :id"), {"id": malo}
        ).scalar()
        assert sigue_fuera is False
