"""guarda el trazo de cada tramo por carretera, para dibujarlo

Revision ID: 0005
Revises: 0004
"""

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """El trazo de un tramo, en su propia tabla.

    **Tiene la misma clave que travel_edges y aun asi no es una columna de
    ahi.** Comparten origen, destino y perfil, pero no comparten ciclo de vida:
    OpenRouteService mide el cupo por endpoint —observado en vivo, la matriz
    respondiendo "Quota exceeded" mientras direcciones seguia contestando— asi
    que un itinerario puede tener sus distancias estimadas y su trazo real a la
    vez.

    Como columna de travel_edges ese caso no cabia: solo se guardan las aristas
    medidas, el UPDATE no encontraba fila, y el trazo se descartaba para volver
    a pedirse en la consulta siguiente. Se gastaba cupo para tirar el resultado.
    """
    op.create_table(
        "route_legs",
        sa.Column(
            "origin_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("places.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "destination_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("places.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("profile", sa.String(24), primary_key=True),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="LINESTRING", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_route_legs_origin", "route_legs", ["origin_id"])


def downgrade() -> None:
    """Borra los trazos guardados, y recuperarlos cuesta cupo de ORS."""
    op.drop_index("ix_route_legs_origin", table_name="route_legs")
    op.drop_table("route_legs")
