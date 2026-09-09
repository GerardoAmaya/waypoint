"""limpia traslados guardados mas cortos que la linea recta

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Borra las aristas imposibles que entraron antes de la comprobacion.

    Cuando dos lugares estan lejos de toda carretera, OpenRouteService los
    engancha al mismo nodo de la red vial y devuelve 0 km. El codigo ya
    descarta esas medidas al recibirlas, pero las que se guardaron antes
    siguen ahi y la cache las sirve igual: el primer itinerario despues del
    arreglo salia con los mismos ceros y marcado como medicion real.

    Un CHECK no puede cubrir esto porque la comprobacion mira otra tabla, asi
    que se limpia una vez y la garantia queda en el codigo que escribe.

    El margen del 2% es el mismo que usa app/services/routing.py, para que la
    base y la aplicacion no discrepen sobre que es plausible.
    """
    op.execute(
        """
        DELETE FROM travel_edges te
        USING places o, places d
        WHERE te.origin_id = o.id
          AND te.destination_id = d.id
          AND te.distance_km * 1000 < ST_Distance(o.geom, d.geom) * 0.98
        """
    )


def downgrade() -> None:
    """No hay vuelta atras y no hace falta.

    Lo que se borro eran medidas invalidas. La cache se vuelve a llenar sola
    la proxima vez que se pida un itinerario en la zona, ahora con los pares
    imposibles cayendo a estimacion como corresponde.
    """
