"""Motor de itinerarios.

El nucleo del proyecto. Convierte las preferencias del usuario en restricciones
duras y arma un plan que las respeta, o declara cual no pudo cumplir.

La division de responsabilidades es deliberada: el modelo de lenguaje traduce
la frase del usuario a restricciones (fase 5) y este modulo las hace cumplir.
Si el modelo armara el itinerario directamente, "odio madrugar" seria una
sugerencia que a veces ignora; aqui es una hora minima de inicio que el
algoritmo no puede violar.

Que sea deterministico ademas lo hace medible: dado un conjunto de
restricciones, se puede comprobar automaticamente si el resultado las cumple.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import time, timedelta

from sqlalchemy.orm import Session

from app.models import Category
from app.services.places import PlaceHit, search_in_area

# Cuanto se queda uno en cada tipo de lugar, en minutos. Son estimaciones de
# sentido comun, no datos: un mirador es una parada corta y un parque nacional
# ocupa media manana.
DEFAULT_DURATIONS: dict[Category, int] = {
    Category.viewpoint: 30,
    Category.food: 60,
    Category.culture: 75,
    Category.attraction: 90,
    Category.nature: 105,
    Category.lodging: 0,
}

# Los caminos reales no van en linea recta. Multiplicamos la distancia
# geodesica por este factor mientras no tengamos rutas reales (fase 4).
DETOUR_FACTOR = 1.35

SPEED_KMH = {"walking": 4.5, "driving": 40.0}

# Cuanto vale la pena visitar cada tipo de lugar, mas alla de que tan completo
# este su registro. Son cosas distintas: quality_score mide si el dato tiene
# horarios y sitio web; esto mide si alguien viajaria a verlo.
#
# En OpenStreetMap "leisure=park" incluye cada plaza municipal del pais, y sin
# esta distincion un redondel puntua igual que un volcan.
SUBCATEGORY_APPEAL: dict[str, float] = {
    # Destinos por los que uno viaja
    "volcano": 1.0,
    "waterfall": 1.0,
    "beach": 0.95,
    "nature_reserve": 0.9,
    "peak": 0.85,
    "viewpoint": 0.8,
    "museum": 0.8,
    "spring": 0.75,
    "cave_entrance": 0.75,
    "theme_park": 0.75,
    "zoo": 0.7,
    "attraction": 0.7,
    "archaeological_site": 0.85,
    "ruins": 0.75,
    "castle": 0.75,
    "gallery": 0.6,
    "theatre": 0.6,
    "arts_centre": 0.55,
    "monument": 0.5,
    "memorial": 0.35,
    "garden": 0.5,
    # Patrimonio menos evidente pero que si es destino
    "pyramid": 0.85,
    "manor": 0.6,
    "wreck": 0.6,
    "church": 0.55,
    "place_of_worship": 0.5,
    # Mobiliario urbano y detalles del paisaje: existen, pero nadie planifica
    # un dia alrededor
    "park": 0.3,
    "artwork": 0.3,
    "wayside_cross": 0.2,
    "wayside_shrine": 0.2,
    "boundary_stone": 0.1,
    "stone": 0.1,
    "building": 0.1,
    "house": 0.1,
    "tomb": 0.25,
}

# Lo desconocido queda fuera por defecto. Es una lista de permitidos a
# proposito: con el criterio inverso, cualquier etiqueta nueva de
# OpenStreetMap se colaria sola en los itinerarios sin que nadie lo decida.
DEFAULT_APPEAL = 0.25

# Debajo de este atractivo un lugar no entra al itinerario aunque este cerca.
MIN_APPEAL = 0.45

LUNCH_WINDOW = (time(11, 30), time(14, 30))
DINNER_WINDOW = (time(18, 0), time(21, 0))


@dataclass
class Constraints:
    """Lo que el usuario pidio, en forma de limites verificables.

    Todo lo que aparece aqui se puede comprobar sobre el itinerario terminado.
    Una preferencia que no se pueda medir no es una restriccion.
    """

    days: int
    center_lat: float
    center_lon: float

    radius_m: int = 20_000
    earliest_start: time = time(9, 0)
    latest_end: time = time(20, 0)
    # Limite duro de traslado por dia. Es la traduccion de "quiero caminar
    # poco" o "no quiero pasarme el dia en el carro".
    max_travel_km_per_day: float = 25.0
    mode: str = "driving"

    preferred_categories: list[Category] = field(default_factory=list)
    avoided_categories: list[Category] = field(default_factory=list)
    include_meals: bool = True
    max_stops_per_day: int = 5
    min_quality: float = 0.0


@dataclass
class Stop:
    place: PlaceHit
    arrival: time
    departure: time
    travel_minutes_from_previous: int = 0
    travel_km_from_previous: float = 0.0
    # None, "lunch" o "dinner". Distinguirlas importa: cada una tiene su
    # franja horaria y tratarlas igual produce cenas a las tres de la tarde.
    meal: str | None = None

    @property
    def is_meal(self) -> bool:
        return self.meal is not None


@dataclass
class Day:
    number: int
    stops: list[Stop] = field(default_factory=list)

    @property
    def travel_km(self) -> float:
        return round(sum(s.travel_km_from_previous for s in self.stops), 2)

    @property
    def start(self) -> time | None:
        return self.stops[0].arrival if self.stops else None

    @property
    def end(self) -> time | None:
        return self.stops[-1].departure if self.stops else None


@dataclass
class Violation:
    """Una restriccion que no se pudo cumplir, con su magnitud.

    Se informa en vez de ocultarse: un itinerario que empieza a las 8:30
    cuando se pidieron las 10:00 es un fallo, y el usuario tiene que verlo.
    """

    constraint: str
    day: int | None
    detail: str


@dataclass
class Itinerary:
    days: list[Day]
    violations: list[Violation] = field(default_factory=list)
    unused_candidates: int = 0

    @property
    def satisfies_all_constraints(self) -> bool:
        return not self.violations

    @property
    def total_stops(self) -> int:
        return sum(len(d.stops) for d in self.days)


# --------------------------------------------------------------------------
# Geometria
# --------------------------------------------------------------------------


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en linea recta entre dos puntos, en kilometros."""
    from math import asin, cos, radians, sin, sqrt

    radio_tierra = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radio_tierra * asin(sqrt(a))


