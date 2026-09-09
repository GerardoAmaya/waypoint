"""Mide cuantos itinerarios cumplen todas sus restricciones.

    python -m scripts.evaluate                 # con distancias estimadas
    python -m scripts.evaluate --real-routes   # con rutas reales de ORS
    python -m scripts.evaluate --verbose       # detalle de cada fallo

Por defecto **no gasta cupo de ORS**: la mayoria de las restricciones
—horarios, paradas, categorias, radio, repeticiones— no dependen de si la
distancia es real o estimada, y correr la evaluacion entera contra la API
gastaria mas de la mitad del cupo diario en cada corrida.

Con `--real-routes` se mide tambien el limite de kilometros contra la
carretera de verdad, que es donde estimar y medir se separan.

Las comprobaciones viven en scripts/evaluation/checks.py y **no usan
validate()**: el motor no puede ser juez de su propio trabajo.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Place
from app.services.itinerary import Itinerary, plan, plan_with_routing
from scripts.evaluation.cases import CASES
from scripts.evaluation.checks import check_all


def catalog_ids(db) -> set:
    return set(db.execute(select(Place.id).where(Place.is_active.is_(True))).scalars())


def marginal_stop_cost(itinerario: Itinerary) -> list[float]:
    """Que fraccion de los kilometros del dia aporta su parada mas cara.

    Es la limitacion que quedo abierta: el motor llena hasta el tope de
    paradas mientras el presupuesto aguante, sin preguntarse si una parada
    vale lo que suma. Si esto sale sistematicamente alto, una regla esta
    justificada; si sale bajo, el caso de Ataco era un caso duro y no un
    patron.
    """
    fracciones = []
    for dia in itinerario.days:
        traslados = [p.travel_km_from_previous for p in dia.stops if p.travel_km_from_previous]
        total = sum(traslados)
        if len(traslados) >= 2 and total > 0:
            fracciones.append(max(traslados) / total)
    return fracciones


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-routes", action="store_true", help="usar ORS")
    parser.add_argument("--verbose", action="store_true", help="detalle de los fallos")
    parser.add_argument("--case", help="correr un solo caso por su nombre")
    args = parser.parse_args()

    casos = [c for c in CASES if not args.case or c.name == args.case]
    if not casos:
        print(f"no hay ningun caso llamado {args.case!r}")
        return 1

    fallos_por_check: Counter[str] = Counter()
    cumplidos = 0
    marginales: list[float] = []
    total_paradas = 0
    inventados = 0

    with SessionLocal() as db:
        ids = catalog_ids(db)
        print(f"Catalogo: {len(ids)} lugares activos")
        print(f"Casos: {len(casos)}")
        print(f"Distancias: {'reales de ORS' if args.real_routes else 'estimadas'}\n")

        for caso in casos:
            if args.real_routes:
                itinerario, _ = plan_with_routing(db, caso.constraints)
            else:
                itinerario = plan(db, caso.constraints)

            reporte = check_all(itinerario, caso.constraints, ids)
            total_paradas += itinerario.total_stops
            marginales.extend(marginal_stop_cost(itinerario))

            for fallo in reporte.failures:
                fallos_por_check[fallo.check] += 1
                if fallo.check == "invented_place":
                    inventados += 1

            if reporte.passed:
                cumplidos += 1
                print(f"  ok    {caso.name}")
            else:
                resumen = ", ".join(sorted({f.check for f in reporte.failures}))
                print(f"  FALLA {caso.name:<26} {resumen}")
                if args.verbose:
                    print(f"        ({caso.why})")
                    for fallo in reporte.failures:
                        dia = f"dia {fallo.day}" if fallo.day else "itinerario"
                        print(f"        - [{dia}] {fallo.detail}")

    print(f"\n{'=' * 60}")
    print(
        f"Cumplen TODAS sus restricciones: {cumplidos}/{len(casos)} "
        f"({cumplidos / len(casos):.0%})"
    )
    print(f"Paradas generadas: {total_paradas}")
    print(f"Lugares inventados: {inventados}")

    if fallos_por_check:
        print("\nFallos por comprobacion:")
        for check, cuantos in fallos_por_check.most_common():
            print(f"  {check:<24} {cuantos:>4}")

    if marginales:
        print("\nCosto de la parada mas cara de cada dia, como fraccion del dia:")
        print(
            f"  mediana {statistics.median(marginales):.0%}   "
            f"peor {max(marginales):.0%}   "
            f"dias medidos {len(marginales)}"
        )

    return 0 if cumplidos == len(casos) else 0


if __name__ == "__main__":
    sys.exit(main())
