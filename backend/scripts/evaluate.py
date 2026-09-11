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
from app.services.geo import EstimatedTravel
from app.services.itinerary import Itinerary, plan, plan_with_routing
from scripts.evaluation.cases import CASES
from scripts.evaluation.checks import SOFT_CHECKS, check_all


def catalog_ids(db) -> set:
    return set(db.execute(select(Place.id).where(Place.is_active.is_(True))).scalars())


# Debajo de cuatro paradas la metrica no dice nada util: en un dia de dos
# tramos, el mas caro pasa del cincuenta por ciento por aritmetica y no por
# mal reparto.
MIN_STOPS_FOR_MARGIN = 4


def marginal_stop_cost(itinerario: Itinerary) -> list[float]:
    """Cuanto se ahorraria quitando la parada mas cara del dia.

    Es la limitacion que quedo abierta: el motor llena hasta el tope de
    paradas mientras el presupuesto aguante, sin preguntarse si una parada
    vale lo que suma.

    **La primera version de esta metrica estaba confundida.** Medía la
    fraccion que aporta el tramo mas caro, y eso depende de cuantos tramos
    tenga el dia: con dos, el mayor es al menos la mitad por definicion. Una
    mediana del 45% no distinguia un reparto malo de un dia corto.

    Ahora se mide lo que la pregunta pedia: quitar cada parada intermedia,
    reconectar sus vecinas, y ver cuanto baja el total. Solo sobre dias de
    cuatro paradas o mas, que es donde la decision importa.
    """
    fracciones = []

    for dia in itinerario.days:
        if len(dia.stops) < MIN_STOPS_FOR_MARGIN:
            continue

        lugares = [p.place for p in dia.stops]
        total = _ruta_km(lugares)
        if total <= 0:
            continue

        # Se prueba quitar cada parada intermedia. Las de los extremos no
        # cuentan: sacar la primera o la ultima acorta el dia en vez de
        # deshacer un rebote.
        ahorros = [
            total - _ruta_km(lugares[:i] + lugares[i + 1 :])
            for i in range(1, len(lugares) - 1)
        ]
        if ahorros:
            fracciones.append(max(ahorros) / total)

    return fracciones


# Un dia de una o dos paradas no dice nada de variedad: con dos paradas, la
# categoria mayoritaria es la mitad por aritmetica.
MIN_STOPS_FOR_VARIETY = 3


def day_variety(itinerario: Itinerary) -> list[tuple[int, int]]:
    """Por cada dia medible: categorias distintas y racha mas larga.

    La monotonia fue una limitacion real y medida. El llenado del dia ordenaba
    solo por distancia a la semilla, y como los lugares de una misma categoria
    estan agrupados en el terreno —los cerros comparten cresta, las iglesias
    comparten centro— un dia sembrado con un cerro se llenaba de cerros: el
    45% de los dias tenian tres o mas paradas seguidas iguales.

    Se mide aca para que no vuelva a degradarse en silencio: la penalizacion
    que lo corrige es una constante del motor, y una constante sin metrica que
    la vigile es una constante que alguien baja sin darse cuenta.
    """
    salida = []

    for dia in itinerario.days:
        cats = [parada.place.category for parada in dia.stops]
        if len(cats) < MIN_STOPS_FOR_VARIETY:
            continue

        mejor = actual = 1
        for anterior, siguiente in zip(cats, cats[1:], strict=False):
            actual = actual + 1 if anterior == siguiente else 1
            mejor = max(mejor, actual)

        salida.append((len(set(cats)), mejor))

    return salida


def _ruta_km(lugares) -> float:
    """Kilometros del recorrido, medidos igual que los mide el motor."""
    medidor = EstimatedTravel("driving")
    return sum(medidor.between(a, b)[0] for a, b in zip(lugares, lugares[1:], strict=False))


