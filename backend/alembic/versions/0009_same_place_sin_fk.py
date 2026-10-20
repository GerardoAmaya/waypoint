"""Quita la clave foranea de same_place_as: rompia el volcado del catalogo.

**La restriccion apunta a la misma tabla y eso vuelve el volcado circular.**
`pg_dump` avisa: "there are circular foreign-key constraints on this table" y
sugiere `--disable-triggers`. El motivo es real y no cosmetico: los datos van en
lotes de 500 INSERT, y una fila cuyo grupo apunta a otra que todavia no se
inserto viola la restriccion en ese momento. El catalogo se publica con
`make dump` y `make restore`, asi que eso es un restore que se cae.

`duplicate_of` ya era un UUID sin clave foranea por exactamente este motivo, y
estaba delante todo el tiempo. Esta columna sigue el mismo patron.

Lo que se pierde es la integridad referencial: si un lugar se borra, los que lo
tenian de representante quedan apuntando a nada. Es el mismo riesgo que ya se
acepto para `duplicate_of`, y acotado: la agrupacion se recalcula entera en
cada carga del catalogo, asi que un puntero huerfano dura hasta la siguiente
corrida. El indice se queda, que es lo que hace falta para consultarla.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_places_same_place_as", "places", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "fk_places_same_place_as",
        "places",
        "places",
        ["same_place_as"],
        ["id"],
        ondelete="SET NULL",
    )
