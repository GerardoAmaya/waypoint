"""Revision sin efecto: la extension unaccent se penso y se descarto.

**Existe vacia a proposito y borrarla podria tirar el despliegue.** La primera
version de la busqueda por nombre creaba aqui la extension `unaccent`. Si esa
migracion llego a correr en produccion, la tabla `alembic_version` guarda
"0007", y quitar el archivo dejaria a Alembic buscando una revision que no
existe: `alembic upgrade head` falla y, como las migraciones corren al arrancar
el contenedor —ver backend/start.sh—, el servicio no levanta.

Por que se descarto: crear una extension necesita permisos que un Postgres
administrado puede no dar, y ese fallo no seria una busqueda peor sino un
arranque roto. Las tildes se quitan ahora con `translate`, que no necesita nada
instalado. Ver CON_TILDES en app/services/places.py, donde esta medido que el
resultado es el mismo sobre el catalogo entero.

Revision ID: 0007
Revises: 0006
"""

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nada. Ver la explicacion de arriba."""


def downgrade() -> None:
    """Nada."""
