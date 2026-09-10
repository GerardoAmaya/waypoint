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
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import time, timedelta

from sqlalchemy.orm import Session

from app.models import Category
from app.services.geo import EstimatedTravel, TravelProvider
from app.services.places import PlaceHit, search_in_area
from app.services.places import by_ids as places_by_ids

# Kilometros por dia por defecto segun el modo. Solo se usan cuando un dia va
# en otro modo que el itinerario: es el numero que el prompt ya le sugiere al
# modelo para "caminando" y para "en carro", puesto donde el motor lo necesita.
BUDGET_BY_MODE: dict[str, float] = {"driving": 25.0, "walking": 8.0}

# Cuanto se queda uno en cada tipo de lugar, en minutos. Son estimaciones de
# sentido comun, no datos: un mirador es una parada corta y un parque nacional
# ocupa media manana.
#
# La entrada de comida es para un comedor que NO es la comida del dia: el
# unico caso es el de quien sale y vuelve a un restaurante, donde la vuelta no
# es otra comida. Lo que se tarda comiendo esta en Constraints.meal_minutes,
# porque eso el usuario lo puede decir y esto no.
DEFAULT_DURATIONS: dict[Category, int] = {
    Category.viewpoint: 30,
    Category.food: 60,
    Category.culture: 75,
    Category.attraction: 90,
    Category.nature: 105,
    Category.lodging: 0,
}

# Cuanto dura la visita segun la subcategoria, cuando la hay.
#
# **Seis numeros no alcanzan y se nota en pantalla.** "Cultura" son los 33
# museos del pais y tambien los 86 monumentos: con una sola cifra, el Museo
# Nacional de Antropologia y una estatua en una rotonda ocupaban los mismos 75
# minutos. Subir la categoria entera para que el museo dure dos horas le daba
# dos horas a la estatua.
#
# Es el mismo motivo por el que existe SUBCATEGORY_APPEAL: la categoria dice
# de que tipo es el sitio, y la subcategoria dice que es. Aca solo estan las
# que cambian algo; el resto cae en DEFAULT_DURATIONS.
#
# Son estimaciones de sentido comun, como la tabla por categoria: no hay datos
# de cuanto se queda la gente en cada sitio. Lo que si esta medido es lo que
# cuestan, porque alargar las visitas acorta el dia.
SUBCATEGORY_DURATIONS: dict[str, int] = {
    # Cultura
    "museum": 120,
    "archaeological_site": 105,
    "ruins": 75,
    "pyramid": 75,
    "castle": 75,
    "gallery": 75,
    "arts_centre": 60,
    "manor": 60,
    "church": 30,
    "place_of_worship": 30,
    "wreck": 30,
    # Un monumento es una foto y seguir. Que no dure lo que un museo es la
    # razon de ser de esta tabla.
    "monument": 20,
    "memorial": 20,
    "artwork": 15,
    # Naturaleza
    "volcano": 180,
    "nature_reserve": 150,
    "beach": 150,
    "peak": 120,
    "garden": 120,
    "waterfall": 75,
    "cave_entrance": 60,
    "spring": 45,
    # `park` en OpenStreetMap es cada plaza municipal del pais —687 de ellas—
    # y no el parque nacional, que va etiquetado nature_reserve. Hoy ni entra
    # a los itinerarios: su atractivo es 0.3 y el piso es 0.45.
    "park": 60,
    # Atracciones
    "theme_park": 210,
    "zoo": 150,
}

# Cuanto dura una comida cuando nadie dice lo contrario.
#
# Era una hora, heredada de la tabla de arriba, y una hora es lo que se tarda
# en comer rapido: sentarse, pedir, esperar, comer, pagar y salir no cabe ahi,
# y menos en una cena. Hora y media es el almuerzo normal de un dia que no
# tiene prisa, que es justo el dia que esto planifica.
#
# El numero se puede decir en el prompt —"almuerzo tranquilo de dos horas"—
# porque es de las pocas duraciones que uno sabe de si mismo. Cuanto se queda
# uno en un museo, no.
DEFAULT_MEAL_MINUTES = 90

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

# Tope de paradas cuando el usuario no pidio ninguno. No es una preferencia,
# es una barrera: doce paradas ya no es un dia, y sin un techo cualquier error
# de medida podria convertir un dia en una lista interminable.
MAX_STOPS_HARD_CAP = 12

# A partir de aca ya no hay luz. En El Salvador el sol se pone entre las 17:50
# y las 18:30 durante todo el ano —esta a trece grados de latitud, asi que el
# dia casi no cambia de largo— y por eso esto puede ser una constante y no una
# cuenta con la fecha.
#
# **Solo aplica a lo que se visita al aire libre.** Un museo a las siete de la
# tarde es cuestion de horarios de apertura, que el catalogo no tiene fiables;
# un mirador a las siete de la tarde es una cuesta a oscuras, y eso no depende
# de ningun horario.
#
# Hizo falta al llenar los dias por reloj: mientras terminaban a las cuatro de
# la tarde no habia forma de llegar a esto. Con dias que llegan a la noche
# aparecieron cinco de 130 paradas al aire libre empezando de noche, entre
# ellas un cerro a las 19:22.
DUSK = time(18, 15)

# Lo que no tiene sentido visitar sin luz.
OUTDOOR_CATEGORIES = {Category.nature.value, Category.viewpoint.value}

LUNCH_WINDOW = (time(11, 30), time(14, 30))
DINNER_WINDOW = (time(18, 0), time(21, 0))

# En orden: el dia que solo da para una comida da para el almuerzo.
MEAL_WINDOWS = (("lunch", LUNCH_WINDOW), ("dinner", DINNER_WINDOW))

# Duracion tipica de una parada mas su traslado. Sirve para estimar hasta que
# hora llega el dia antes de armarlo, que es cuando hay que decidir cuantos
# cupos reservar para comer.
TYPICAL_STOP_MINUTES = 90


def _as_minutes(momento: time) -> int:
    return momento.hour * 60 + momento.minute


# Tope de la reserva de comida, como fraccion del presupuesto del dia.
#
# La reserva de verdad sale de meter la comida y ver que costo: ver
# _meal_km_reserve. Esto solo evita que una zona sin comedores cerca se coma
# el dia entero guardando sitio para un almuerzo que no va a existir; cuando
# la reserva llega a este tope, lo que corresponde es el consejo de llevar
# comida y no un dia de dos paradas.
MEAL_KM_CAP_SHARE = 0.30


