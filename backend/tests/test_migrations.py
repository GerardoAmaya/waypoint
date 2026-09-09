"""Las migraciones deben correr limpias sobre una base vacia.

Existen desde el primer commit a proposito: en el proyecto anterior los tests
de migracion encontraron dos bugs reales apenas se escribieron, uno de ellos
destructivo.
"""

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from tests.conftest import database_url


def alembic_config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url())
    return config


def test_upgrade_enables_postgis(clean_database):
    command.upgrade(alembic_config(), "head")

    with clean_database.connect() as connection:
        extensions = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT extname FROM pg_extension WHERE extname IN ('postgis', 'pg_trgm')"
                )
            )
        }
    assert extensions == {"postgis", "pg_trgm"}


def test_spatial_functions_are_usable(clean_database):
    """PostGIS instalado no basta: hay que poder calcular distancias.

    Comprueba contra una distancia conocida: San Salvador a Santa Ana son
    unos 55 km en linea recta.
    """
    command.upgrade(alembic_config(), "head")

    with clean_database.connect() as connection:
        metros = connection.execute(
            text("""
                SELECT ST_Distance(
                    ST_MakePoint(-89.2182, 13.6929)::geography,
                    ST_MakePoint(-89.5597, 13.9942)::geography
                )
            """)
        ).scalar()

    assert 45_000 < metros < 65_000, f"Distancia inesperada: {metros} m"


def test_upgrade_then_downgrade_is_repeatable(clean_database):
    config = alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    with clean_database.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM pg_extension WHERE extname = 'postgis'")
            ).scalar()
            == 1
        )