def estimate_travel(origen: PlaceHit, destino: PlaceHit, mode: str) -> tuple[float, int]:
    """Kilometros y minutos estimados entre dos paradas.

    Es una aproximacion a proposito: la fase 4 la reemplaza por tiempos reales
    de OpenRouteService. La firma se mantiene para que el cambio sea sustituir
    esta funcion y nada mas.
    """
    km = haversine_km(origen.lat, origen.lon, destino.lat, destino.lon) * DETOUR_FACTOR
    velocidad = SPEED_KMH.get(mode, SPEED_KMH["driving"])
    return round(km, 3), max(1, round(km / velocidad * 60))


# --------------------------------------------------------------------------
# Seleccion y orden
# --------------------------------------------------------------------------


def appeal_of(hit: PlaceHit) -> float:
    """Que tan visitable es el lugar, segun su subcategoria de OSM."""
    return SUBCATEGORY_APPEAL.get(hit.subcategory or "", DEFAULT_APPEAL)


def score_candidate(hit: PlaceHit, constraints: Constraints) -> float:
    """Que tan bien encaja un lugar con lo que pidio el usuario.

    El atractivo pesa mas que lo completo del registro: un volcan sin horarios
    publicados sigue siendo mejor destino que una plaza bien documentada.
    """
    puntaje = appeal_of(hit) * 2 + hit.quality_score

    if hit.category in {c.value for c in constraints.preferred_categories}:
        puntaje += 0.6
    if hit.category in {c.value for c in constraints.avoided_categories}:
        puntaje -= 2.0

    return puntaje


def order_by_proximity(paradas: list[PlaceHit]) -> list[PlaceHit]:
    """Ordena las paradas para recorrerlas sin zigzaguear.

    Vecino mas cercano y despues 2-opt. Con cinco paradas por dia el optimo se
    podria calcular por fuerza bruta, pero 2-opt escala si algun dia crece y
    en la practica llega al mismo resultado.
    """
    if len(paradas) <= 2:
        return paradas

    restantes = paradas[1:]
    ruta = [paradas[0]]
    while restantes:
        actual = ruta[-1]
        siguiente = min(
            restantes,
            key=lambda p: haversine_km(actual.lat, actual.lon, p.lat, p.lon),
        )
        ruta.append(siguiente)
        restantes.remove(siguiente)

    return _two_opt(ruta)