def _meal_km_reserve(
    ruta: list[PlaceHit],
    comidas: list[PlaceHit],
    constraints: Constraints,
    travel: TravelProvider,
    esperadas: int,
    numero: int,
) -> float:
    """Kilometros que hay que guardarle a las comidas de este dia.

    **Se calcula metiendo la comida de verdad, no estimandola.** Dos intentos
    peores antes de este, los dos medidos sobre los 26 casos:

    - Una fraccion fija del presupuesto reserva lo mismo en San Salvador, con
      el comedor a doscientos metros, que dentro de un parque nacional, con el
      mas cercano a quince kilometros: sobra en un sitio y falta en el otro, y
      lo que sobra se paga en paradas.
    - La distancia al comedor mas cercano tampoco sirve, y el diagnostico dice
      por que: un dia se quedaba sin almuerzo con el restaurante a 230 metros,
      porque meterlo costaba 3.2 km igual. El costo no lo manda la cercania
      sino la hora —el comedor tiene que ir donde el reloj lo permite, no
      donde queda cerca— y eso solo lo sabe la insercion.

    Asi que se hace la insercion sin mirar el presupuesto y se reserva lo que
    costo. El tope evita que una zona sin comedores deje el dia en dos paradas
    guardando sitio para un almuerzo que no va a existir: llegado ahi, lo que
    corresponde es el consejo de llevar comida.
    """
    if not esperadas or not comidas or not ruta:
        return 0.0

    cercanas = _meal_candidates(ruta, comidas, travel)
    # Sobre la lista tal como esta y no sobre _pinned_order: probado tambien
    # ordenando, y sale peor —298 paradas y 23 dias sin comida, contra 300 y
    # 21—. El orden definitivo cambia otra vez al meter la comida, asi que
    # ordenar aca no acerca la estimacion, solo la mueve.
    secuencia: list[tuple[PlaceHit, str | None]] = [(lugar, None) for lugar in ruta]
    total = 0.0

    for tipo, ventana in list(MEAL_WINDOWS)[:esperadas]:
        tentativa, comida, costo = _best_meal_insertion(
            secuencia,
            cercanas,
            tipo,
            ventana,
            constraints,
            travel,
            enforce_budget=False,
            numero=numero,
        )
        if comida is None:
            continue
        total += costo
        secuencia = tentativa
        cercanas = [c for c in cercanas if c is not comida]

    return min(total, MEAL_KM_CAP_SHARE * constraints.budget_for(numero))


