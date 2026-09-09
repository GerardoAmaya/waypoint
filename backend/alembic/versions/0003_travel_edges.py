"""cache de traslados medidos con openrouteservice

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "travel_edges",
        sa.Column("origin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("destination_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Perfil de ORS: "driving-car" o "foot-walking". Va en la clave porque
        # a pie y en carro son redes distintas, no la misma medida escalada.
        sa.Column("profile", sa.String(24), nullable=False),
        sa.Column("distance_km", sa.Float, nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="ors"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("origin_id", "destination_id", "profile"),
        # Si un lugar se borra del catalogo, sus aristas se van con el. Sin
        # esto quedarian midiendo traslados hacia un sitio que ya no existe.
        sa.ForeignKeyConstraint(["origin_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["destination_id"], ["places.id"], ondelete="CASCADE"),
        # Un traslado no puede ir de un lugar a si mismo.
        sa.CheckConstraint("origin_id <> destination_id", name="ck_travel_edges_distinct"),
        # Una ruta no puede tener largo ni duracion negativos.
        sa.CheckConstraint(
            "distance_km >= 0 AND duration_minutes >= 0", name="ck_travel_edges_positive"
        ),
    )

    op.create_index("ix_travel_edges_origin", "travel_edges", ["origin_id"])
    op.create_index("ix_travel_edges_profile", "travel_edges", ["profile"])


def downgrade() -> None:
    op.drop_index("ix_travel_edges_profile", table_name="travel_edges")
    op.drop_index("ix_travel_edges_origin", table_name="travel_edges")
    op.drop_table("travel_edges")
