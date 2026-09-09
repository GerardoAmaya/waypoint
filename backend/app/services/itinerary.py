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
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import time, timedelta

from sqlalchemy.orm import Session

from app.models import Category
from app.services.geo import EstimatedTravel, TravelProvider
from app.services.places import PlaceHit, search_in_area
from app.services.places import by_ids as places_by_ids

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

# La geometria y las velocidades viven en geo.py. El motor ya no las toca
# directamente: pide traslados al proveedor y no sabe como se midieron.

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

# Duracion tipica de una parada mas su traslado. Sirve para estimar hasta que
# hora llega el dia antes de armarlo, que es cuando hay que decidir cuantos
# cupos reservar para comer.
TYPICAL_STOP_MINUTES = 90


def _as_minutes(momento: time) -> int:
    return momento.hour * 60 + momento.minute


def _meals_that_fit(constraints: Constraints) -> int:
    """Cuantas comidas puede llegar a colocar un dia con estas restricciones.

    Con los cinco cupos que trae por defecto, un dia arranca a las nueve y
    termina cerca de las cuatro y media: nunca llega a la cena. Reservar dos
    cupos ahi deja uno permanentemente vacio, y no en un caso raro sino en el
    caso normal.

    La cuenta se hace en minutos y no con _add_minutes porque esa funcion da
    la vuelta al reloj, y un dia de doce paradas terminaria "a las tres de la
    manana" pareciendo mas corto que uno de cinco.
    """
    if not constraints.include_meals:
        return 0

    fin_estimado = (
        _as_minutes(constraints.earliest_start)
        + constraints.max_stops_per_day * TYPICAL_STOP_MINUTES
    )
    llega_a_la_cena = fin_estimado >= _as_minutes(DINNER_WINDOW[0]) and _as_minutes(
        constraints.latest_end
    ) >= _as_minutes(DINNER_WINDOW[0])

    return 2 if llega_a_la_cena else 1


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
class Advice:
    """Algo que el viajero deberia saber, que no es un limite incumplido.

    **No es lo mismo que una violacion y mezclarlos empeora las dos cosas.**
    Una violacion es "rompi un limite que pusiste": el dia se paso de los
    kilometros, empezo antes de la hora. Un consejo es "no pude darte algo
    que querias, esto es por que, y esto podes hacer".

    El almuerzo es el caso claro. Que el comedor mas cercano quede fuera del
    presupuesto de traslado no es romper una regla, y la solucion del mundo
    real es llevar comida, no saltarse un volcan. Con los dos en la misma
    bolsa, "cumple todas las restricciones" deja de significar nada.
    """

    kind: str
    day: int | None
    detail: str


@dataclass
class Itinerary:
    days: list[Day]
    violations: list[Violation] = field(default_factory=list)
    advice: list[Advice] = field(default_factory=list)
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


def estimate_travel(origen: PlaceHit, destino: PlaceHit, mode: str) -> tuple[float, int]:
    """Kilometros y minutos estimados entre dos paradas.

    Desde la fase 4 esto es el respaldo, no la fuente principal: se usa cuando
    no hay rutas reales disponibles. Se conserva como funcion porque es la
    forma mas corta de medir un traslado suelto sin construir un proveedor.
    """
    return EstimatedTravel(mode).between(origen, destino)


def _travel_or_estimate(travel: TravelProvider | None, mode: str) -> TravelProvider:
    """El proveedor dado, o la estimacion geodesica si no hay ninguno.

    Que el respaldo sea el valor por defecto y no una rama de emergencia es
    deliberado: el camino degradado se ejercita en cada test del motor, asi que
    no puede pudrirse sin que alguien se entere.
    """
    return travel if travel is not None else EstimatedTravel(mode)


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


def order_by_proximity(
    paradas: list[PlaceHit], travel: TravelProvider | None = None
) -> list[PlaceHit]:
    """Ordena las paradas para recorrerlas sin zigzaguear.

    Vecino mas cercano y despues 2-opt. Con cinco paradas por dia el optimo se
    podria calcular por fuerza bruta, pero 2-opt escala si algun dia crece y
    en la practica llega al mismo resultado.

    Con rutas reales el orden puede diferir del que da la linea recta, y es
    justamente el punto: dos lugares separados por un volcan estan cerca en el
    mapa y lejos en la carretera.
    """
    if len(paradas) <= 2:
        return paradas

    medidor = _travel_or_estimate(travel, "driving")
    restantes = paradas[1:]
    ruta = [paradas[0]]
    while restantes:
        actual = ruta[-1]
        siguiente = min(restantes, key=lambda p: medidor.between(actual, p)[0])
        ruta.append(siguiente)
        restantes.remove(siguiente)

    return _two_opt(ruta, medidor)