def _motivo(detalle: str) -> str:
    """Clasifica el consejo por su causa, leyendo el texto que emitio el motor."""
    if "no hay ningún lugar" in detalle:
        return "sin restaurantes en la zona"
    if "cae dentro del horario" in detalle:
        return "ninguno cae en la franja horaria"
    return "el mas cercano no entra en el presupuesto"


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
    recomendaciones = 0
    fuera_de_hora = 0
    total_dias = 0
    motivos_consejo: Counter[str] = Counter()
    marginales: list[float] = []
    variedad: list[tuple[int, int]] = []
    total_paradas = 0
    inventados = 0

    with SessionLocal() as db:
        ids = catalog_ids(db)
        print(f"Catalogo: {len(ids)} lugares activos")
        print(f"Casos: {len(casos)}")
        print(f"Distancias: {'reales de ORS' if args.real_routes else 'estimadas'}\n")

        for caso in casos:
            if args.real_routes:
                itinerario, _, _ = plan_with_routing(db, caso.constraints)
            else:
                itinerario = plan(db, caso.constraints)

            reporte = check_all(itinerario, caso.constraints, ids)
            total_paradas += itinerario.total_stops
            total_dias += len(itinerario.days)

            # Los consejos los emite el motor y no el comprobador: aqui solo
            # se cuentan, para separar "no hay restaurantes" de "los hay pero
            # no entran en el presupuesto". Son cosas distintas y la segunda
            # se arregla subiendo un limite.
            for consejo in itinerario.advice:
                motivos_consejo[_motivo(consejo.detail)] += 1
            marginales.extend(marginal_stop_cost(itinerario))
            variedad.extend(day_variety(itinerario))

            for fallo in reporte.failures:
                fallos_por_check[fallo.check] += 1
                if fallo.check == "invented_place":
                    inventados += 1
            # Las blandas se cuentan por separado: son dos cosas distintas y
            # sumarlas hacia que la cifra de "llevá comida" subiera al agregar
            # la de horarios, midiendo otra cosa con el mismo numero.
            recomendaciones += sum(1 for f in reporte.soft if f.check == "include_meals")
            fuera_de_hora += sum(1 for f in reporte.soft if f.check == "fuera_de_hora")

            if reporte.passed:
                cumplidos += 1
                marca = "ok   " if not reporte.soft else "ok  ~"
                print(f"  {marca} {caso.name}")
            else:
                resumen = ", ".join(sorted({f.check for f in reporte.hard}))
                print(f"  FALLA {caso.name:<26} {resumen}")

            if args.verbose and reporte.failures:
                print(f"        ({caso.why})")
                for fallo in reporte.failures:
                    dia = f"dia {fallo.day}" if fallo.day else "itinerario"
                    tipo = "consejo" if fallo.check in SOFT_CHECKS else "limite"
                    print(f"        - [{tipo} {dia}] {fallo.detail}")

    print(f"\n{'=' * 60}")
    print(
        f"Cumplen todos sus LIMITES DUROS: {cumplidos}/{len(casos)} "
        f"({cumplidos / len(casos):.0%})"
    )
    print(f"Paradas generadas: {total_paradas}")
    print(f"Lugares inventados: {inventados}")

    duros = {k: v for k, v in fallos_por_check.items() if k not in SOFT_CHECKS}
    if duros:
        print("\nLimites incumplidos:")
        for check, cuantos in sorted(duros.items(), key=lambda kv: -kv[1]):
            print(f"  {check:<24} {cuantos:>4}")
    else:
        print("\nNingun limite duro incumplido.")

    if total_dias:
        print(
            f"\nDias con recomendacion de llevar comida: {recomendaciones}"
            f" de {total_dias} ({recomendaciones / total_dias:.0%})"
        )
        for motivo, cuantos in sorted(motivos_consejo.items(), key=lambda kv: -kv[1]):
            print(f"  {motivo:<28} {cuantos:>4}")

    # **Existia como afirmacion en el README y no como medicion.** La tabla
    # decia cero, que era verdad el dia que se conto a mano, y dejo de serlo sin
    # que nada avisara.
    print(f"\nParadas que terminan fuera de hora (luz o cierre): {fuera_de_hora}")

    if marginales:
        print(
            "\nAhorro de quitar la parada intermedia mas cara "
            f"(solo dias de {MIN_STOPS_FOR_MARGIN}+ paradas):"
        )
        print(
            f"  mediana {statistics.median(marginales):.0%}   "
            f"peor {max(marginales):.0%}   "
            f"dias medidos {len(marginales)}"
        )
        caros = [f for f in marginales if f >= 0.30]
        print(f"  dias donde una sola parada cuesta 30% o mas: {len(caros)}")
    else:
        print(
            f"\nNingun dia llego a {MIN_STOPS_FOR_MARGIN} paradas: "
            "la metrica del rebote no aplica."
        )

    if variedad:
        distintas = [d for d, _ in variedad]
        rachas = [r for _, r in variedad]
        dominados = sum(1 for d in distintas if d == 1)
        con_racha = sum(1 for r in rachas if r >= 3)
        print(f"\nVariedad por dia (solo dias de {MIN_STOPS_FOR_VARIETY}+ paradas):")
        print(
            f"  categorias distintas: media {statistics.mean(distintas):.2f}   "
            f"peor {min(distintas)}   dias medidos {len(variedad)}"
        )
        print(
            f"  dias con 3+ paradas seguidas iguales: {con_racha} "
            f"({con_racha / len(variedad):.0%})"
        )
        print(f"  dias de una sola categoria: {dominados} ({dominados / len(variedad):.0%})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
