"""Extension unaccent, para buscar lugares sin depender de las tildes.

Los nombres del catalogo vienen de OpenStreetMap con sus tildes —"Centro
Comercial Galerías", "Volcán de Santa Ana"— y quien escribe en una caja de
texto casi nunca las pone. Sin esto, "Galerias" se parece mas a "Go Green
Galerias", que es un local de comida rapida, que al centro comercial del mismo
nombre: 1.00 contra 0.56, y gana el que no era.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    # No se borra la extension: otras cosas pueden estar usandola, y una
    # extension de mas no rompe nada. Bajar una migracion no deberia poder
    # tumbar una busqueda que no es suya.
    pass