def _route_km(ruta: list[PlaceHit]) -> float:
    return sum(
        haversine_km(a.lat, a.lon, b.lat, b.lon) for a, b in zip(ruta, ruta[1:], strict=False)
    )


def _two_opt(ruta: list[PlaceHit]) -> list[PlaceHit]:
    """Deshace los cruces de la ruta invirtiendo tramos."""
    mejorada = True
    while mejorada:
        mejorada = False
        for i in range(1, len(ruta) - 1):
            for j in range(i + 1, len(ruta)):
                candidata = ruta[:i] + ruta[i : j + 1][::-1] + ruta[j + 1 :]
                if _route_km(candidata) < _route_km(ruta) - 0.001:
                    ruta = candidata
                    mejorada = True
    return ruta


def _fits_travel_budget(
    ruta: list[PlaceHit], nueva: PlaceHit, constraints: Constraints
) -> bool:
    """Comprueba si agregar una parada mantiene el dia dentro del limite."""
    tentativa = order_by_proximity([*ruta, nueva])
    return _route_km(tentativa) * DETOUR_FACTOR <= constraints.max_travel_km_per_day


def build_days(candidatos: list[PlaceHit], constraints: Constraints) -> list[list[PlaceHit]]:
    """Reparte los candidatos en dias agrupados geograficamente.

    Cada dia arranca por el mejor lugar sin usar y se completa con los mas
    cercanos que quepan en el presupuesto de traslado. Asi los dias salen
    compactos sin necesidad de un algoritmo de agrupamiento aparte: la
    cercania es el criterio de llenado.
    """
    disponibles = sorted(
        candidatos, key=lambda h: score_candidate(h, constraints), reverse=True
    )
    dias: list[list[PlaceHit]] = []

    for _ in range(constraints.days):
        if not disponibles:
            break

        semilla = disponibles.pop(0)
        dia = [semilla]

        # Sin comida los cupos son solo para destinos; con comida se reservan
        # dos lugares para almuerzo y cena.
        cupo = constraints.max_stops_per_day - (2 if constraints.include_meals else 0)
        cupo = max(cupo, 1)

        while len(dia) < cupo:
            cercanos = sorted(
                (h for h in disponibles if h.category != Category.food.value),
                key=lambda h: haversine_km(semilla.lat, semilla.lon, h.lat, h.lon),
            )
            agregado = False
            for candidato in cercanos[:15]:
                if _fits_travel_budget(dia, candidato, constraints):
                    dia.append(candidato)
                    disponibles.remove(candidato)
                    agregado = True
                    break
            if not agregado:
                break

        dias.append(order_by_proximity(dia))

    return dias


# --------------------------------------------------------------------------
# Horarios
# --------------------------------------------------------------------------