def _route_km(ruta: list[PlaceHit], travel: TravelProvider | None = None) -> float:
    """Kilometros de recorrido de la ruta completa.

    Devuelve distancia de traslado, no distancia en linea recta. Quien use
    este valor no debe multiplicarlo por ningun factor de correccion: antes de
    la fase 4 habia dos convenciones conviviendo y el limite diario se
    comprobaba contra una y se reportaba contra la otra.
    """
    medidor = _travel_or_estimate(travel, "driving")
    return sum(medidor.between(a, b)[0] for a, b in zip(ruta, ruta[1:], strict=False))


def _two_opt(ruta: list[PlaceHit], travel: TravelProvider | None = None) -> list[PlaceHit]:
    """Deshace los cruces de la ruta invirtiendo tramos."""
    medidor = _travel_or_estimate(travel, "driving")
    mejorada = True
    while mejorada:
        mejorada = False
        for i in range(1, len(ruta) - 1):
            for j in range(i + 1, len(ruta)):
                candidata = ruta[:i] + ruta[i : j + 1][::-1] + ruta[j + 1 :]
                if _route_km(candidata, medidor) < _route_km(ruta, medidor) - 0.001:
                    ruta = candidata
                    mejorada = True
    return ruta


def _fits_travel_budget(
    ruta: list[PlaceHit],
    nueva: PlaceHit,
    constraints: Constraints,
    travel: TravelProvider | None = None,
) -> bool:
    """Comprueba si agregar una parada mantiene el dia dentro del limite."""
    medidor = _travel_or_estimate(travel, constraints.mode)
    tentativa = order_by_proximity([*ruta, nueva], medidor)
    return _route_km(tentativa, medidor) <= constraints.max_travel_km_per_day


def build_days(
    candidatos: list[PlaceHit],
    constraints: Constraints,
    travel: TravelProvider | None = None,
    meal_options: int = 2,
) -> list[list[PlaceHit]]:
    """Reparte los candidatos en dias agrupados geograficamente.

    Cada dia arranca por el mejor lugar sin usar y se completa con los mas
    cercanos que quepan en el presupuesto de traslado. Asi los dias salen
    compactos sin necesidad de un algoritmo de agrupamiento aparte: la
    cercania es el criterio de llenado.
    """
    medidor = _travel_or_estimate(travel, constraints.mode)

    # **Lo que se pidio evitar se descarta, no se penaliza.** Restarle puntos
    # en el ranking solo lo manda al final de la lista, y basta con que sobre
    # un cupo para que entre igual. La restriccion es dura y el motor la tiene
    # que hacer cumplir el mismo: depender de que select_candidates haya
    # filtrado antes deja el limite a merced de quien llame.
    evitadas = {c.value for c in constraints.avoided_categories}
    admisibles = [h for h in candidatos if h.category not in evitadas]

    disponibles = sorted(
        admisibles, key=lambda h: score_candidate(h, constraints), reverse=True
    )
    dias: list[list[PlaceHit]] = []

    for _ in range(constraints.days):
        if not disponibles:
            break

        semilla = disponibles.pop(0)
        dia = [semilla]

        # Sin comida los cupos son solo para destinos; con comida se reserva
        # sitio para las que de verdad se van a poder colocar.
        #
        # **La reserva se limita a las comidas que de verdad existen.** Guardar
        # dos cupos donde el catalogo no tiene ni un restaurante deja el dia en
        # tres paradas terminando a la una de la tarde, con siete horas de
        # margen sin usar y sin nada que ocupe el sitio reservado. Pasa dentro
        # de los parques nacionales, que es justo donde mas hay que caminar.
        #
        # La cuenta es del itinerario entero y no de cada dia: build_days arma
        # todos los grupos antes de que se repartan las comidas. Con tres
        # restaurantes para cinco dias, los ultimos dias reservan sitio que no
        # van a llenar. Es una imprecision acotada, a diferencia de la de
        # reservar contra cero.
        reservados = min(_meals_that_fit(constraints), max(0, meal_options))
        cupo = max(constraints.max_stops_per_day - reservados, 1)

        while len(dia) < cupo:
            cercanos = sorted(
                (h for h in disponibles if h.category != Category.food.value),
                key=lambda h: medidor.between(semilla, h)[0],
            )
            agregado = False
            for candidato in cercanos[:15]:
                if _fits_travel_budget(dia, candidato, constraints, medidor):
                    dia.append(candidato)
                    disponibles.remove(candidato)
                    agregado = True
                    break
            if not agregado:
                break

        dias.append(order_by_proximity(dia, medidor))

    return dias


