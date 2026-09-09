"""Tests de las consultas espaciales.

Usan coordenadas reales de El Salvador para que las distancias esperadas sean
verificables contra el mundo, no contra numeros inventados.
"""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Category
from app.services.places import (
    catalog_stats,
    distance_between,
    search_by_name,
    search_in_area,
    search_nearby,
)
from tests.test_dedupe import insertar
from tests.test_migrations import alembic_config

# Puntos reales, para poder contrastar distancias con la realidad.
SAN_SALVADOR = (13.6929, -89.2182)
SANTA_ANA = (13.9942, -89.5597)  # a unos 55 km de San Salvador


@pytest.fixture
def sesion(clean_database):
    command.upgrade(alembic_config(), "head")
    clean_database.dispose()
    with Session(clean_database) as sesion:
        yield sesion


def sembrar(sesion: Session) -> dict[str, object]:
    """Un catalogo pequeno alrededor de San Salvador."""
    lat, lon = SAN_SALVADOR
    conexion = sesion.connection()
    ids = {
        # A pocos cientos de metros
        "pupuseria": insertar(conexion, "Pupuseria Olocuilta", lat + 0.002, lon, 0.6),
        "museo": insertar(conexion, "Museo Nacional de Antropologia", lat, lon + 0.003, 0.9),
        "mirador": insertar(conexion, "Mirador de los Planes", lat + 0.004, lon, 0.5),
        # A unos 3 km
        "parque": insertar(conexion, "Parque Cuscatlan", lat + 0.027, lon, 0.7),
        # A 55 km, en Santa Ana
        "lejano": insertar(conexion, "Catedral de Santa Ana", *SANTA_ANA, 0.8),
        # Alojamiento, que no debe salir por defecto
        "hotel": insertar(conexion, "Hotel Real Intercontinental", lat, lon + 0.001, 0.9),
    }
    conexion.execute(
        text("UPDATE places SET category = 'lodging' WHERE id = :id"),
        {"id": ids["hotel"]},
    )
    conexion.execute(
        text("UPDATE places SET category = 'food' WHERE id = :id"),
        {"id": ids["pupuseria"]},
    )
    conexion.execute(
        text("UPDATE places SET category = 'culture' WHERE id IN (:a, :b)"),
        {"a": ids["museo"], "b": ids["lejano"]},
    )
    conexion.execute(
        text("UPDATE places SET category = 'viewpoint' WHERE id = :id"),
        {"id": ids["mirador"]},
    )
    sesion.commit()
    return ids


class TestBusquedaPorRadio:
    def test_devuelve_solo_lo_que_esta_dentro(self, sesion):
        sembrar(sesion)
        resultados = search_nearby(sesion, *SAN_SALVADOR, radius_m=1_000)
        nombres = {r.name for r in resultados}

        assert "Museo Nacional de Antropologia" in nombres
        assert "Catedral de Santa Ana" not in nombres, "Santa Ana esta a 55 km"

    def test_ordena_del_mas_cercano_al_mas_lejano(self, sesion):
        sembrar(sesion)
        resultados = search_nearby(sesion, *SAN_SALVADOR, radius_m=50_000)
        distancias = [r.distance_m for r in resultados]
        assert distancias == sorted(distancias)

    def test_la_distancia_devuelta_es_verosimil(self, sesion):
        """Parque Cuscatlan quedo a 0.027 grados de latitud, unos 3 km."""
        sembrar(sesion)
        resultados = search_nearby(sesion, *SAN_SALVADOR, radius_m=10_000)
        parque = next(r for r in resultados if r.name == "Parque Cuscatlan")
        assert 2_500 < parque.distance_m < 3_500

    def test_excluye_alojamiento_por_defecto(self, sesion):
        sembrar(sesion)
        resultados = search_nearby(sesion, *SAN_SALVADOR, radius_m=5_000)
        assert all(r.category != "lodging" for r in resultados)

    def test_incluye_alojamiento_si_se_pide(self, sesion):
        sembrar(sesion)
        resultados = search_nearby(sesion, *SAN_SALVADOR, radius_m=5_000, include_lodging=True)
        assert any(r.category == "lodging" for r in resultados)

    def test_pedir_lodging_explicito_lo_devuelve(self, sesion):
        """Pedirlo a proposito es distinto de que se cuele en una busqueda."""
        sembrar(sesion)
        resultados = search_nearby(
            sesion, *SAN_SALVADOR, radius_m=5_000, categories=[Category.lodging]
        )
        assert len(resultados) == 1
        assert resultados[0].category == "lodging"

    def test_filtra_por_categoria(self, sesion):
        sembrar(sesion)
        resultados = search_nearby(
            sesion, *SAN_SALVADOR, radius_m=50_000, categories=[Category.culture]
        )
        assert {r.category for r in resultados} == {"culture"}

    def test_filtra_por_calidad_minima(self, sesion):
        sembrar(sesion)
        resultados = search_nearby(sesion, *SAN_SALVADOR, radius_m=50_000, min_quality=0.75)
        assert all(r.quality_score >= 0.75 for r in resultados)

    def test_respeta_el_limite(self, sesion):
        sembrar(sesion)
        assert len(search_nearby(sesion, *SAN_SALVADOR, radius_m=50_000, limit=2)) == 2

    def test_los_inactivos_no_aparecen(self, sesion):
        ids = sembrar(sesion)
        sesion.execute(
            text("UPDATE places SET is_active = false WHERE id = :id"),
            {"id": ids["museo"]},
        )
        sesion.commit()
        resultados = search_nearby(sesion, *SAN_SALVADOR, radius_m=5_000)
        assert all(r.name != "Museo Nacional de Antropologia" for r in resultados)