def _meals_expected(constraints: Constraints) -> int:
    """Cuantas comidas va a intentar colocar el dia.

    No es lo mismo que _meals_that_fit, que reparte CUPOS de parada y solo
    tiene sentido con un tope pedido. Esto dice cuantas comidas hay que tener
    en cuenta al reservar tiempo y kilometros, que hace falta siempre.
    """
    if not constraints.include_meals:
        return 0

    esperadas = 0
    if _as_minutes(constraints.latest_end) >= _as_minutes(LUNCH_WINDOW[0]) and _as_minutes(
        constraints.earliest_start
    ) <= _as_minutes(LUNCH_WINDOW[1]):
        esperadas += 1
    if _as_minutes(constraints.latest_end) >= _as_minutes(DINNER_WINDOW[0]):
        esperadas += 1
    return esperadas


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

    # **Se reserva contra el tope que este mandando**, sea el que pidio la
    # persona o la barrera interna. Sin numero pedido el reloj corta antes que
    # el tope casi siempre, asi que la reserva no le quita nada a nadie; pero
    # el caso en que no —un dia de paradas cortas que llega a las doce— se
    # quedaba sin comer, que es el mismo agujero que ya tenia el ancla.
    fin_estimado = (
        _as_minutes(constraints.earliest_start) + constraints.stops_cap * TYPICAL_STOP_MINUTES
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

    # Categorias que el itinerario TIENE que incluir al menos una vez.
    #
    # **Es distinto de preferred_categories, y la diferencia importa.** Preferir
    # es un empujon en el puntaje: sube las probabilidades y no garantiza nada.
    # "quiero ver minimo un museo" no es una preferencia, es un requisito, y
    # cumplirlo a medias es no cumplirlo.
    #
    # La cuenta es del itinerario entero y no de cada dia: quien pide un museo
    # en dos dias quiere un museo, no dos.
    must_include_categories: list[Category] = field(default_factory=list)

    # Modo de cada dia, cuando no todos van igual: "el primer dia en coche, el
    # segundo a pie". La clave es el numero de dia; los que no aparecen usan
    # `mode`.
    #
    # A pie y en carro no son la misma red —un sendero que el peaton cruza no
    # existe para el carro— asi que el modo cambia las distancias, los tiempos
    # y el presupuesto del dia, no solo el icono.
    day_modes: dict[int, str] = field(default_factory=dict)

    def mode_for(self, numero: int) -> str:
        """El modo del dia `numero`."""
        return self.day_modes.get(numero, self.mode)

    def budget_for(self, numero: int) -> float:
        """Los kilometros que puede recorrer el dia `numero`.

        **El presupuesto sigue al modo y no se puede no hacerlo.** Veinticinco
        kilometros son un dia normal en coche y cinco horas caminando: dejar el
        limite del itinerario en un dia a pie no seria una imprecision, seria
        un dia imposible.

        Solo se sustituye cuando el dia va en otro modo que el itinerario: si
        todo el viaje es a pie, el numero que puso el usuario ya es el de a pie
        y manda sobre el valor por defecto.
        """
        modo = self.mode_for(numero)
        if modo == self.mode:
            return self.max_travel_km_per_day
        return BUDGET_BY_MODE.get(modo, self.max_travel_km_per_day)

    include_meals: bool = True

    # Minutos que se pasa uno en cada comida. Ver DEFAULT_MEAL_MINUTES.
    meal_minutes: int = DEFAULT_MEAL_MINUTES

    # Cuanto quiere quedarse en cada tipo de lugar, cuando lo dice: "quiero
    # pasar dos horas en el parque" son {nature: 120}. Lo que no aparece usa
    # DEFAULT_DURATIONS.
    #
    # **Es por categoria y no por lugar, y la diferencia se nota.** Quien pide
    # dos horas de parque las recibe en todos los parques del viaje, porque
    # cuando lo pide todavia no sabe cual le va a tocar: los lugares los elige
    # el motor despues. Pedirlo de un sitio concreto es otra cosa y necesita
    # resolver el nombre y fijar el lugar en el plan.
    category_minutes: dict[Category, int] = field(default_factory=dict)

    # **Cuantos lugares quiere visitar por dia, cuando lo dice.**
    #
    # None no es "cinco por defecto": es "no lo dijo", y las dos cosas llevan a
    # itinerarios distintos. Con un cinco puesto de oficio, un dia de diez de
    # la manana a once de la noche terminaba a las cuatro de la tarde con
    # siete horas sin usar, porque el largo del dia lo decidia un contador y
    # no el horario que la persona habia pedido. Sin numero, mandan el reloj y
    # los kilometros, que son los limites que si vienen de ella.
    max_stops_per_day: int | None = None
    min_quality: float = 0.0

    # De donde sale el dia: la casa, el hotel, la pizzeria donde se almuerza.
    #
    # **No cuenta contra max_stops_per_day.** Quien pide "tres paradas" habla
    # de lugares que va a visitar, no del sitio de donde sale; descontarle una
    # parada por decir de donde parte le daria menos de lo que pidio.
    start_place: PlaceHit | None = None

    # Si el dia vuelve al punto de partida. Cambia tambien a que dias aplica el
    # ancla: quien vuelve cada noche esta diciendo que ese es su base y el ancla
    # vale para todos los dias, y quien solo parte de un sitio lo hace una vez,
    # el primer dia.
    return_to_start: bool = False

    @property
    def stops_cap(self) -> int:
        """El techo de paradas que el motor hace cumplir.

        El numero que pidio la persona, o la barrera si no pidio ninguno. Todo
        el motor cuenta contra esto; validate() en cambio solo reporta cuando
        habia un numero pedido, porque una barrera interna no es algo que
        nadie haya incumplido.
        """
        return self.max_stops_per_day or MAX_STOPS_HARD_CAP

    def anchors_day(self, numero: int) -> bool:
        """Si el dia `numero` arranca en el punto de partida."""
        if self.start_place is None:
            return False
        return self.return_to_start or numero == 1


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


def _travel_or_estimate(
    travel: TravelProvider | Mapping[str, TravelProvider] | None, mode: str
) -> TravelProvider:
    """El proveedor dado, o la estimacion geodesica si no hay ninguno.

    Que el respaldo sea el valor por defecto y no una rama de emergencia es
    deliberado: el camino degradado se ejercita en cada test del motor, asi que
    no puede pudrirse sin que alguien se entere.

    Acepta tambien un diccionario de modo a proveedor, que es lo que hace
    posible un itinerario con dias en coche y dias a pie: cada red tiene su
    matriz medida y el dia usa la suya. Un proveedor suelto se usa tal cual, y
    ahi la responsabilidad de que corresponda al modo es de quien lo paso.
    """
    if isinstance(travel, Mapping):
        return travel.get(mode) or EstimatedTravel(mode)
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


def _pinned_order(
    ancla: PlaceHit | None, paradas: list[PlaceHit], travel: TravelProvider | None = None
) -> list[PlaceHit]:
    """Ordena dejando el ancla primera, si hay ancla.

    El vecino mas cercano ya arranca por `paradas[0]` y 2-opt invierte tramos
    desde el indice 1, asi que la primera parada se queda quieta sola: basta
    con ponerla ahi. Lo que no se puede es dejar que el ancla entre al monton y
    que el orden la mueva al medio, porque entonces el dia empieza en otro
    lado.
    """
    if ancla is None:
        return order_by_proximity(paradas, travel)

    resto = [p for p in paradas if p is not ancla]
    return order_by_proximity([ancla, *resto], travel)


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


# Cuanto cuesta repetir categoria dentro de un dia, expresado en kilometros.
#
# El llenado del dia ordenaba solo por distancia a la semilla, y como los
# lugares de una misma categoria estan agrupados en el terreno —los cerros
# comparten cresta, las iglesias comparten centro— un dia sembrado con un cerro
# se llenaba de cerros. Medido sobre los 26 casos de evaluacion: el 75% de los
# dias tenian una categoria en la mitad o mas de sus paradas y el 45% tenian
# tres o mas seguidas iguales.
#
# La penalizacion va en kilometros a proposito, para que sea comparable con lo
# unico que el llenado media hasta ahora: la segunda parada de una categoria
# que ya esta en el dia tiene que estar este numero de kilometros mas cerca que
# una de categoria nueva para ganarle el sitio.
#
# **No es un filtro, es un desempate.** Donde el catalogo solo tiene cerros
# —Perquin, Costa del Sol— el dia sigue saliendo de cerros, porque no hay otra
# cosa. Filtrar dejaria esos dias a medio llenar.
#
# El valor sale de barrer de 0 a 40 sobre los 26 casos:
#
#     km   cumple   km/dia  cats/dia  dom>=50%  racha3+
#      0   25/26     10.4      2.63       75%      47%
#      6   25/26     13.1      3.23       53%      28%
#     12   25/26     14.3      3.28       44%      21%
#     20   25/26     15.2      3.30       39%      19%
#     40   25/26     15.1      3.32       39%      16%
#
# A partir de 20 la variedad se satura —lo que queda es catalogo que de verdad
# solo tiene una clase de lugar— y se empiezan a perder paradas: 281 contra las
# 284 de 12, porque algun dia ya no encuentra con que llenarse. En 12 se
# recoge casi toda la mejora disponible, ningun dia se pasa de su presupuesto
# (el peor queda en el 99%, igual que antes) y el atractivo medio de las
# paradas no baja: 0.699 contra 0.694.
#
# **Vuelto a barrer al llenar los dias por horario, y el 12 ya no valia.** Un
# dia de cinco paradas casi no tiene sitio para una racha de tres; uno de
# ocho, si. Con la misma penalizacion de antes las rachas subieron del 21% al
# 38% de los dias, no porque el criterio empeorara sino porque hay mas dia
# donde repetirse. El barrido nuevo, con la reserva de comida ya puesta:
#
#     km   cumple   paradas  lleva comida  cats/dia  racha3+
#     12   25/26      317        18/61       3.24      38%
#     18   25/26      309        17/61       3.24      33%
#     24   25/26      306        16/61       3.24      31%
#     30   25/26      305        16/61       3.22      31%
#     40   25/26      305        16/61       3.22      31%
#
# En 24 esta la rodilla: se recupera casi toda la regresion de rachas por once
# paradas de 317, y de ahi en adelante no compra nada. Las categorias por dia
# no se mueven en todo el barrido, que es la senal de que lo que cambio fue el
# largo del dia y no el criterio.
REPEAT_PENALTY_KM = 24.0


# Descuento para una categoria que el usuario exigio y todavia no aparece.
#
# Va en kilometros como la penalizacion por repetir, para que las tres cosas que
# ordenan el llenado —cercania, variedad y requisitos— se comparen en la misma
# unidad. El numero es grande a proposito: un requisito gana a la cercania salvo
# que el candidato este absurdamente lejos, y si esta absurdamente lejos el
# presupuesto de traslado lo rechaza igual.
REQUIRED_BONUS_KM = 60.0


def _visit_count(lugares: Iterable[PlaceHit], numero: int, constraints: Constraints) -> int:
    """Cuantas de esas paradas cuentan contra max_stops_per_day.

    **El punto de partida no cuenta, ni cuando aparece dos veces por el
    regreso.** Es la misma regla que aplica build_days al repartir los cupos,
    y estaba escrita tres veces con tres criterios distintos: build_days le
    daba un cupo aparte al ancla, validate() la descontaba, y la insercion de
    comidas la contaba como una parada mas. Esa tercera copia se comia el cupo
    reservado para el almuerzo en todos los dias con hotel.
    """
    ancla = constraints.start_place if constraints.anchors_day(numero) else None
    if ancla is None:
        return sum(1 for _ in lugares)
    return sum(1 for lugar in lugares if lugar.id != ancla.id)


def _fill_cost(
    dia: list[PlaceHit],
    candidato: PlaceHit,
    semilla: PlaceHit,
    medidor: TravelProvider,
    faltantes: frozenset[str] = frozenset(),
) -> float:
    """Lo que cuesta agregar un candidato: distancia, repeticion y requisitos."""
    repetidas = sum(1 for parada in dia if parada.category == candidato.category)
    coste = medidor.between(semilla, candidato)[0] + repetidas * REPEAT_PENALTY_KM
    if candidato.category in faltantes:
        coste -= REQUIRED_BONUS_KM
    return coste


def _closing_km(
    ruta: list[PlaceHit],
    numero: int,
    constraints: Constraints,
    travel: TravelProvider,
) -> float:
    """Kilometros de volver al punto de partida, si el dia vuelve.

    Se suma aparte en vez de meter el ancla al final de la lista. Una lista con
    el mismo lugar dos veces rompe todo lo que la recorre: `remove` saca la
    primera aparicion, el orden por cercania lo trata como dos paradas, y el
    recorte del presupuesto puede quitar el regreso y no darse cuenta.
    """
    if not constraints.return_to_start or not constraints.anchors_day(numero):
        return 0.0
    if not ruta or constraints.start_place is None:
        return 0.0
    return travel.between(ruta[-1], constraints.start_place)[0]


def _fits_travel_budget(
    ruta: list[PlaceHit],
    nueva: PlaceHit,
    constraints: Constraints,
    travel: TravelProvider | None = None,
    numero: int = 1,
    ancla: PlaceHit | None = None,
    reserva_km: float = 0.0,
) -> bool:
    """Comprueba si agregar una parada mantiene el dia dentro del limite.

    Cuenta tambien el regreso al punto de partida cuando el dia vuelve: sin
    eso, el dia se llena hasta el tope y el viaje de vuelta lo saca del
    presupuesto despues, cuando ya no hay nada que recortar. La reserva de las
    comidas es lo mismo un paso mas alla: el desvio al restaurante tampoco
    aparece de la nada.
    """
    medidor = _travel_or_estimate(travel, constraints.mode_for(numero))
    tentativa = _pinned_order(ancla, [*ruta, nueva], medidor)
    total = _route_km(tentativa, medidor) + _closing_km(
        tentativa, numero, constraints, medidor
    )
    return total <= constraints.budget_for(numero) - reserva_km


def _fits_the_clock(
    ruta: list[PlaceHit],
    nueva: PlaceHit,
    constraints: Constraints,
    travel: TravelProvider | None = None,
    numero: int = 1,
    ancla: PlaceHit | None = None,
    reservados: int = 0,
) -> bool:
    """Comprueba si agregar una parada deja el dia dentro de su horario.

    Cuenta lo mismo que contara el dia terminado: el recorrido con la parada
    nueva, el regreso al punto de partida si lo hay, y el rato de las comidas
    que todavia no estan puestas pero que se van a poner. Sin esa ultima
    parte, un dia se llenaba hasta el limite del reloj y despues el almuerzo
    lo pasaba de largo, que es el mismo error que _fits_travel_budget ya
    corregia para el regreso.

    No mira la espera de las franjas de comida a proposito: esperar a que
    abran adelanta el reloj, y contarlo aca haria parecer imposibles dias que
    se resuelven solos cuando la comida cae en su hora.
    """
    medidor = _travel_or_estimate(travel, constraints.mode_for(numero))
    tentativa = _pinned_order(ancla, [*ruta, nueva], medidor)
    secuencia = [(lugar, None) for lugar in tentativa]

    # Nada al aire libre despues de que oscurece. Se mira sobre el orden
    # tentativo, que es el mismo que va a salir: _pinned_order es determinista.
    limite_luz = _as_minutes(DUSK)
    for lugar, hora in zip(
        tentativa, _arrival_times(secuencia, constraints, medidor), strict=False
    ):
        if lugar.category in OUTDOOR_CATEGORIES and _as_minutes(hora) >= limite_luz:
            return False

    minutos = _sequence_minutes(secuencia, constraints, medidor)
    if constraints.return_to_start and constraints.anchors_day(numero) and ancla is not None:
        if tentativa[-1].id != ancla.id:
            minutos += medidor.between(tentativa[-1], ancla)[1]
    minutos += reservados * constraints.meal_minutes

    return minutos <= _as_minutes(constraints.latest_end)


def build_days(
    candidatos: list[PlaceHit],
    constraints: Constraints,
    travel: TravelProvider | None = None,
    meal_options: int = 2,
    comidas: list[PlaceHit] | None = None,
) -> list[list[PlaceHit]]:
    """Reparte los candidatos en dias agrupados geograficamente.

    Cada dia arranca por el mejor lugar sin usar y se completa con los mas
    cercanos que quepan en el presupuesto de traslado. Asi los dias salen
    compactos sin necesidad de un algoritmo de agrupamiento aparte: la
    cercania es el criterio de llenado.
    """
    # El medidor se crea por dia dentro del bucle: cada dia puede ir en su
    # propio modo y las distancias cambian con la red.

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

    # Los requisitos se llevan como cuenta del itinerario entero: quien pide un
    # museo en dos dias quiere un museo, no dos.
    requeridas = {c.value for c in constraints.must_include_categories}
    cubiertas: set[str] = set()
    if constraints.start_place is not None:
        cubiertas.add(constraints.start_place.category)

    for numero in range(1, constraints.days + 1):
        medidor = _travel_or_estimate(travel, constraints.mode_for(numero))
        anclado = constraints.anchors_day(numero)
        ancla = constraints.start_place if anclado else None

        if not disponibles and ancla is None:
            break

        if ancla is not None:
            # El ancla es la semilla: el dia se llena alrededor de donde
            # empieza, que es lo que se pidio.
            semilla = ancla
            dia = [ancla]
            # Puede estar en el catalogo de destinos: no se elige dos veces.
            disponibles = [h for h in disponibles if h.id != ancla.id]
        else:
            # La semilla cubre un requisito pendiente si hay con que: es la
            # forma mas barata de garantizarlo, porque el resto del dia se
            # llena alrededor de ella.
            faltantes = requeridas - cubiertas
            pendiente = next((h for h in disponibles if h.category in faltantes), None)
            semilla = pendiente if pendiente is not None else disponibles[0]
            disponibles.remove(semilla)
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
        # Si el dia arranca en un comedor, ese comedor ya es la comida del dia
        # y su cupo reservado sobra. Sin esto se guarda sitio para un almuerzo
        # que nunca se coloca, y el dia sale con un destino menos del pedido.
        if ancla is not None and ancla.category == Category.food.value:
            reservados = max(0, reservados - 1)
        # El ancla no gasta cupo: quien pide tres paradas habla de lugares
        # que va a visitar, no del sitio de donde sale. Descontarle una parada
        # por decir de donde parte le daria menos de lo que pidio.
        cupo = max(constraints.stops_cap - reservados, 1) + (1 if ancla is not None else 0)

        # Lo que se le guarda a las comidas en tiempo y en kilometros. Es
        # independiente de los cupos: aunque no se reserve ninguna parada, el
        # rato de comer y el desvio al restaurante ocurren igual.
        esperadas = min(_meals_expected(constraints), max(0, meal_options))
        if ancla is not None and ancla.category == Category.food.value:
            esperadas = max(0, esperadas - 1)

        while len(dia) < cupo:
            # Se reordena en cada vuelta porque el coste depende de lo que
            # ya haya en el dia, y eso cambia con cada parada agregada.
            # Se recalcula en cada vuelta: lo que falta cambia con cada
            # parada que entra.
            faltantes = frozenset(requeridas - cubiertas - {p.category for p in dia})
            # Se recalcula en cada vuelta: el comedor mas cercano depende de
            # donde esta el dia, y el dia se mueve con cada parada.
            reserva_km = _meal_km_reserve(
                dia, comidas or [], constraints, medidor, esperadas, numero
            )
            cercanos = sorted(
                (h for h in disponibles if h.category != Category.food.value),
                key=lambda h: _fill_cost(dia, h, semilla, medidor, faltantes),
            )
            agregado = False
            for candidato in cercanos[:15]:
                if not _fits_travel_budget(
                    dia, candidato, constraints, medidor, numero, ancla, reserva_km
                ):
                    continue
                # **El horario es un limite de llenado y no solo de recorte.**
                # Antes solo se comprobaba despues, en _trim_to_budget, que
                # quita paradas: o sea que el reloj podia acortar el dia pero
                # nunca alargarlo. Mirandolo aca, el dia crece mientras quepa
                # y para cuando ya no.
                if not _fits_the_clock(
                    dia, candidato, constraints, medidor, numero, ancla, esperadas
                ):
                    continue
                dia.append(candidato)
                disponibles.remove(candidato)
                agregado = True
                break
            if not agregado:
                break

        # **Un dia que solo tiene el punto de partida no es un dia.** Al
        # anclar los dias hubo que aflojar la guarda de "sin candidatos, no
        # hay dia", y eso dejaba pasar dias con el hotel y nada mas: parecian
        # un error y encima escondian que el catalogo no daba para tantos dias.
        # Cortando aca, el itinerario sale con menos dias y validate() reporta
        # el faltante, que es lo que se pidio y no se pudo cumplir.
        if ancla is not None and len(dia) == 1:
            break

        cubiertas |= {p.category for p in dia}
        dias.append(_pinned_order(ancla, dia, medidor))

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


def _stop_minutes(lugar: PlaceHit, comida: str | None, constraints: Constraints) -> int:
    """Cuanto dura la parada.

    Cuatro escalones, del mas especifico al mas general: la etiqueta de
    comida, lo que el usuario pidio para esa categoria, la subcategoria del
    lugar, y la tabla por categoria.

    La etiqueta va primero y no la categoria del lugar: lo que hace larga a
    una parada es que uno se siente a comer, y eso lo dice la etiqueta que
    puso _insert_meals. Por categoria, el restaurante al que se vuelve a
    cerrar el dia contaria como una segunda cena.

    Lo que pidio el usuario va por encima de la subcategoria a proposito:
    quien dice "dos horas en el parque" esta hablando de todos los parques del
    dia, y afinar por debajo de eso seria discutirle.
    """
    if comida is not None:
        return constraints.meal_minutes
    categoria = Category(lugar.category)
    if categoria in constraints.category_minutes:
        return constraints.category_minutes[categoria]
    if lugar.subcategory in SUBCATEGORY_DURATIONS:
        return SUBCATEGORY_DURATIONS[lugar.subcategory]
    return DEFAULT_DURATIONS.get(categoria, 60)


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
        momento = _add_minutes(momento, _stop_minutes(lugar, comida, constraints))

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
    numero: int = 1,
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
    #
    # Se cuenta con la misma regla que el resto: el punto de partida no gasta
    # cupo. Contando la secuencia entera, el hotel se comia el sitio que
    # build_days habia reservado para el almuerzo, y el dia salia sin comida
    # aunque el restaurante estuviera al lado y dentro del presupuesto.
    if (
        _visit_count((lugar for lugar, _ in secuencia), numero, constraints)
        >= constraints.stops_cap
    ):
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
            if enforce_budget and total > constraints.budget_for(numero):
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
    numero: int = 1,
) -> list[tuple[PlaceHit, str | None]]:
    """Intercala almuerzo y cena entre las paradas del dia.

    Cada comida va donde menos kilometros agregue, entre las posiciones cuya
    hora cae dentro de la franja. Antes se elegia por cercania a la parada
    anterior, que ignoraba el regreso y partia los dias en dos.
    """
    secuencia: list[tuple[PlaceHit, str | None]] = [(p, None) for p in ruta]

    if not constraints.include_meals or not ruta:
        return secuencia

    # Si el dia arranca en un comedor, ese comedor ES la comida del dia. Quien
    # dice "parto de la pupuseria y almuerzo ahi" no quiere que ademas se le
    # meta un restaurante a media tarde.
    ancla = constraints.start_place
    if ancla is not None and ruta[0] is ancla and ancla.category == Category.food.value:
        etiqueta = "lunch" if constraints.earliest_start < DINNER_WINDOW[0] else "dinner"
        secuencia[0] = (ancla, etiqueta)
        return secuencia

    if not comidas:
        return secuencia

    medidor = _travel_or_estimate(travel, constraints.mode_for(numero))
    disponibles = list(comidas)

    secuencia, almuerzo, _ = _best_meal_insertion(
        secuencia, disponibles, "lunch", LUNCH_WINDOW, constraints, medidor, numero=numero
    )
    if almuerzo is not None:
        disponibles.remove(almuerzo)

    if disponibles:
        secuencia, _, _ = _best_meal_insertion(
            secuencia,
            disponibles,
            "dinner",
            DINNER_WINDOW,
            constraints,
            medidor,
            numero=numero,
        )

    return secuencia


