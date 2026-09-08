"""Fixtures compartidos. Requiere un Postgres con PostGIS alcanzable."""

import os

import pytest
from sqlalchemy import create_engine, text

DEFAULT_TEST_URL = "postgresql+psycopg://waypoint:waypoint@localhost:5434/waypoint_test"


def database_url() -> str:
    """URL de la base descartable donde corren los tests.

    Estos tests hacen DROP SCHEMA. Si apuntan por error a la base de
    desarrollo se la llevan puesta, asi que exigimos que el nombre contenga
    "test". Es barato y evita un accidente caro.
    """
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_URL)
    database = url.rsplit("/", 1)[-1].split("?")[0]
    if "test" not in database.lower():
        raise RuntimeError(
            f"TEST_DATABASE_URL apunta a la base {database!r}, que no parece de "
            "prueba. Estos tests borran el esquema completo."
        )
    return url


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(database_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(engine):
    """Deja la base sin tablas antes de cada prueba de migracion."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    return engine