class TestBusquedaPorArea:
    def test_reparte_el_cupo_entre_categorias(self, sesion):
        """Sin reparto, la categoria mas numerosa se lleva todo el resultado."""
        lat, lon = SAN_SALVADOR
        conexion = sesion.connection()
        for i in range(15):
            identificador = insertar(
                conexion, f"Comedor Numero {i}", lat, lon + i * 0.0001, 0.5
            )
            conexion.execute(
                text("UPDATE places SET category = 'food' WHERE id = :id"),
                {"id": identificador},
            )
        museo = insertar(conexion, "Museo Nacional", lat, lon + 0.002, 0.9)
        conexion.execute(
            text("UPDATE places SET category = 'culture' WHERE id = :id"),
            {"id": museo},
        )
        sesion.commit()

        resultados = search_in_area(sesion, lat, lon, radius_m=5_000, per_category=3)
        por_categoria = {}
        for r in resultados:
            por_categoria.setdefault(r.category, []).append(r)

        assert len(por_categoria["food"]) == 3, "El cupo por categoria no se respeto"
        assert "culture" in por_categoria, "El museo quedo fuera pese a ser el unico"


class TestBusquedaPorNombre:
    def test_encuentra_con_el_nombre_completo(self, sesion):
        sembrar(sesion)
        resultados = search_by_name(sesion, "Museo Nacional de Antropologia")
        assert resultados[0].name == "Museo Nacional de Antropologia"

    def test_tolera_errores_de_escritura(self, sesion):
        sembrar(sesion)
        resultados = search_by_name(sesion, "Museo Nacional Antropologia", min_similarity=0.4)
        assert any("Antropologia" in r.name for r in resultados)

    def test_no_devuelve_nada_sin_parecido(self, sesion):
        sembrar(sesion)
        assert search_by_name(sesion, "Torre Eiffel") == []


class TestDistanciaYEstadisticas:
    def test_la_distancia_entre_dos_lugares_es_correcta(self, sesion):
        ids = sembrar(sesion)
        metros = distance_between(sesion, ids["museo"], ids["lejano"])
        # San Salvador a Santa Ana: unos 55 km en linea recta.
        assert 45_000 < metros < 65_000

    def test_las_estadisticas_cuentan_solo_lo_activo(self, sesion):
        ids = sembrar(sesion)
        sesion.execute(
            text("UPDATE places SET is_active = false WHERE id = :id"),
            {"id": ids["mirador"]},
        )
        sesion.commit()

        stats = catalog_stats(sesion)
        assert stats["active"] == 5
        assert stats["downloaded"] == 6
        assert "viewpoint" not in stats["by_category"]
