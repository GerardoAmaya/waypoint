"""Reaplica el filtro de calidad al catalogo que ya esta en la base.

Cuando el filtro aprende una regla nueva, los lugares que entraron antes
siguen adentro. La alternativa seria volver a bajar los seis mil registros de
Overpass, que es lento y ademas los devolveria distintos: OpenStreetMap cambia
todos los dias y una recarga mezclaria el efecto de la regla nueva con el de
los datos nuevos. Aqui se reevalua lo guardado y no se toca la red.

    python -m scripts.refilter_places            # solo dice que pasaria
    python -m scripts.refilter_places --apply    # lo hace

**No resucita nada.** Solo desactiva lo que la regla nueva rechaza. Un lugar
que se descarto por duplicado o por calidad se queda afuera, porque volver a
activarlo desharia la deduplicacion sin rehacerla.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Place
from app.services.places_quality import evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="escribir los cambios")
    parser.add_argument("--show", type=int, default=25, help="cuantos ejemplos mostrar")
    args = parser.parse_args()

    motivos: Counter[str] = Counter()
    caidos: list[tuple[str, str]] = []

    with SessionLocal() as db:
        activos = db.execute(select(Place).where(Place.is_active.is_(True))).scalars().all()

        for lugar in activos:
            # Sin tags no se puede reevaluar: se deja como esta en vez de
            # descartarlo por falta de informacion nuestra.
            if not lugar.tags:
                continue

            veredicto = evaluate(lugar.tags)
            if veredicto.accepted:
                continue

            motivos[veredicto.reason or "sin_motivo"] += 1
            caidos.append((lugar.name, veredicto.reason or "sin_motivo"))

            if args.apply:
                lugar.is_active = False
                lugar.rejected_reason = veredicto.reason

        print(f"Activos revisados: {len(activos)}")
        print(f"Rechazados por las reglas actuales: {len(caidos)}\n")

        for motivo, cuantos in motivos.most_common():
            print(f"  {motivo:<22} {cuantos:>5}")

        if caidos:
            print(f"\nEjemplos (hasta {args.show}):")
            for nombre, motivo in caidos[: args.show]:
                print(f"  [{motivo}] {nombre}")

        if not args.apply:
            print("\nNada escrito. Agrega --apply para desactivarlos.")
            return 0

        db.commit()
        print(f"\n{len(caidos)} lugares desactivados.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