def schedule_day(
    numero: int,
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider | None = None,
) -> Day:
    """Asigna horas de llegada y salida respetando la hora minima de inicio.

    Si el dia vuelve al punto de partida, el regreso se agrega aca y no antes.
    Es una parada visible a proposito: quien pregunta "y a que hora llego a
    casa" esta preguntando por el dato que la ultima linea de la lista da, y un
    recorrido dibujado que no cierra parece un recorrido a medias.

    Se agrega al final del todo, despues de que el orden y el recorte ya
    hicieron su trabajo: mientras el ancla esta en la lista dos veces, todo lo
    que la recorre se confunde.
    """
    medidor = _travel_or_estimate(travel, constraints.mode_for(numero))
    dia = Day(number=numero)
    momento = constraints.earliest_start

    if (
        constraints.return_to_start
        and constraints.anchors_day(numero)
        and constraints.start_place is not None
        and secuencia
        # **Se compara por identificador y no por identidad.** Al rehacer un
        # dia, los otros se reconstruyen desde el catalogo, asi que su hotel
        # final es otro objeto con el mismo id: con `is not`, el regreso se
        # agregaba encima del que ya estaba y el dia terminaba llegando dos
        # veces al hotel. Solo se veia con punto de partida y revision, que es
        # justo lo que antes se perdia por el camino.
        and secuencia[-1][0].id != constraints.start_place.id
    ):
        secuencia = [*secuencia, (constraints.start_place, None)]

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

        duracion = _stop_minutes(lugar, comida, constraints)
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