def _add_minutes(momento: time, minutos: int) -> time:
    total = momento.hour * 60 + momento.minute + minutos
    return time((total // 60) % 24, total % 60)


def _minutes_between(desde: time, hasta: time) -> int:
    return (hasta.hour * 60 + hasta.minute) - (desde.hour * 60 + desde.minute)


def _insert_meals(
    ruta: list[PlaceHit], comidas: list[PlaceHit], constraints: Constraints
) -> list[tuple[PlaceHit, str | None]]:
    """Intercala almuerzo y cena entre las paradas del dia.

    La comida se elige por cercania a la parada anterior: mandar al usuario
    quince kilometros a almorzar rompe el dia aunque el restaurante sea mejor.
    """
    if not constraints.include_meals or not comidas:
        return [(p, None) for p in ruta]

    resultado: list[tuple[PlaceHit, str | None]] = []
    disponibles = list(comidas)
    momento = constraints.earliest_start
    almuerzo_puesto = False

    for indice, parada in enumerate(ruta):
        if indice:
            _, minutos = estimate_travel(ruta[indice - 1], parada, constraints.mode)
            momento = _add_minutes(momento, minutos)

        # Si al llegar a esta parada ya paso la hora de almorzar, primero se come.
        if not almuerzo_puesto and disponibles and momento >= LUNCH_WINDOW[0]:
            referencia = resultado[-1][0] if resultado else parada
            comida = min(
                disponibles,
                key=lambda c: haversine_km(referencia.lat, referencia.lon, c.lat, c.lon),
            )
            disponibles.remove(comida)
            resultado.append((comida, "lunch"))
            almuerzo_puesto = True
            momento = _add_minutes(momento, DEFAULT_DURATIONS[Category.food])

        resultado.append((parada, None))
        duracion = DEFAULT_DURATIONS.get(Category(parada.category), 60)
        momento = _add_minutes(momento, duracion)

    # La cena solo se agrega si el dia llega de verdad a la tarde. Sin esta
    # comprobacion, un dia que termina a las tres cierra con una "cena" que en
    # realidad es un segundo almuerzo.
    hora_minima_de_cena = _add_minutes(DINNER_WINDOW[0], -60)
    llega_a_la_tarde = momento >= hora_minima_de_cena
    hay_tiempo = _minutes_between(momento, DINNER_WINDOW[1]) >= 60

    if disponibles and llega_a_la_tarde and hay_tiempo:
        referencia = resultado[-1][0]
        cena = min(
            disponibles,
            key=lambda c: haversine_km(referencia.lat, referencia.lon, c.lat, c.lon),
        )
        resultado.append((cena, "dinner"))

    return resultado


def schedule_day(
    numero: int, secuencia: list[tuple[PlaceHit, str | None]], constraints: Constraints
) -> Day:
    """Asigna horas de llegada y salida respetando la hora minima de inicio."""
    dia = Day(number=numero)
    momento = constraints.earliest_start

    for indice, (lugar, comida) in enumerate(secuencia):
        km = 0.0
        minutos = 0
        if indice:
            anterior = secuencia[indice - 1][0]
            km, minutos = estimate_travel(anterior, lugar, constraints.mode)
            momento = _add_minutes(momento, minutos)

        # Cada comida espera a que abra su propia franja.
        if comida == "lunch" and momento < LUNCH_WINDOW[0]:
            momento = LUNCH_WINDOW[0]
        elif comida == "dinner" and momento < DINNER_WINDOW[0]:
            momento = DINNER_WINDOW[0]

        duracion = DEFAULT_DURATIONS.get(Category(lugar.category), 60)
        salida = _add_minutes(momento, duracion)

        dia.stops.append(
            Stop(
                place=lugar,
                arrival=momento,
                departure=salida,
                travel_minutes_from_previous=minutos,
                travel_km_from_previous=km,
                meal=comida,
            )
        )
        momento = salida

    return dia


# --------------------------------------------------------------------------
# Verificacion
# --------------------------------------------------------------------------


def validate(itinerario: Itinerary, constraints: Constraints) -> list[Violation]:
    """Comprueba el itinerario terminado contra cada restriccion.

    Es la funcion que hace medible el proyecto: sobre un conjunto de peticiones
    con restricciones conocidas se puede contar que porcentaje de itinerarios
    las cumple todas.
    """
    violaciones: list[Violation] = []

    for dia in itinerario.days:
        if not dia.stops:
            continue

        if dia.start and dia.start < constraints.earliest_start:
            violaciones.append(
                Violation(
                    "earliest_start",
                    dia.number,
                    f"empieza a las {dia.start:%H:%M} y se pidio no antes de "
                    f"las {constraints.earliest_start:%H:%M}",
                )
            )

        if dia.end and dia.end > constraints.latest_end:
            violaciones.append(
                Violation(
                    "latest_end",
                    dia.number,
                    f"termina a las {dia.end:%H:%M} y se pidio no despues de "
                    f"las {constraints.latest_end:%H:%M}",
                )
            )

        if dia.travel_km > constraints.max_travel_km_per_day:
            violaciones.append(
                Violation(
                    "max_travel_km_per_day",
                    dia.number,
                    f"{dia.travel_km} km recorridos, el limite era "
                    f"{constraints.max_travel_km_per_day}",
                )
            )

        if len(dia.stops) > constraints.max_stops_per_day:
            violaciones.append(
                Violation(
                    "max_stops_per_day",
                    dia.number,
                    f"{len(dia.stops)} paradas, el limite era {constraints.max_stops_per_day}",
                )
            )

        evitadas = {c.value for c in constraints.avoided_categories}
        for parada in dia.stops:
            if parada.place.category in evitadas:
                violaciones.append(
                    Violation(
                        "avoided_categories",
                        dia.number,
                        f"{parada.place.name} es de categoria "
                        f"{parada.place.category}, que se pidio evitar",
                    )
                )

    if len(itinerario.days) < constraints.days:
        violaciones.append(
            Violation(
                "days",
                None,
                f"se armaron {len(itinerario.days)} dias de {constraints.days} "
                "pedidos: no hay suficientes lugares en la zona",
            )
        )

    return violaciones


# --------------------------------------------------------------------------
# Entrada publica
# --------------------------------------------------------------------------


def _day_travel_km(secuencia: list[tuple[PlaceHit, str | None]], mode: str) -> float:
    """Kilometros reales de un dia, comidas incluidas."""
    return round(
        sum(
            estimate_travel(a, b, mode)[0]
            for (a, _), (b, _) in zip(secuencia, secuencia[1:], strict=False)
        ),
        2,
    )


def _trim_to_budget(
    grupo: list[PlaceHit], comidas: list[PlaceHit], constraints: Constraints
) -> list[tuple[PlaceHit, str | None]]:
    """Arma el dia y le quita paradas hasta que entre en el presupuesto.

    El limite se comprueba sobre la secuencia final, con las comidas ya
    intercaladas: un restaurante a ocho kilometros del recorrido suma
    kilometros que la seleccion de destinos nunca conto.

    Se descarta la parada que mas traslado aporta, no la ultima, porque la
    culpable del exceso suele estar en el medio.
    """
    restantes = list(grupo)

    while restantes:
        secuencia = _insert_meals(order_by_proximity(restantes), comidas, constraints)
        if _day_travel_km(secuencia, constraints.mode) <= constraints.max_travel_km_per_day:
            return secuencia
        if len(restantes) == 1:
            break

        # Costo de cada destino: lo que se ahorraria quitandolo.
        ordenadas = order_by_proximity(restantes)
        base = _route_km(ordenadas)
        peor = max(
            restantes,
            key=lambda p: base
            - _route_km(order_by_proximity([x for x in restantes if x is not p])),
        )
        restantes.remove(peor)

    return _insert_meals(order_by_proximity(restantes), comidas, constraints)


def plan(db: Session, constraints: Constraints) -> Itinerary:
    """Arma un itinerario que respeta las restricciones dadas."""
    candidatos = search_in_area(
        db,
        constraints.center_lat,
        constraints.center_lon,
        radius_m=constraints.radius_m,
        min_quality=constraints.min_quality,
        per_category=25,
    )

    evitadas = {c.value for c in constraints.avoided_categories}
    candidatos = [c for c in candidatos if c.category not in evitadas]

    # Fuera el mobiliario urbano: plazas, redondeles y estatuas conmemorativas
    # no son destinos aunque esten catalogados.
    candidatos = [
        c
        for c in candidatos
        if c.category == Category.food.value or appeal_of(c) >= MIN_APPEAL
    ]

    comidas = [c for c in candidatos if c.category == Category.food.value]
    destinos = [c for c in candidatos if c.category != Category.food.value]

    grupos = build_days(destinos, constraints)

    dias: list[Day] = []
    comidas_restantes = list(comidas)
    for numero, grupo in enumerate(grupos, start=1):
        # Cada dia toma las comidas mas cercanas a su primera parada, para no
        # repetir restaurante entre dias.
        cercanas = sorted(
            comidas_restantes,
            key=lambda c: haversine_km(grupo[0].lat, grupo[0].lon, c.lat, c.lon),
        )[:4]
        secuencia = _trim_to_budget(grupo, cercanas, constraints)
        for lugar, comida in secuencia:
            if comida and lugar in comidas_restantes:
                comidas_restantes.remove(lugar)
        dias.append(schedule_day(numero, secuencia, constraints))

    itinerario = Itinerary(
        days=dias,
        unused_candidates=len(destinos) - sum(len(g) for g in grupos),
    )
    itinerario.violations = validate(itinerario, constraints)
    return itinerario


def used_place_ids(itinerario: Itinerary) -> set[uuid.UUID]:
    return {s.place.id for d in itinerario.days for s in d.stops}


def day_duration(dia: Day) -> timedelta:
    if not dia.stops:
        return timedelta()
    return timedelta(minutes=_minutes_between(dia.start, dia.end))
