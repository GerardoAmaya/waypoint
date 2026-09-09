"""Schemas de la API.

Separados de los modelos ORM para que la base pueda cambiar de forma sin
romper el contrato que consume el frontend.
"""

from __future__ import annotations

import uuid
from datetime import time
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models import Category


class PlaceOut(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    subcategory: str | None = None
    lat: float
    lon: float
    quality_score: float
    # Presente solo en busquedas con un punto de referencia.
    distance_m: float | None = None

    # Los cuatro datos de OSM que existen en cantidad suficiente para valer la
    # pena, medidos sobre el catalogo cargado: cocina en el 42% de los
    # comedores, altitud en el 24% de los lugares naturales, telefono en el 27%
    # de los alojamientos y web en el 17%. Se derivan de las etiquetas en vez de
    # mandarlas crudas: el cliente no tiene por que saber como OSM escribe
    # "contact:phone", y el resto de las etiquetas no le sirve de nada.
    cuisine: str | None = None
    elevation_m: int | None = None
    phone: str | None = None
    website: str | None = None


class PlaceList(BaseModel):
    items: list[PlaceOut]
    total: int


class PlaceField(BaseModel):
    """Las coordenadas del catalogo entero, sin nada mas.

    Pares [lat, lon] en vez de objetos: con cinco mil seiscientos lugares, la
    diferencia son cientos de kilobytes de nombres y categorias que el estado
    vacio del mapa no dibuja.
    """

    points: list[list[float]]
    total: int


class CatalogStats(BaseModel):
    active: int
    downloaded: int
    duplicates: int
    by_category: dict[str, int]


class NearbyQuery(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=5_000, ge=1, le=100_000)
    categories: list[Category] | None = None
    include_lodging: bool = False
    min_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=200)


# --------------------------------------------------------------------------
# Itinerarios
# --------------------------------------------------------------------------


class ItineraryRequest(BaseModel):
    """Las restricciones del usuario, ya traducidas a limites verificables.

    En la fase 5 este objeto lo va a llenar el modelo a partir de una frase.
    Que sea un schema explicito y no texto libre es la division de
    responsabilidades del proyecto: el modelo interpreta, el motor cumple.
    """

    days: int = Field(default=1, ge=1, le=7)
    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)

    radius_m: int = Field(default=20_000, ge=1, le=100_000)
    earliest_start: time = time(9, 0)
    latest_end: time = time(20, 0)
    max_travel_km_per_day: float = Field(default=25.0, gt=0, le=500)
    mode: Literal["driving", "walking"] = "driving"

    preferred_categories: list[Category] = Field(default_factory=list)
    avoided_categories: list[Category] = Field(default_factory=list)
    include_meals: bool = True
    max_stops_per_day: int = Field(default=5, ge=1, le=12)
    min_quality: float = Field(default=0.0, ge=0.0, le=1.0)

    # Con rutas reales el itinerario consume cupo de ORS. Se puede apagar para
    # probar o para ahorrar, y la respuesta dice siempre cual se uso.
    real_routes: bool = True

    @model_validator(mode="after")
    def _horario_coherente(self) -> ItineraryRequest:
        if self.earliest_start >= self.latest_end:
            raise ValueError("earliest_start tiene que ser anterior a latest_end")
        if set(self.preferred_categories) & set(self.avoided_categories):
            raise ValueError("una categoria no puede estar preferida y evitada a la vez")
        return self


class StopOut(BaseModel):
    place: PlaceOut
    arrival: time
    departure: time
    travel_minutes_from_previous: int
    travel_km_from_previous: float
    meal: str | None = None

    # El trazo por carretera del tramo que llega a esta parada, en (lat, lon).
    #
    # Va con la parada de destino y no en el dia porque acompaña a
    # travel_km_from_previous, que es el otro dato del mismo tramo. Nulo
    # cuando ese tramo no se pudo enrutar, y eso es informacion: el cliente
    # dibuja la recta punteada y con eso dice que esa distancia es estimada.
    # La primera parada de cada dia nunca lo tiene, porque no llega de ningun
    # lado.
    geometry_from_previous: list[tuple[float, float]] | None = None


class DayOut(BaseModel):
    number: int
    stops: list[StopOut]
    travel_km: float
    start: time | None = None
    end: time | None = None


class ViolationOut(BaseModel):
    """Una restriccion que no se pudo cumplir.

    Se devuelve en vez de ocultarse. Un itinerario que empieza antes de lo
    pedido es un fallo y el usuario tiene que verlo.
    """

    constraint: str
    day: int | None = None
    detail: str


class AdviceOut(BaseModel):
    """Algo que el viajero deberia saber, que no es un limite incumplido.

    Separado de las violaciones a proposito. Que el comedor mas cercano quede
    fuera del presupuesto de traslado no es romper una regla que el usuario
    puso, y la solucion del mundo real es llevar comida.
    """

    kind: str
    day: int | None = None
    detail: str


