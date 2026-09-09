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


@pytest.fixture(autouse=True)
def limites_limpios():
    """Vacia la cuenta del limitador antes de cada test.

    El limitador es un singleton del proceso, que es lo correcto en produccion
    —una cuenta por IP no sirve si cada peticion empieza de cero— y un
    acoplamiento entre tests aqui: sin esto, la bateria entera comparte una sola
    cuota y los tests se cortan unos a otros segun el orden en que corran.

    Se declara en vez de esconderse con limites altos en el entorno de prueba:
    un limite que en los tests vale mil no prueba nada del que vale cuatro.
    """
    from app.api import itinerary as api_itinerary
    from app.api import plan as api_plan

    for modulo in (api_itinerary, api_plan):
        modulo._limiter._hits.clear()
    yield


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(database_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture
def clean_database(engine):
    """Deja la base sin tablas antes de cada prueba de migracion.

    DROP SCHEMA CASCADE borra tambien PostGIS, que vive en public. Al volver a
    crearla, el tipo geography recibe un OID nuevo, asi que se descarta el pool
    de conexiones: las que quedaron abiertas tienen el OID anterior cacheado y
    Postgres falla con "no spatial operator found for st_dwithin".
    """
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return engine
