"""El modelo ORM y la base migrada no deben divergir.

Comprueba nombres Y tipos. Comprobar solo los nombres deja pasar el caso en
que el modelo declara Integer y la migracion BigInteger: la tabla se crea bien
y la insercion falla en tiempo de ejecucion con "integer out of range".
"""

from sqlalchemy import inspect

from alembic import command
from app import models  # noqa: F401  (registra las tablas en Base.metadata)
from app.core.db import Base
from tests.test_migrations import alembic_config

# Tipos que la base reporta con otro nombre del que usa SQLAlchemy.
EQUIVALENTES = {
    "VARCHAR": {"VARCHAR", "STRING"},
    "TIMESTAMP": {"TIMESTAMP", "DATETIME"},
    "DOUBLE PRECISION": {"DOUBLE PRECISION", "FLOAT"},
    "JSONB": {"JSONB", "JSON"},
    "GEOGRAPHY": {"GEOGRAPHY"},
}


def nombre_de_tipo(tipo) -> str:
    return str(tipo).split("(")[0].strip().upper()


def son_compatibles(modelo: str, base: str) -> bool:
    if modelo == base:
        return True
    for grupo in EQUIVALENTES.values():
        if modelo in grupo and base in grupo:
            return True
    return False


def test_todas_las_tablas_del_modelo_existen(clean_database):
    command.upgrade(alembic_config(), "head")

    reales = set(inspect(clean_database).get_table_names())
    for nombre in Base.metadata.tables:
        assert nombre in reales, f"El modelo declara {nombre} y la migracion no la crea"


def test_todas_las_columnas_existen(clean_database):
    command.upgrade(alembic_config(), "head")

    inspector = inspect(clean_database)
    faltantes: list[str] = []

    for tabla, definicion in Base.metadata.tables.items():
        reales = {c["name"] for c in inspector.get_columns(tabla)}
        for columna in definicion.columns:
            if columna.name not in reales:
                faltantes.append(f"{tabla}.{columna.name}")

    assert not faltantes, f"Columnas del modelo que no existen en la base: {faltantes}"


def test_los_tipos_de_columna_coinciden(clean_database):
    """El caso que rompio la carga del catalogo.

    El modelo declaraba osm_id como Integer y la migracion como BigInteger.
    La tabla quedaba bien, pero SQLAlchemy convertia el parametro a INTEGER y
    un identificador de OSM real desbordaba.
    """
    command.upgrade(alembic_config(), "head")

    inspector = inspect(clean_database)
    discrepancias: list[str] = []

    for tabla, definicion in Base.metadata.tables.items():
        reales = {c["name"]: c["type"] for c in inspector.get_columns(tabla)}
        for columna in definicion.columns:
            if columna.name not in reales:
                continue
            del_modelo = nombre_de_tipo(columna.type)
            de_la_base = nombre_de_tipo(reales[columna.name])
            if not son_compatibles(del_modelo, de_la_base):
                discrepancias.append(
                    f"{tabla}.{columna.name}: modelo={del_modelo} base={de_la_base}"
                )

    assert not discrepancias, "Tipos que no coinciden: " + "; ".join(discrepancias)