class TravelSourceOut(BaseModel):
    """De donde salieron las distancias de este itinerario.

    Va en la respuesta a proposito. El usuario ve horas de llegada, y tiene
    derecho a saber si estan medidas sobre carretera o aproximadas desde la
    linea recta.
    """

    # Los contadores en cero son ambiguos: no distinguen "todo estimado" de
    # "no se midio nada". Este campo lo dice sin que haya que deducirlo.
    source: Literal["estimated", "mixed", "real"] = "estimated"
    cached: int = 0
    fetched: int = 0
    estimated: int = 0
    real_ratio: float = 0.0
    # Peticiones a ORS que costo este itinerario. Con la cache caliente es 0.
    requests: int = 0
    # Por que no hubo medidas reales. "no_key", "no_quota" o "unroutable".
    # Decir solo "estimadas" deja al usuario sin saber si falta configurar algo,
    # si hay que esperar, o si el lugar simplemente no tiene camino.
    reason: str | None = None
    # Lo que ORS dice que le queda. None mientras no haya respondido: nuestro
    # presupuesto sin estrenar no es una lectura del cupo real.
    quota_remaining: int | None = None


class ItineraryOut(BaseModel):
    days: list[DayOut]
    violations: list[ViolationOut] = Field(default_factory=list)
    advice: list[AdviceOut] = Field(default_factory=list)
    satisfies_all_constraints: bool
    total_stops: int
    unused_candidates: int
    travel: TravelSourceOut


# --------------------------------------------------------------------------
# Capa conversacional
# --------------------------------------------------------------------------


class PlanMessage(BaseModel):
    """Lo que el usuario escribe, sin estructura."""

    message: str = Field(min_length=1, max_length=600)


class AreaPhotoOut(BaseModel):
    """Una foto libre de la zona, con su credito.

    El autor y la licencia viajan con la imagen porque la licencia de Commons
    los exige. Que sean obligatorios en el schema es a proposito: asi no se
    puede servir la foto sin el credito.
    """

    # Nombre del archivo en Wikimedia Commons. El cliente arma la URL con
    # Special:FilePath, que deja pedir el ancho que necesite.
    file: str
    author: str
    license: str
    page: str


class AreaOut(BaseModel):
    name: str
    lat: float
    lon: float
    radius_m: int
    # "zone" si vino del nomenclator, "catalog" si de la busqueda por nombre.
    source: str
    # Solo las zonas del nomenclator la tienen, y dos de ellas tampoco.
    photo: AreaPhotoOut | None = None


class InterpretationOut(BaseModel):
    """Lo que se entendio de la frase, antes de armar nada.

    `unmapped` y `notes` son la parte importante y no un adorno: dicen que
    quedo afuera y que hubo que recortar. Un planificador que silenciosamente
    ignora la mitad de lo que le pediste es peor que uno que lo admite.
    """

    area: AreaOut | None = None
    constraints: ItineraryRequest | None = None
    unmapped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class StopRefIn(BaseModel):
    """Una parada tal como el cliente la recibio.

    Lleva la etiqueta de comida ademas del identificador para que el dia se
    reconstruya igual. Deducirla de la categoria y la hora acertaria casi
    siempre, y "casi" en un dia que nadie pidio tocar es un dia que se mueve
    solo.
    """

    place_id: uuid.UUID
    meal: str | None = None


class DayStateIn(BaseModel):
    number: int = Field(ge=1, le=7)
    stops: list[StopRefIn] = Field(max_length=12)


class ReviseRequest(BaseModel):
    """Pedido de cambio sobre un dia de un itinerario que el cliente ya tiene.

    El itinerario viaja de ida y vuelta en vez de guardarse en el servidor: sin
    cuentas de usuario, un almacen de sesiones seria estado con caducidad y
    limpieza para nada. Cada identificador se valida contra el catalogo, asi
    que no se pueden inyectar lugares que no existan.
    """

    message: str = Field(min_length=1, max_length=600)
    day: int = Field(ge=1, le=7)
    constraints: ItineraryRequest
    days: list[DayStateIn] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def _el_dia_existe(self) -> ReviseRequest:
        if self.day not in {d.number for d in self.days}:
            raise ValueError(f"el itinerario no tiene un día {self.day}")
        return self


class RevisionOut(BaseModel):
    """El itinerario revisado y que se entendio del pedido."""

    itinerary: ItineraryOut
    applied: dict = Field(default_factory=dict)
    removed: list[str] = Field(default_factory=list)
    # Paradas que ya no estan en el catalogo y salieron del plan.
    missing: list[uuid.UUID] = Field(default_factory=list)
    unmapped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
