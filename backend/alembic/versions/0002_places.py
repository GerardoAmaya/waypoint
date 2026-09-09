"""tabla del catalogo de lugares

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create_type=False evita que SQLAlchemy intente crear el tipo otra vez al
    # encontrarlo dentro de create_table. Lo creamos nosotros.
    categoria = postgresql.ENUM(
        "food", "nature", "culture", "viewpoint", "attraction", "lodging",
        name="place_category",
        create_type=False,
    )
    categoria.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "places",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("osm_type", sa.String(8), nullable=False),
        sa.Column("osm_id", sa.BigInteger, nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("category", categoria, nullable=False),
        sa.Column("subcategory", sa.String(64)),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.Column("tags", postgresql.JSONB),
        sa.Column("quality_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("rejected_reason", sa.String(64)),
        sa.Column("duplicate_of", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("osm_type", "osm_id", name="uq_places_osm"),
    )

    # GiST para consultas por radio. Sin el, cada busqueda recorre la tabla.
    op.execute("CREATE INDEX ix_places_geom ON places USING gist (geom)")
    # Trigramas para comparar nombres, que en OSM vienen con variaciones.
    op.execute("CREATE INDEX ix_places_name_trgm ON places USING gin (name gin_trgm_ops)")
    op.create_index("ix_places_category_active", "places", ["category", "is_active"])


def downgrade() -> None:
    op.drop_table("places")
    op.execute("DROP TYPE IF EXISTS place_category")
