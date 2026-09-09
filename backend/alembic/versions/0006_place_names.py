"""nomenclator de nombres de lugar: departamentos, municipios, pueblos, barrios

Revision ID: 0006
Revises: 0005
"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Los nombres de lugar viven aparte de los puntos de interes.

    Son dos cosas distintas y confundirlas ya causaba un fallo real: "vivo en
    Mejicanos" no resolvia nada porque lo unico llamado Mejicanos en el
    catalogo son cuatro puestos de comida, y el motor —con razon— se niega a
    anclar un viaje en un cafe. Mejicanos no es un punto de interes, es un
    lugar donde la gente vive.

    **Tabla propia y busqueda propia.** Mezclarlos en `places` pondria tres mil
    nombres de barrio a competir por trigramas con los nombres de negocios, y
    la busqueda difusa ya se equivoca sin ayuda: "Hotel Barcelo" devuelve
    "Hotel La Parcela". Cada indice busca en lo suyo.

    `destinations_nearby` se guarda medido y no se recalcula al vuelo: es el
    dato que decide si un nombre sirve para armar un dia. Los que no llegan al
    minimo quedan con is_active en false y su motivo, igual que en `places`:
    borrarlos impediria medir el filtro y afinarlo despues.
    """
    op.create_table(
        "place_names",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("osm_type", sa.String(16), nullable=False),
        sa.Column("osm_id", sa.BigInteger, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        # "admin4" (departamento), "admin6" (municipio), "admin8" (distrito),
        # "city", "town", "village", "suburb", "neighbourhood".
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geography(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        # Sale del recuadro del limite administrativo cuando OSM lo trae, y de
        # un valor por tipo cuando el lugar es solo un punto. Un departamento y
        # un barrio no pueden buscar en el mismo radio.
        sa.Column("radius_m", sa.Integer, nullable=False),
        sa.Column("destinations_nearby", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
        sa.Column("rejected_reason", sa.String(32)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("osm_type", "osm_id", name="uq_place_names_osm"),
    )
    op.create_index(
        "ix_place_names_geom", "place_names", ["geom"], postgresql_using="gist"
    )
    # Misma tolerancia a errores de escritura que el catalogo, en su propio
    # indice: la gente escribe "Mejicanos" y "mejicanos" y "Megicanos".
    op.create_index(
        "ix_place_names_name_trgm",
        "place_names",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_place_names_kind_active", "place_names", ["kind", "is_active"]
    )


def downgrade() -> None:
    op.drop_index("ix_place_names_kind_active", table_name="place_names")
    op.drop_index("ix_place_names_name_trgm", table_name="place_names")
    op.drop_index("ix_place_names_geom", table_name="place_names")
    op.drop_table("place_names")