# --------------------------------------------------------------------------
# Horarios
# --------------------------------------------------------------------------


def _add_minutes(momento: time, minutos: int) -> time:
    total = momento.hour * 60 + momento.minute + minutos
    return time((total // 60) % 24, total % 60)


def _minutes_between(desde: time, hasta: time) -> int:
    return (hasta.hour * 60 + hasta.minute) - (desde.hour * 60 + desde.minute)


def _sequence_km(
    secuencia: list[tuple[PlaceHit, str | None]], travel: TravelProvider
) -> float:
    return sum(
        travel.between(a, b)[0]
        for (a, _), (b, _) in zip(secuencia, secuencia[1:], strict=False)
    )


def _arrival_times(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
) -> list[time]:
    """Hora de llegada a cada elemento, con las esperas de franja aplicadas.

    Es la misma cuenta que hace schedule_day. Se separa porque hay que poder
    evaluar una secuencia tentativa antes de comprometerse con ella.
    """
    momento = constraints.earliest_start
    horas: list[time] = []

    for indice, (lugar, comida) in enumerate(secuencia):
        if indice:
            _, minutos = travel.between(secuencia[indice - 1][0], lugar)
            momento = _add_minutes(momento, minutos)
        if comida == "lunch" and momento < LUNCH_WINDOW[0]:
            momento = LUNCH_WINDOW[0]
        elif comida == "dinner" and momento < DINNER_WINDOW[0]:
            momento = DINNER_WINDOW[0]
        horas.append(momento)
        momento = _add_minutes(momento, DEFAULT_DURATIONS.get(Category(lugar.category), 60))

    return horas


# Cuanto se tolera llegar antes de que abra la franja. Mas que esto y el dia
# se queda esperando de brazos cruzados a que sirvan.
MEAL_EARLY_TOLERANCE_MINUTES = 30

# Cuantos restaurantes se consideran por dia. Eran cuatro, elegidos por
# cercania a la PRIMERA parada del dia, y las dos cosas estaban mal.
#
# Cuatro es poco: el almuerzo consume uno y a la cena le quedan tres. Y la
# primera parada es un ancla arbitraria: si el dia arranca en un cerro remoto,
# los cuatro mas cercanos a ese cerro pueden estar todos lejos del resto del
# recorrido, y la insercion los rechaza a todos por presupuesto.
MEAL_CANDIDATES_PER_DAY = 8


def _meal_candidates(
    grupo: list[PlaceHit],
    comidas: list[PlaceHit],
    travel: TravelProvider,
    limit: int = MEAL_CANDIDATES_PER_DAY,
) -> list[PlaceHit]:
    """Los restaurantes mas convenientes para un dia.

    Se mide contra la parada MAS CERCANA del dia, no contra la primera. Un dia
    que empieza lejos y termina en el pueblo tiene restaurantes convenientes
    al final, y anclarse en el arranque no los ve.
    """
    if not grupo or not comidas:
        return []

    def cercania(comida: PlaceHit) -> float:
        return min(travel.between(parada, comida)[0] for parada in grupo)

    return sorted(comidas, key=cercania)[:limit]


def _best_meal_insertion(
    secuencia: list[tuple[PlaceHit, str | None]],
    disponibles: list[PlaceHit],
    tipo: str,
    ventana: tuple[time, time],
    constraints: Constraints,
    travel: TravelProvider,
    enforce_budget: bool = True,
) -> tuple[list[tuple[PlaceHit, str | None]], PlaceHit | None, float]:
    """Mete la comida donde menos kilometros cueste, entre las posiciones que dan la hora.

    **El costo del regreso tiene que entrar en la cuenta.** Elegir el
    restaurante mas cercano a la parada anterior parece razonable y produce
    dias como este: tres paradas dentro de un parque nacional, salida de
    dieciseis kilometros a almorzar al pueblo, y vuelta de quince al parque.
    Treinta y cuatro kilometros para un dia que en el parque son cinco.

    La insercion mas barata mira la secuencia entera y encuentra sola que el
    almuerzo va al final: se sale una vez y no se vuelve.

    **El limite de traslado sigue mandando sobre la comida.** Si el unico
    restaurante de la zona esta a cuarenta kilometros y el usuario pidio no
    pasar de quince, no hay almuerzo: validate() lo reporta como restriccion
    incumplida y el usuario decide si lleva comida o levanta el limite. Meter
    la comida rompiendo el limite seria elegir por el.
    """
    # **El tope de paradas se comprueba aqui y no se predice antes.** La
    # reserva de cupos en build_days estima cuantas comidas van a caber; si la
    # estimacion dice una y despues la cena tambien entra por hora, el dia
    # termina con seis paradas y el limite era cinco. Una restriccion dura no
    # se puede predecir, se hace cumplir donde se puede garantizar.
    if len(secuencia) >= constraints.max_stops_per_day:
        return secuencia, None, 0.0

    base_km = _sequence_km(secuencia, travel)
    limite_temprano = _add_minutes(ventana[0], -MEAL_EARLY_TOLERANCE_MINUTES)
    mejor: tuple[float, list[tuple[PlaceHit, str | None]], PlaceHit] | None = None

    for comida in disponibles:
        for posicion in range(1, len(secuencia) + 1):
            tentativa = secuencia[:posicion] + [(comida, tipo)] + secuencia[posicion:]
            horas = _arrival_times(tentativa, constraints, travel)

            # La hora sin la espera de franja: sirve para descartar las
            # posiciones que obligarian a esperar media manana sentado.
            natural = _arrival_times(
                [*tentativa[:posicion], (comida, None), *tentativa[posicion + 1 :]],
                constraints,
                travel,
            )[posicion]

            if natural > ventana[1] or natural < limite_temprano:
                continue
            if horas[posicion] > ventana[1]:
                continue

            total = _sequence_km(tentativa, travel)
            if enforce_budget and total > constraints.max_travel_km_per_day:
                continue

            costo = total - base_km
            if mejor is None or costo < mejor[0]:
                mejor = (costo, tentativa, comida)

    if mejor is None:
        return secuencia, None, 0.0
    return mejor[1], mejor[2], mejor[0]


def _insert_meals(
    ruta: list[PlaceHit],
    comidas: list[PlaceHit],
    constraints: Constraints,
    travel: TravelProvider | None = None,
) -> list[tuple[PlaceHit, str | None]]:
    """Intercala almuerzo y cena entre las paradas del dia.

    Cada comida va donde menos kilometros agregue, entre las posiciones cuya
    hora cae dentro de la franja. Antes se elegia por cercania a la parada
    anterior, que ignoraba el regreso y partia los dias en dos.
    """
    secuencia: list[tuple[PlaceHit, str | None]] = [(p, None) for p in ruta]

    if not constraints.include_meals or not comidas or not ruta:
        return secuencia

    medidor = _travel_or_estimate(travel, constraints.mode)
    disponibles = list(comidas)

    secuencia, almuerzo, _ = _best_meal_insertion(
        secuencia, disponibles, "lunch", LUNCH_WINDOW, constraints, medidor
    )
    if almuerzo is not None:
        disponibles.remove(almuerzo)

    if disponibles:
        secuencia, _, _ = _best_meal_insertion(
            secuencia, disponibles, "dinner", DINNER_WINDOW, constraints, medidor
        )

    return secuencia


def schedule_day(
    numero: int,
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider | None = None,
) -> Day:
    """Asigna horas de llegada y salida respetando la hora minima de inicio."""
    medidor = _travel_or_estimate(travel, constraints.mode)
    dia = Day(number=numero)
    momento = constraints.earliest_start

    for indice, (lugar, comida) in enumerate(secuencia):
        km = 0.0
        minutos = 0
        if indice:
            anterior = secuencia[indice - 1][0]
            km, minutos = medidor.between(anterior, lugar)
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

        # La comida que falta ya no se reporta aqui: es un consejo y no una
        # violacion. Ver advise().

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


def advise(
    itinerario: Itinerary,
    constraints: Constraints,
    comidas: list[PlaceHit],
    travel: TravelProvider | None = None,
) -> list[Advice]:
    """Lo que el viajero deberia saber y no es un limite incumplido.

    Hoy son las comidas. **El aviso lleva el numero**, porque "no hay donde
    comer" era falso en casi todos los casos: Santa Ana tiene trescientos
    lugares de comida, lo que no habia era uno que entrara en el presupuesto
    de kilometros. Decir la causa equivocada es peor que no decir nada, y
    "llevá almuerzo, el comedor mas cercano suma 14 km sobre tu limite de 25"
    es accionable donde "no hay donde comer" no lo es.
    """
    medidor = _travel_or_estimate(travel, constraints.mode)
    consejos: list[Advice] = []

    if not constraints.include_meals:
        return consejos

    for dia in itinerario.days:
        if not dia.stops or not dia.start or not dia.end:
            continue

        cruza_almuerzo = dia.start <= LUNCH_WINDOW[1] and dia.end >= LUNCH_WINDOW[0]
        if not cruza_almuerzo or any(p.meal == "lunch" for p in dia.stops):
            continue

        consejos.append(_lunch_advice(dia, constraints, comidas, medidor))

    return consejos


def _lunch_advice(
    dia: Day, constraints: Constraints, comidas: list[PlaceHit], travel: TravelProvider
) -> Advice:
    """Por que no hubo almuerzo, con el numero que lo explica."""
    if not comidas:
        return Advice(
            "bring_lunch",
            dia.number,
            "no hay ningún lugar para comer registrado en esta zona: llevá almuerzo",
        )

    secuencia = [(p.place, p.meal) for p in dia.stops]
    candidatos = _meal_candidates([p.place for p in dia.stops], comidas, travel)

    # Se busca la mejor insercion SIN respetar el presupuesto, justamente para
    # poder decir cuanto se habria pasado.
    _, comida, costo = _best_meal_insertion(
        secuencia,
        candidatos,
        "lunch",
        LUNCH_WINDOW,
        constraints,
        travel,
        enforce_budget=False,
    )

    if comida is None:
        return Advice(
            "bring_lunch",
            dia.number,
            "ningún lugar para comer cae dentro del horario de almuerzo de este "
            "día: llevá almuerzo",
        )

    total = dia.travel_km + costo
    return Advice(
        "bring_lunch",
        dia.number,
        f"el lugar para comer más conveniente es {comida.name}, que agrega "
        f"{costo:.1f} km y dejaría el día en {total:.1f} km, sobre tu límite de "
        f"{constraints.max_travel_km_per_day:.0f}. Llevá almuerzo, o subí el "
        f"límite de traslado a {total:.0f} km",
    )


# --------------------------------------------------------------------------
# Entrada publica
# --------------------------------------------------------------------------


def _day_travel_km(
    secuencia: list[tuple[PlaceHit, str | None]],
    mode: str,
    travel: TravelProvider | None = None,
) -> float:
    """Kilometros de traslado de un dia, comidas incluidas."""
    medidor = _travel_or_estimate(travel, mode)
    return round(
        sum(
            medidor.between(a, b)[0]
            for (a, _), (b, _) in zip(secuencia, secuencia[1:], strict=False)
        ),
        2,
    )


def _sequence_end(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
) -> time | None:
    """Hora a la que termina la ultima parada de la secuencia."""
    if not secuencia:
        return None
    horas = _arrival_times(secuencia, constraints, travel)
    ultimo, _ = secuencia[-1]
    duracion = DEFAULT_DURATIONS.get(Category(ultimo.category), 60)
    return _add_minutes(horas[-1], duracion)


def _fits_the_day(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
) -> bool:
    """Si el dia entra en el presupuesto de kilometros y en su horario.

    **latest_end era un aviso y no un limite.** validate() lo reportaba y
    nadie lo hacia cumplir: un dia con ventana de 10:00 a 15:00 salia
    terminando a las 16:13. Se recorta igual que por kilometros.
    """
    if _day_travel_km(secuencia, constraints.mode, travel) > constraints.max_travel_km_per_day:
        return False

    fin = _sequence_end(secuencia, constraints, travel)
    return fin is None or fin <= constraints.latest_end


def _trim_to_budget(
    grupo: list[PlaceHit],
    comidas: list[PlaceHit],
    constraints: Constraints,
    travel: TravelProvider | None = None,
) -> list[tuple[PlaceHit, str | None]]:
    """Arma el dia y le quita paradas hasta que entre, con su comida adentro.

    El limite se comprueba sobre la secuencia final, con las comidas ya
    intercaladas: un restaurante a ocho kilometros del recorrido suma
    kilometros que la seleccion de destinos nunca conto.

    Se descarta la parada que mas traslado aporta, no la ultima, porque la
    culpable del exceso suele estar en el medio.

    **El dia NO se achica para hacerle lugar a una comida.** Se intento y
    estaba mal: alguien pide cinco paradas y un almuerzo, y devolverle cuatro
    destinos a cambio de un comedor es decidir por el. Cuando el restaurante
    no entra en el presupuesto, el dia queda completo y se emite el consejo de
    llevar almuerzo, con los kilometros que habria costado. Llevar comida es
    una solucion del mundo real; saltarse un volcan no lo es.
    """
    medidor = _travel_or_estimate(travel, constraints.mode)
    restantes = list(grupo)

    while restantes:
        secuencia = _insert_meals(
            order_by_proximity(restantes, medidor), comidas, constraints, medidor
        )
        if _fits_the_day(secuencia, constraints, medidor):
            return secuencia
        if len(restantes) == 1:
            break

        # Costo de cada destino: lo que se ahorraria quitandolo.
        ordenadas = order_by_proximity(restantes, medidor)
        base = _route_km(ordenadas, medidor)
        peor = max(
            restantes,
            key=lambda p: (
                base
                - _route_km(
                    order_by_proximity([x for x in restantes if x is not p], medidor), medidor
                )
            ),
        )
        restantes.remove(peor)

    return _insert_meals(order_by_proximity(restantes, medidor), comidas, constraints, medidor)


def _crosses_lunch(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
) -> bool:
    """Si el dia llega a la hora de almorzar.

    Un dia que termina a las once no necesita restaurante, y sin esta
    comprobacion el bucle lo achicaria hasta una parada buscando meterle uno.
    """
    if not secuencia:
        return False
    horas = _arrival_times(secuencia, constraints, travel)
    fin = _sequence_end(secuencia, constraints, travel)
    return horas[0] <= LUNCH_WINDOW[1] and fin is not None and fin >= LUNCH_WINDOW[0]


def select_candidates(
    db: Session, constraints: Constraints
) -> tuple[list[PlaceHit], list[PlaceHit]]:
    """Los lugares utilizables de la zona, separados en comidas y destinos.

    Se extrajo de plan() para que la fase 4 pueda saber que lugares entran en
    juego antes de armar el itinerario: sin esa lista no se puede pedir la
    matriz de traslados, y pedirla despues de armar el plan llegaria tarde.
    """
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
    return comidas, destinos


def assemble(
    comidas: list[PlaceHit],
    destinos: list[PlaceHit],
    constraints: Constraints,
    travel: TravelProvider | None = None,
    grupos: list[list[PlaceHit]] | None = None,
) -> Itinerary:
    """Arma el itinerario a partir de candidatos ya seleccionados.

    `grupos` permite reutilizar un reparto de dias hecho antes con otro
    medidor. Es lo que usa plan_with_routing: agrupa con estimaciones sobre
    todos los candidatos, y refina solo los elegidos con rutas reales.
    """
    medidor = _travel_or_estimate(travel, constraints.mode)
    if grupos is None:
        grupos = build_days(destinos, constraints, medidor, meal_options=len(comidas))

    dias: list[Day] = []
    comidas_restantes = list(comidas)
    for numero, grupo in enumerate(grupos, start=1):
        if not grupo:
            continue
        # Cada dia toma las comidas mas cercanas a su primera parada, para no
        # repetir restaurante entre dias.
        cercanas = _meal_candidates(grupo, comidas_restantes, medidor)
        secuencia = _trim_to_budget(grupo, cercanas, constraints, medidor)
        for lugar, comida in secuencia:
            if comida and lugar in comidas_restantes:
                comidas_restantes.remove(lugar)
        dias.append(schedule_day(numero, secuencia, constraints, medidor))

    itinerario = Itinerary(
        days=dias,
        unused_candidates=len(destinos) - sum(len(g) for g in grupos),
    )
    itinerario.violations = validate(itinerario, constraints)
    itinerario.advice = advise(itinerario, constraints, comidas, medidor)
    return itinerario


def plan(
    db: Session, constraints: Constraints, travel: TravelProvider | None = None
) -> Itinerary:
    """Arma un itinerario que respeta las restricciones dadas.

    Sin proveedor de traslados usa distancias estimadas y no toca la red. Para
    rutas reales de OpenRouteService, plan_with_routing.
    """
    comidas, destinos = select_candidates(db, constraints)
    return assemble(comidas, destinos, constraints, travel)


# --------------------------------------------------------------------------
# Construccion por fases
# --------------------------------------------------------------------------


@dataclass
class CandidatesReady:
    """Los lugares utilizables de la zona, antes de repartirlos en dias.

    Llega en microsegundos y sin tocar la red. El mapa ya puede dibujar los
    pines mientras el resto se calcula.
    """

    phase: str = field(default="candidates", init=False)
    destinations: list[PlaceHit] = field(default_factory=list)
    meals: list[PlaceHit] = field(default_factory=list)


@dataclass
class DraftReady:
    """Itinerario completo con distancias estimadas.

    **No es un adelanto parcial: esta armado, ordenado y verificado.** Si la
    llamada a OpenRouteService falla o se acabo el cupo, esto es lo que el
    usuario se queda mirando, y es utilizable. Que el camino degradado sea el
    mismo que el camino normal, una fase antes, es lo que hace que no se pudra
    sin que nadie se entere.
    """

    itinerary: Itinerary
    phase: str = field(default="draft", init=False)


@dataclass
class PlanReady:
    """Itinerario con distancias reales de carretera.

    Cambia el orden del recorrido, los kilometros del dia y las horas de
    llegada. Dos lugares que la linea recta pone juntos pueden estar separados
    por un cerro.
    """

    itinerary: Itinerary
    stats: object | None = None
    phase: str = field(default="plan", init=False)


PlanEvent = CandidatesReady | DraftReady | PlanReady


def plan_streaming(db: Session, constraints: Constraints, client=None) -> Iterator[PlanEvent]:
    """Arma el itinerario emitiendo cada fase en cuanto esta lista.

    **Las fases son las que existen de verdad, no las que quedarian bonitas.**
    La matriz de OpenRouteService es una sola llamada que cubre el itinerario
    entero: partirla por dia costaria una peticion por dia, y con cincuenta
    diarias eso se agota enseguida. Emitir los dias de a uno despues de que la
    matriz ya volvio seria fingir un progreso que no ocurrio.

    Lo que si tiene latencia entre medio es el salto de la estimacion a las
    rutas reales. El borrador se arma sin red y llega de inmediato; la matriz
    tarda lo que tarde y despues corrige. Esa transicion es visible y es real.

    **Agrupa con estimaciones y refina con rutas reales.** La busqueda puede
    devolver ciento cincuenta candidatos, y pedir su matriz completa serian
    veintidos mil pares repartidos en nueve peticiones, casi todas sobre
    lugares que nunca entran al itinerario. Repartir los dias con la
    estimacion cuesta cero y acota el problema a las paradas elegidas mas sus
    restaurantes cercanos: menos de cincuenta lugares, una sola peticion.
    """
    from app.services.routing import client_from_settings, load_travel_matrix

    comidas, destinos = select_candidates(db, constraints)
    yield CandidatesReady(destinations=destinos, meals=comidas)

    estimado = EstimatedTravel(constraints.mode)
    grupos = build_days(destinos, constraints, estimado, meal_options=len(comidas))
    borrador = assemble(comidas, destinos, constraints, estimado, grupos)
    yield DraftReady(itinerary=borrador)

    matriz = load_travel_matrix(
        _places_to_measure(borrador),
        constraints.mode,
        db=db,
        client=client if client is not None else client_from_settings(),
    )

    # El reparto de dias se rehace con distancias reales: dos lugares que la
    # linea recta pone en el mismo dia pueden estar separados por un cerro.
    yield PlanReady(
        itinerary=assemble(comidas, destinos, constraints, matriz),
        stats=matriz.stats,
    )


def _places_to_measure(borrador: Itinerary) -> list[PlaceHit]:
    """Los lugares que el borrador realmente eligio.

    Se derivan del borrador y no se adivinan antes. Adivinarlos obligaba a
    incluir varios restaurantes por dia por si acaso, y con ocho candidatos
    diarios un viaje de siete dias pasaria de cincuenta lugares: la matriz se
    partiria en bloques y costaria cuatro peticiones en vez de una.

    El precio es que las rutas reales no pueden hacer que se elija OTRO
    restaurante, solo corregir las distancias del que ya se eligio. Con
    cincuenta peticiones diarias, pagar cuatro por refinar una eleccion que
    la estimacion ya hizo razonablemente no vale la pena.
    """
    return [parada.place for dia in borrador.days for parada in dia.stops]


def plan_with_routing(
    db: Session, constraints: Constraints, client=None
) -> tuple[Itinerary, object]:
    """Igual que plan(), pero con distancias reales de carretera.

    Consume plan_streaming y devuelve el resultado final. Existe para quien no
    necesita las fases intermedias, que es todo lo que no sea el streaming.
    """
    ultimo: PlanReady | DraftReady | None = None
    for evento in plan_streaming(db, constraints, client):
        if isinstance(evento, DraftReady | PlanReady):
            ultimo = evento

    if isinstance(ultimo, PlanReady):
        return ultimo.itinerary, ultimo.stats
    if ultimo is not None:
        return ultimo.itinerary, None
    return Itinerary(days=[]), None


# --------------------------------------------------------------------------
# Revision de un dia
# --------------------------------------------------------------------------


@dataclass
class DayState:
    """Un dia tal como el cliente lo tiene, para poder reconstruirlo igual.

    Lleva la etiqueta de comida ademas del identificador porque es un viaje de
    ida y vuelta exacto de lo que el servidor emitio. Deducir cual parada era
    el almuerzo por su categoria y su hora funcionaria casi siempre, y "casi"
    en un dia que el usuario no pidio cambiar es un dia que cambia solo.
    """

    number: int
    stops: list[tuple[uuid.UUID, str | None]] = field(default_factory=list)


@dataclass
class RevisionResult:
    itinerary: Itinerary
    stats: object | None = None
    # Paradas que ya no estan en el catalogo. Se informan en vez de omitirse.
    missing: list[uuid.UUID] = field(default_factory=list)


def revise_day(
    db: Session,
    constraints: Constraints,
    state: list[DayState],
    target: int,
    *,
    day_constraints: Constraints | None = None,
    exclude: set[uuid.UUID] | None = None,
    travel: TravelProvider | None = None,
) -> RevisionResult:
    """Rehace un dia y deja los demas exactamente como estaban.

    **Los otros dias no se recalculan, se reconstruyen.** El motor es
    deterministico, asi que volver a planificarlos daria lo mismo... hasta que
    cambie una constante, o la cache traiga una distancia real que antes se
    estimaba. Entonces el usuario pidio tocar el dia 3 y se le movio el 1. Se
    reprograman las paradas que ya tenia, en su orden, y nada mas.

    El dia pedido se rearma con los candidatos de la zona menos todo lo que
    usan los otros dias, para que no aparezca dos veces el mismo lugar.
    """
    excluidos = set(exclude or ())
    medidor = _travel_or_estimate(travel, constraints.mode)
    restricciones_dia = day_constraints or constraints

    referencias = [par[0] for dia in state for par in dia.stops]
    catalogo = places_by_ids(db, referencias)
    faltantes = [ref for ref in referencias if ref not in catalogo]

    # Lo que ocupan los otros dias no puede repetirse en el que se rehace.
    tomados = {
        par[0]
        for dia in state
        if dia.number != target
        for par in dia.stops
        if par[0] in catalogo
    }

    comidas, destinos = select_candidates(db, constraints)
    disponibles = [d for d in destinos if d.id not in tomados and d.id not in excluidos]
    comidas_libres = [c for c in comidas if c.id not in tomados and c.id not in excluidos]

    grupos = build_days(
        disponibles,
        replace(restricciones_dia, days=1),
        medidor,
        meal_options=len(comidas_libres),
    )
    nuevo = grupos[0] if grupos else []

    dias: list[Day] = []
    for dia in sorted(state, key=lambda d: d.number):
        if dia.number == target:
            cercanas = _meal_candidates(nuevo, comidas_libres, medidor)
            secuencia = _trim_to_budget(nuevo, cercanas, restricciones_dia, medidor)
            dias.append(schedule_day(dia.number, secuencia, restricciones_dia, medidor))
            continue

        secuencia = [(catalogo[ref], comida) for ref, comida in dia.stops if ref in catalogo]
        if secuencia:
            dias.append(schedule_day(dia.number, secuencia, constraints, medidor))

    itinerario = Itinerary(days=dias)
    itinerario.violations = validate(itinerario, constraints)
    return RevisionResult(itinerary=itinerario, missing=faltantes)


def revise_with_routing(
    db: Session,
    constraints: Constraints,
    state: list[DayState],
    target: int,
    *,
    day_constraints: Constraints | None = None,
    exclude: set[uuid.UUID] | None = None,
    client=None,
) -> RevisionResult:
    """Revisa un dia con distancias reales de carretera.

    Mismo patron que plan_with_routing: se arma con estimaciones para saber que
    lugares entran en juego, y despues se mide solo esos. Sin ese primer paso
    habria que pedir la matriz de todos los candidatos de la zona para rehacer
    un unico dia.
    """
    from app.services.routing import client_from_settings, load_travel_matrix

    estimado = EstimatedTravel(constraints.mode)
    borrador = revise_day(
        db,
        constraints,
        state,
        target,
        day_constraints=day_constraints,
        exclude=exclude,
        travel=estimado,
    )

    lugares = [parada.place for dia in borrador.itinerary.days for parada in dia.stops]
    matriz = load_travel_matrix(
        lugares,
        constraints.mode,
        db=db,
        client=client if client is not None else client_from_settings(),
    )

    final = revise_day(
        db,
        constraints,
        state,
        target,
        day_constraints=day_constraints,
        exclude=exclude,
        travel=matriz,
    )
    return RevisionResult(itinerary=final.itinerary, stats=matriz.stats, missing=final.missing)


def used_place_ids(itinerario: Itinerary) -> set[uuid.UUID]:
    return {s.place.id for d in itinerario.days for s in d.stops}


def day_duration(dia: Day) -> timedelta:
    if not dia.stops:
        return timedelta()
    return timedelta(minutes=_minutes_between(dia.start, dia.end))