ETIQUETA_CATEGORIA = {
    Category.food: "comida",
    Category.nature: "naturaleza",
    Category.culture: "cultura",
    Category.viewpoint: "mirador",
    Category.attraction: "atraccion",
    Category.lodging: "alojamiento",
}


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

        if dia.travel_km > constraints.budget_for(dia.number):
            violaciones.append(
                Violation(
                    "max_travel_km_per_day",
                    dia.number,
                    f"{dia.travel_km} km recorridos, el limite era "
                    f"{constraints.budget_for(dia.number)}",
                )
            )

        # El punto de partida no cuenta contra el limite, ni cuando aparece dos
        # veces por el regreso: el motor le da un cupo aparte al armar el dia,
        # asi que contarlo aca lo haria reportar como violacion un limite que
        # el mismo decidio no aplicarle.
        visitas = _visit_count((parada.place for parada in dia.stops), dia.number, constraints)

        # Solo se reporta cuando la persona pidio un numero. El tope interno
        # que usa el motor cuando nadie pidio nada es una barrera suya, y
        # reportarla como restriccion incumplida seria acusar al usuario de
        # romper una regla que no puso.
        if (
            constraints.max_stops_per_day is not None
            and visitas > constraints.max_stops_per_day
        ):
            violaciones.append(
                Violation(
                    "max_stops_per_day",
                    dia.number,
                    f"{visitas} paradas, el limite era {constraints.max_stops_per_day}",
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

    # **El requisito es del itinerario, no de cada dia.** Se comprueba aca
    # aunque el motor ya lo prioriza al armar: priorizar no es garantizar, y si
    # la zona no tiene ni un museo hay que decirlo en vez de dejar que el
    # usuario lo descubra leyendo la lista.
    presentes = {parada.place.category for dia in itinerario.days for parada in dia.stops}
    for categoria in constraints.must_include_categories:
        if categoria.value not in presentes:
            violaciones.append(
                Violation(
                    "must_include_categories",
                    None,
                    f"pediste al menos una parada de "
                    f"{ETIQUETA_CATEGORIA.get(categoria, categoria.value)} y no "
                    "hay ninguna en la zona que entre en el dia",
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
    consejos: list[Advice] = []

    if not constraints.include_meals:
        return consejos

    for dia in itinerario.days:
        medidor = _travel_or_estimate(travel, constraints.mode_for(dia.number))
        if not dia.stops or not dia.start or not dia.end:
            continue

        cruza_almuerzo = dia.start <= LUNCH_WINDOW[1] and dia.end >= LUNCH_WINDOW[0]
        if cruza_almuerzo and not any(p.meal == "lunch" for p in dia.stops):
            consejos.append(
                _meal_advice(dia, constraints, comidas, medidor, "lunch", LUNCH_WINDOW)
            )

        # La cena tambien: el comprobador de la evaluacion la reclamaba y
        # advise() no decia nada, asi que un dia que llegaba a la noche sin
        # cenar se quedaba sin explicacion.
        llega_a_la_cena = dia.end >= DINNER_WINDOW[0]
        if llega_a_la_cena and not any(p.meal == "dinner" for p in dia.stops):
            consejos.append(
                _meal_advice(dia, constraints, comidas, medidor, "dinner", DINNER_WINDOW)
            )

    return consejos


MEAL_LABELS = {"lunch": ("almuerzo", "bring_lunch"), "dinner": ("cena", "bring_dinner")}


def _meal_advice(
    dia: Day,
    constraints: Constraints,
    comidas: list[PlaceHit],
    travel: TravelProvider,
    tipo: str,
    ventana: tuple[time, time],
) -> Advice:
    """Por que no hubo esta comida, con el numero que lo explica."""
    nombre, kind = MEAL_LABELS[tipo]

    if not comidas:
        return Advice(
            kind,
            dia.number,
            f"No hay ningún lugar para comer registrado en esta zona: llevá {nombre}",
        )

    secuencia = [(p.place, p.meal) for p in dia.stops]

    # **Sin cupo no hay nada que buscar, y decirlo importa.** La insercion
    # devuelve lo mismo —None— cuando no queda sitio y cuando ningun comedor
    # cae en la franja, y el aviso daba siempre la segunda explicacion. En un
    # dia lleno eso era falso: el restaurante existia, estaba en hora y dentro
    # del presupuesto, y lo que faltaba era una parada. Ademas la salida es
    # distinta: aca se sube el tope de paradas, alla se lleva comida.
    visitas = _visit_count((p.place for p in dia.stops), dia.number, constraints)
    if visitas >= constraints.stops_cap:
        pedido = constraints.max_stops_per_day
        salida = (
            f"pediste {pedido}. Subí el límite de paradas o llevá {nombre}"
            if pedido is not None
            else f"es lo más que arma en un día. Llevá {nombre}"
        )
        return Advice(
            kind,
            dia.number,
            f"No queda parada libre para {nombre}: el día ya tiene {visitas} y {salida}",
        )

    candidatos = _meal_candidates([p.place for p in dia.stops], comidas, travel)

    # Se busca la mejor insercion SIN respetar el presupuesto, justamente para
    # poder decir cuanto se habria pasado.
    _, comida, costo = _best_meal_insertion(
        secuencia,
        candidatos,
        tipo,
        ventana,
        constraints,
        travel,
        enforce_budget=False,
        numero=dia.number,
    )

    if comida is None:
        return Advice(
            kind,
            dia.number,
            f"Ningún lugar para comer cae dentro del horario de {nombre} de este "
            f"día: llevá {nombre}",
        )

    total = dia.travel_km + costo
    return Advice(
        kind,
        dia.number,
        f"El lugar para comer más conveniente es {comida.name}, que agrega "
        f"{costo:.1f} km y dejaría el día en {total:.1f} km, sobre tu límite de "
        f"{constraints.budget_for(dia.number):.0f}. Llevá {nombre}, o subí el "
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


def _sequence_minutes(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
) -> int:
    """En que minuto del dia termina la secuencia, contado desde medianoche.

    **En minutos y no en `time` porque `time` da la vuelta al reloj.** Un dia
    que se pasa de las doce de la noche volvia a empezar en cero y parecia
    terminar de madrugada, o sea antes que uno corto: justo donde se comprueba
    latest_end, la comprobacion decia que si. Mientras los dias eran de cinco
    paradas no se llegaba nunca; llenandolos por horario, si.
    """
    minutos = _as_minutes(constraints.earliest_start)
    for indice, (lugar, comida) in enumerate(secuencia):
        if indice:
            minutos += travel.between(secuencia[indice - 1][0], lugar)[1]
        if comida == "lunch":
            minutos = max(minutos, _as_minutes(LUNCH_WINDOW[0]))
        elif comida == "dinner":
            minutos = max(minutos, _as_minutes(DINNER_WINDOW[0]))
        minutos += _stop_minutes(lugar, comida, constraints)
    return minutos


def _sequence_end(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
) -> time | None:
    """Hora a la que termina la ultima parada de la secuencia.

    La etiqueta de la ultima parada cuenta: un dia que termina cenando dura lo
    que dura la cena.
    """
    if not secuencia:
        return None
    total = _sequence_minutes(secuencia, constraints, travel)
    # Un dia que se pasa de la medianoche no termina temprano: se satura, para
    # que quien lo compare con una hora limite lo vea largo y no corto.
    if total >= 24 * 60:
        return time(23, 59)
    return time(total // 60, total % 60)


def _fits_the_day(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
    numero: int = 1,
) -> bool:
    """Si el dia entra en el presupuesto de kilometros y en su horario.

    **latest_end era un aviso y no un limite.** validate() lo reportaba y
    nadie lo hacia cumplir: un dia con ventana de 10:00 a 15:00 salia
    terminando a las 16:13. Se recorta igual que por kilometros.
    """
    km = _day_travel_km(secuencia, constraints.mode_for(numero), travel) + _closing_km(
        [lugar for lugar, _ in secuencia], numero, constraints, travel
    )
    if km > constraints.budget_for(numero):
        return False

    if not secuencia:
        return True
    return _sequence_minutes(secuencia, constraints, travel) <= _as_minutes(
        constraints.latest_end
    )


def _outdoor_after_dusk(
    secuencia: list[tuple[PlaceHit, str | None]],
    constraints: Constraints,
    travel: TravelProvider,
) -> PlaceHit | None:
    """La primera parada al aire libre que caeria ya de noche, si hay alguna.

    Se comprueba aca ademas de al llenar el dia porque entre una cosa y la
    otra el orden cambia: _pinned_order optimiza el recorrido y la comida se
    intercala, y las dos cosas mueven las horas. Mirandolo solo al llenar
    quedaban cuatro de cinco.
    """
    limite = _as_minutes(DUSK)
    for (lugar, _), hora in zip(
        secuencia, _arrival_times(secuencia, constraints, travel), strict=False
    ):
        if lugar.category in OUTDOOR_CATEGORIES and _as_minutes(hora) >= limite:
            return lugar
    return None


def _trim_to_budget(
    grupo: list[PlaceHit],
    comidas: list[PlaceHit],
    constraints: Constraints,
    travel: TravelProvider | None = None,
    numero: int = 1,
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
    medidor = _travel_or_estimate(travel, constraints.mode_for(numero))
    restantes = list(grupo)
    # El punto de partida no se recorta: es un dato del usuario y no una
    # eleccion del motor. Si el dia no entra, se quitan las paradas elegidas.
    ancla = constraints.start_place if constraints.anchors_day(numero) else None

    while restantes:
        secuencia = _insert_meals(
            _pinned_order(ancla, restantes, medidor),
            comidas,
            constraints,
            medidor,
            numero,
        )
        # **La parada de noche se quita por su nombre y no por su costo.** El
        # recorte de kilometros elige la que mas traslado suma, que casi nunca
        # es la que cae tarde: buscando por ahi, el dia perdia otras paradas
        # antes de arreglar la unica que estaba mal.
        nocturna = _outdoor_after_dusk(secuencia, constraints, medidor)
        if nocturna is not None and nocturna is not ancla:
            restantes.remove(nocturna)
            continue

        if _fits_the_day(secuencia, constraints, medidor, numero):
            return secuencia

        quitables = [p for p in restantes if p is not ancla]
        if not quitables:
            break

        # Costo de cada destino: lo que se ahorraria quitandolo.
        base = _route_km(_pinned_order(ancla, restantes, medidor), medidor)
        peor = max(
            quitables,
            key=lambda p: (
                base
                - _route_km(
                    _pinned_order(ancla, [x for x in restantes if x is not p], medidor),
                    medidor,
                )
            ),
        )
        restantes.remove(peor)

    return _insert_meals(
        _pinned_order(ancla, restantes, medidor), comidas, constraints, medidor, numero
    )


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
    # **Se pasa `travel` hacia abajo y no un medidor ya resuelto.** Resolverlo
    # aca anulaba el modo por dia: cada funcion recibia un proveedor concreto y
    # `_travel_or_estimate` lo devolvia tal cual, asi que el dia a pie se medía
    # con la red del coche sin que nada lo delatara.
    if grupos is None:
        grupos = build_days(
            destinos, constraints, travel, meal_options=len(comidas), comidas=comidas
        )

    dias: list[Day] = []
    comidas_restantes = list(comidas)
    for numero, grupo in enumerate(grupos, start=1):
        if not grupo:
            continue
        medidor = _travel_or_estimate(travel, constraints.mode_for(numero))
        # Cada dia toma las comidas mas cercanas a su primera parada, para no
        # repetir restaurante entre dias.
        cercanas = _meal_candidates(grupo, comidas_restantes, medidor)
        secuencia = _trim_to_budget(grupo, cercanas, constraints, travel, numero)
        for lugar, comida in secuencia:
            if comida and lugar in comidas_restantes:
                comidas_restantes.remove(lugar)
        dias.append(schedule_day(numero, secuencia, constraints, travel))

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

    Trae tambien el trazo por carretera de cada tramo, indexado por el par de
    lugares que une. Los tramos que no lo tienen —sin llave, sin cupo, o dos
    paradas que ORS no puede enrutar— simplemente no aparecen en el diccionario,
    y quien dibuja tira la linea recta. El degradado es por tramo y no por
    itinerario: un solo par sin carretera no tiene por que borrar el trazo real
    de los otros seis.
    """

    itinerary: Itinerary
    stats: object | None = None
    geometry: dict = field(default_factory=dict)
    geometry_stats: object | None = None
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
    from app.services.routing import (
        client_from_settings,
        load_route_geometry,
        load_travel_matrix,
    )

    comidas, destinos = select_candidates(db, constraints)
    yield CandidatesReady(destinations=destinos, meals=comidas)

    estimado = EstimatedTravel(constraints.mode)
    grupos = build_days(
        destinos, constraints, estimado, meal_options=len(comidas), comidas=comidas
    )
    borrador = assemble(comidas, destinos, constraints, estimado, grupos)
    yield DraftReady(itinerary=borrador)

    cliente = client if client is not None else client_from_settings()

    # **Una matriz por modo distinto, no una por itinerario.** A pie y en carro
    # son redes distintas —un sendero que el peaton cruza no existe para el
    # carro— asi que medir un dia a pie con la matriz del coche seria inventar.
    #
    # Cuesta una peticion mas cuando el viaje mezcla modos, y solo entonces:
    # un itinerario entero en coche sigue costando una. La alternativa era
    # estimar los dias a pie, y la estimacion esta calibrada contra rutas en
    # coche —DETOUR_FACTOR sale de 812 pares de ORS en carro— asi que para
    # caminar esta doblemente mal.
    lugares_por_modo: dict[str, list[PlaceHit]] = {}
    for dia in borrador.days:
        modo = constraints.mode_for(dia.number)
        lugares_por_modo.setdefault(modo, []).extend(parada.place for parada in dia.stops)

    matrices = {
        modo: load_travel_matrix(lugares, modo, db=db, client=cliente)
        for modo, lugares in lugares_por_modo.items()
    }
    # El resumen que ve el usuario es del itinerario entero: se suma lo de cada
    # modo en vez de reportar solo el de uno.
    matriz = _merge_matrix_stats(matrices, constraints.mode)

    # El reparto de dias se rehace con distancias reales: dos lugares que la
    # linea recta pone en el mismo dia pueden estar separados por un cerro.
    final = assemble(comidas, destinos, constraints, matrices)

    # El trazo se pide DESPUES del reparto final y no antes: con distancias
    # reales el orden del dia cambia, y una geometria pedida sobre el orden del
    # borrador dibujaria un recorrido que el itinerario ya no hace.
    geometria, geo_stats = load_route_geometry(
        [
            (
                constraints.mode_for(dia.number),
                [parada.place for parada in dia.stops],
            )
            for dia in final.days
        ],
        db=db,
        client=cliente,
    )

    yield PlanReady(
        itinerary=final,
        stats=matriz,
        geometry=geometria,
        geometry_stats=geo_stats,
    )


def _merge_matrix_stats(matrices: dict, modo_principal: str):
    """Junta las estadisticas de varias matrices en un solo resumen.

    El usuario pregunta "de donde salieron estas distancias" por el itinerario
    entero, no por modo. Con una sola matriz esto devuelve sus propias
    estadisticas sin tocarlas.
    """
    if len(matrices) == 1:
        return next(iter(matrices.values())).stats

    principal = matrices.get(modo_principal) or next(iter(matrices.values()))
    total = type(principal.stats)()
    for matriz in matrices.values():
        total.cached += matriz.stats.cached
        total.fetched += matriz.stats.fetched
        total.estimated += matriz.stats.estimated
        total.requests += matriz.stats.requests
        # El motivo del degradado se toma del primero que lo tenga: son la
        # misma llave y el mismo cupo, asi que fallan por lo mismo.
        if total.reason is None:
            total.reason = matriz.stats.reason
    return total


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
    restricciones_dia = day_constraints or constraints

    # **El dia que se rehace lleva su propio modo, no el del itinerario.**
    # Se armaba con un medidor resuelto una sola vez desde constraints.mode y
    # se repartia como "dia 1" de un itinerario de un dia, asi que el dia 2 a
    # pie de "el primero en coche y el segundo caminando" se reconstruia con
    # la red del coche y con sus veinticinco kilometros. Es el mismo error que
    # ya se habia corregido en assemble(), que aqui habia sobrevivido.
    modo = restricciones_dia.mode_for(target)
    medidor = _travel_or_estimate(travel, modo)

    # build_days reparte dias numerados desde 1, asi que el dia objetivo tiene
    # que viajar ahi como un itinerario de un solo dia que ya trae puestos el
    # modo y el presupuesto que le tocan.
    del_objetivo = replace(
        restricciones_dia,
        days=1,
        mode=modo,
        max_travel_km_per_day=restricciones_dia.budget_for(target),
        day_modes={},
    )

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
        del_objetivo,
        travel,
        meal_options=len(comidas_libres),
        comidas=comidas_libres,
    )
    nuevo = grupos[0] if grupos else []

    dias: list[Day] = []
    for dia in sorted(state, key=lambda d: d.number):
        if dia.number == target:
            cercanas = _meal_candidates(nuevo, comidas_libres, medidor)
            secuencia = _trim_to_budget(nuevo, cercanas, restricciones_dia, travel, target)
            dias.append(schedule_day(dia.number, secuencia, restricciones_dia, travel))
            continue

        # Los demas dias tambien se reprograman con `travel` y no con un
        # medidor ya resuelto: cada uno tiene su modo y su red.
        secuencia = [(catalogo[ref], comida) for ref, comida in dia.stops if ref in catalogo]
        if secuencia:
            dias.append(schedule_day(dia.number, secuencia, constraints, travel))

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

    # Sin proveedor, cada dia cae en la estimacion de SU modo: pasar
    # EstimatedTravel(constraints.mode) medía el dia a pie con la velocidad
    # del coche antes siquiera de llegar a la matriz.
    borrador = revise_day(
        db,
        constraints,
        state,
        target,
        day_constraints=day_constraints,
        exclude=exclude,
        travel=None,
    )

    # Una matriz por modo distinto, igual que plan_streaming: a pie y en carro
    # no son la misma red, y medir el dia a pie con la del coche seria
    # inventar. Cuesta una peticion mas solo cuando el viaje mezcla modos.
    lugares_por_modo: dict[str, list[PlaceHit]] = {}
    for dia in borrador.itinerary.days:
        modo = constraints.mode_for(dia.number)
        lugares_por_modo.setdefault(modo, []).extend(parada.place for parada in dia.stops)

    cliente = client if client is not None else client_from_settings()
    matrices = {
        modo: load_travel_matrix(lugares, modo, db=db, client=cliente)
        for modo, lugares in lugares_por_modo.items()
    }

    final = revise_day(
        db,
        constraints,
        state,
        target,
        day_constraints=day_constraints,
        exclude=exclude,
        travel=matrices,
    )
    return RevisionResult(
        itinerary=final.itinerary,
        stats=_merge_matrix_stats(matrices, constraints.mode),
        missing=final.missing,
    )


def used_place_ids(itinerario: Itinerary) -> set[uuid.UUID]:
    return {s.place.id for d in itinerario.days for s in d.stops}


def day_duration(dia: Day) -> timedelta:
    if not dia.stops:
        return timedelta()
    return timedelta(minutes=_minutes_between(dia.start, dia.end))
