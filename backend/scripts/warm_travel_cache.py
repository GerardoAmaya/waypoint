"""Llena travel_edges por adelantado, zona por zona.

Con cincuenta peticiones diarias de matriz, una demo publica que consulte ORS
en vivo se queda sin cupo a media manana. La salida es precalcular: las zonas
turisticas del pais son pocas y sus lugares no se mueven, asi que la cache se
llena una vez y despues el itinerario sale de la base.

    python -m scripts.warm_travel_cache                # solo dice cuanto costaria
    python -m scripts.warm_travel_cache --apply        # lo hace
    python -m scripts.warm_travel_cache --apply --zone ataco

**No gasta nada sin --apply.** Un guion que consume cupo por equivocacion es
caro cuando el cupo son cincuenta al dia y se reinicia a las veinticuatro
horas de la primera llamada, no a medianoche.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Category, Place
from app.services.geocode import ZONES
from app.services.itinerary import appeal_of
from app.services.places import PlaceHit
from app.services.routing import (
    MAX_LOCATIONS_PER_REQUEST,
    ORSError,
    client_from_settings,
    load_travel_matrix,
)

# Las zonas salen del nomenclator, que es la misma lista que usa la capa
# conversacional para resolver "quiero ir a Suchitoto". No es casualidad: una
# zona que vale la pena precalentar es una zona a la que la gente pide ir, y
# tener dos listas que se desincronizan seria peor que tener una sola.
ZONAS = {z.key: (z.lat, z.lon, z.radius_m) for z in ZONES}


def lugares_de_zona(db, lat: float, lon: float, radio_m: int, tope: int) -> list[PlaceHit]:
    """Los lugares mas visitables de la zona, en orden de atractivo.

    Se recorta a los mejores porque la matriz crece al cuadrado: sesenta
    lugares son 3.540 pares y ya no entran en una peticion. Los que quedan
    fuera siguen funcionando con estimacion.
    """
    punto = func.ST_MakePoint(lon, lat).cast(Place.geom.type)
    filas = (
        db.execute(
            select(Place)
            .where(
                Place.is_active.is_(True),
                Place.category != Category.lodging,
                func.ST_DWithin(Place.geom, punto, radio_m),
            )
            .order_by(Place.quality_score.desc())
            .limit(tope * 3)
        )
        .scalars()
        .all()
    )

    hits = [
        PlaceHit(
            id=p.id,
            name=p.name,
            category=p.category.value if hasattr(p.category, "value") else p.category,
            subcategory=p.subcategory,
            lat=p.lat,
            lon=p.lon,
            quality_score=p.quality_score,
        )
        for p in filas
    ]
    hits.sort(key=lambda h: (appeal_of(h), h.quality_score), reverse=True)
    return hits[:tope]


def peticiones_para(cantidad: int, chunk: int = MAX_LOCATIONS_PER_REQUEST) -> int:
    bloques = max(1, -(-cantidad // chunk))
    return bloques * bloques


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="gastar cupo de verdad")
    parser.add_argument("--zone", choices=sorted(ZONAS), help="una sola zona")
    parser.add_argument("--top", type=int, default=MAX_LOCATIONS_PER_REQUEST)
    parser.add_argument("--mode", choices=["driving", "walking"], default="driving")
    args = parser.parse_args()

    if args.top > 59:
        print("--top no puede pasar de 59: son 3.422 pares y el techo es 3.500.")
        return 1

    zonas = {args.zone: ZONAS[args.zone]} if args.zone else ZONAS
    cliente = client_from_settings() if args.apply else None

    if args.apply and cliente is None:
        print("No hay ORS_API_KEY en el entorno.")
        return 1

    total_peticiones = 0
    with SessionLocal() as db:
        planes = []
        for nombre, (lat, lon, radio) in zonas.items():
            lugares = lugares_de_zona(db, lat, lon, radio, args.top)
            costo = peticiones_para(len(lugares)) if len(lugares) > 1 else 0
            total_peticiones += costo
            planes.append((nombre, lugares, costo))
            print(f"{nombre:<14} {len(lugares):>3} lugares  {costo} peticion(es)")

        print(f"\nTotal: {total_peticiones} de las 50 diarias.")

        if not args.apply:
            print("Nada gastado. Agrega --apply para hacerlo.")
            return 0

        if total_peticiones > 50:
            print("Eso pasa del cupo diario. Corre zona por zona con --zone.")
            return 1

        for nombre, lugares, _ in planes:
            if len(lugares) < 2:
                continue
            try:
                matriz = load_travel_matrix(
                    lugares, args.mode, db=db, client=cliente, chunk_size=args.top
                )
            except ORSError as exc:
                print(f"{nombre}: {exc}")
                continue

            s = matriz.stats
            print(
                f"{nombre:<14} cache {s.cached:>5}  nuevos {s.fetched:>5}  "
                f"sin ruta {s.estimated:>4}  ({s.real_ratio:.0%} reales)"
            )

    print(f"\nPeticiones usadas: {cliente.request_count if cliente else 0}")
    print(f"Ritmo configurado: {settings.ors_min_interval_seconds}s entre llamadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
