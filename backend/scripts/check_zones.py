"""Comprueba que cada zona del nomenclator tenga lugares alrededor.

Las coordenadas se escribieron a mano y a ojo en un mapa no se validan. Una
que este mal no falla: simplemente no tiene nada cerca, y el itinerario sale
vacio sin explicar por que.

    python -m scripts.check_zones

No gasta cupo de ORS ni llama a ningun servicio: solo consulta el catalogo.
"""

from __future__ import annotations

import sys

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import Category, Place
from app.services.geocode import ZONES

# Debajo de esto la zona no da para armar un itinerario variado.
MINIMO_DESTINOS = 8


def contar(db, zona) -> tuple[int, int]:
    punto = func.ST_MakePoint(zona.lon, zona.lat).cast(Place.geom.type)
    dentro = (
        select(func.count())
        .select_from(Place)
        .where(Place.is_active.is_(True), func.ST_DWithin(Place.geom, punto, zona.radius_m))
    )
    total = db.execute(dentro).scalar() or 0
    destinos = (
        db.execute(
            dentro.where(
                Place.category.notin_([Category.food, Category.lodging]),
            )
        ).scalar()
        or 0
    )
    return total, destinos


def main() -> int:
    problemas = 0

    with SessionLocal() as db:
        print(f"{'zona':<22} {'radio':>7} {'lugares':>8} {'destinos':>9}")
        for zona in ZONES:
            total, destinos = contar(db, zona)
            aviso = "" if destinos >= MINIMO_DESTINOS else "  <-- revisar"
            if aviso:
                problemas += 1
            print(
                f"{zona.name:<22} {zona.radius_m // 1000:>5} km "
                f"{total:>8} {destinos:>9}{aviso}"
            )

    if problemas:
        print(
            f"\n{problemas} zona(s) con menos de {MINIMO_DESTINOS} destinos. "
            "O la coordenada esta mal, o el radio es chico, o la zona no da "
            "para un itinerario y conviene sacarla."
        )
        return 1

    print("\nTodas las zonas tienen material suficiente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
