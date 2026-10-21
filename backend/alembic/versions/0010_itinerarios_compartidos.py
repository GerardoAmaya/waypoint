"""Itinerarios guardados para poder compartirlos por enlace.

Hasta ahora un itinerario vivia solo en la pestaña de quien lo pidio: se podia
copiar como texto y nada mas. Para un planificador de viajes eso es raro, que
el acto siguiente a armar un plan es enseñarselo a quien va con vos.

**Lo guarda el servidor al armarlo, no el cliente al compartirlo.** La forma
obvia seria un `POST /share` que reciba el itinerario y devuelva un codigo, y
esa forma guarda JSON arbitrario de un cliente para servirselo a otros. El
frontend dibuja el sitio web de cada parada como un enlace, asi que un
`javascript:` inyectado en ese campo seria XSS almacenado. Como `/plan` ya
tiene el itinerario armado del lado del servidor, guardarlo ahi quita la
entrada del cliente de la ecuacion.

El contenido se guarda entero y no se regenera al abrirlo. Un plan rearmado
puede salir distinto —el catalogo cambia, el cupo de rutas se agota, el
pronostico se mueve— y quien comparte un itinerario comparte ESE, no "lo que
salga cuando lo abras".

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shared_itineraries",
        # Codigo corto y no un UUID: va en una URL que alguien puede llegar a
        # dictar por telefono. Lo genera la aplicacion, no la base, porque el
        # alfabeto excluye a proposito los caracteres que se confunden.
        sa.Column("code", sa.String(12), primary_key=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # Cuantas veces se abrio. No es analitica: sirve para saber que se
        # puede borrar sin molestar a nadie el dia que la tabla crezca.
        sa.Column("opened", sa.Integer, nullable=False, server_default="0"),
    )
    # Para poder limpiar los viejos por fecha sin recorrer la tabla entera.
    op.create_index("ix_shared_itineraries_created_at", "shared_itineraries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_shared_itineraries_created_at", table_name="shared_itineraries")
    op.drop_table("shared_itineraries")
