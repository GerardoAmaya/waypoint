"""Agrupa los registros que son el mismo sitio, sin borrar ninguno.

**Es distinto de `duplicate_of` y la diferencia es el proposito.** Un duplicado
es una fila sobrante: se desactiva y desaparece del catalogo. Esto marca filas
que describen el mismo sitio desde angulos distintos —"Parque Nacional El
Imposible" (la reserva) y "Parque El Imposible" (la entrada), a 1.173 metros—
y las dos son legitimas: cada una tiene su nombre, su categoria y su punto, y
cualquiera sirve para buscar o para que el mapa la muestre.

Lo unico que no tiene sentido es visitarlas las dos en el mismo viaje. Eso es
lo que esta columna permite evitar.

Por que no se resolvio subiendo el radio de la deduplicacion: medido sobre el
catalogo, la banda de 500 a 1.200 metros esta llena de cadenas con nombre
identico —Subway, Don Pollo, Pool House Hostel— que son locales distintos de
verdad. Subir el radio los borraria.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "places",
        sa.Column("same_place_as", sa.UUID(as_uuid=True), nullable=True),
    )
    # Apunta al representante del grupo, que es el de mejor calidad. El
    # representante se apunta a si mismo con NULL, igual que duplicate_of.
    op.create_foreign_key(
        "fk_places_same_place_as",
        "places",
        "places",
        ["same_place_as"],
        ["id"],
        ondelete="SET NULL",
    )
    # Se consulta al leer candidatos, para traer el grupo de cada lugar.
    op.create_index("ix_places_same_place_as", "places", ["same_place_as"])


def downgrade() -> None:
    op.drop_index("ix_places_same_place_as", table_name="places")
    op.drop_constraint("fk_places_same_place_as", "places", type_="foreignkey")
    op.drop_column("places", "same_place_as")
