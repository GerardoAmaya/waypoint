"""habilitar postgis y pg_trgm

Revision ID: 0001
Revises:

PostGIS resuelve distancias y radios en SQL en vez de en Python.
pg_trgm se usa para deduplicar nombres de lugares parecidos, que en los datos
de OpenStreetMap son frecuentes: "Mirador Volcan de Izalco" y "Mirador al
Volcan de Izalco" son el mismo sitio.
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # No se eliminan: otras tablas podrian depender de ellas y borrarlas en un
    # downgrade es mas destructivo que dejarlas.
    pass
