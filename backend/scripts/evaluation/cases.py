"""Peticiones con restricciones conocidas.

Cubren las zonas y los tipos de restriccion, e **incluyen a proposito los
casos donde ya sabemos que el sistema sufre**: Perquin tiene nueve lugares que
no son destino en quince kilometros, Costa del Sol tiene diecisiete destinos
en total, y dentro del Parque El Imposible no hay donde comer.

Una muestra que solo tomara San Salvador y la Ruta de las Flores mediria un
sistema mas facil que el que existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from app.models import Category
from app.services.geocode import find_zone
from app.services.itinerary import Constraints


@dataclass(frozen=True)
class Case:
    name: str
    zone: str
    constraints: Constraints
    # Por que esta este caso. Va al reporte para que un fallo se entienda.
    why: str


def _en(zona: str, **extra) -> Constraints:
    z = find_zone(zona)
    if z is None:
        raise ValueError(f"zona desconocida en los casos: {zona}")
    base = dict(
        days=2,
        center_lat=z.lat,
        center_lon=z.lon,
        radius_m=z.radius_m,
    )
    base.update(extra)
    return Constraints(**base)


CASES: tuple[Case, ...] = (
    # --- Zonas con material de sobra -------------------------------------
    Case("capital-2d", "San Salvador", _en("San Salvador"), "zona densa, caso facil"),
    Case(
        "flores-3d",
        "Concepcion de Ataco",
        _en("Concepcion de Ataco", days=3),
        "la ruta turistica principal",
    ),
    Case("santa-ana-2d", "Santa Ana", _en("Santa Ana"), "zona grande"),
    Case("coatepeque-2d", "Lago de Coatepeque", _en("Lago de Coatepeque"), "lago"),
    Case("cerro-verde-2d", "Cerro Verde", _en("Cerro Verde"), "volcanes"),
    # --- Zonas flacas, donde se espera que falle --------------------------
    Case(
        "perquin-2d",
        "Perquin",
        _en("Perquin"),
        "solo 9 lugares que no son destino: el almuerzo deberia fallar",
    ),
    Case(
        "costa-del-sol-3d",
        "Costa del Sol",
        _en("Costa del Sol", days=3),
        "17 destinos en total: tres dias no deberian salir",
    ),
    Case(
        "metapan-2d",
        "Metapan",
        _en("Metapan"),
        "muchos destinos y pocos restaurantes",
    ),
    Case("la-palma-2d", "La Palma", _en("La Palma"), "zona chica de montana"),
    Case("alegria-2d", "Alegria", _en("Alegria"), "pueblo pequeno"),
    # --- Horarios ---------------------------------------------------------
    Case(
        "arranque-tarde",
        "Concepcion de Ataco",
        _en("Concepcion de Ataco", earliest_start=time(11, 0)),
        "odio madrugar",
    ),
    Case(
        "dia-corto",
        "San Salvador",
        _en("San Salvador", earliest_start=time(10, 0), latest_end=time(15, 0)),
        "ventana estrecha: el motor tiene que recortar",
    ),
    Case(
        "dia-largo",
        "San Salvador",
        _en("San Salvador", latest_end=time(21, 0), max_stops_per_day=9),
        "dia que llega a la cena",
    ),
    # --- Traslado ---------------------------------------------------------
    Case(
        "poco-carro",
        "Santa Ana",
        _en("Santa Ana", max_travel_km_per_day=10),
        "limite apretado en zona grande",
    ),
    Case(
        "muy-poco-carro",
        "Concepcion de Ataco",
        _en("Concepcion de Ataco", max_travel_km_per_day=3),
        "limite casi imposible: se espera un dia de una parada",
    ),
    Case(
        "a-pie",
        "San Salvador",
        _en("San Salvador", mode="walking", max_travel_km_per_day=6, radius_m=5_000),
        "caminando por el centro",
    ),
    Case(
        "sin-limite",
        "San Salvador",
        _en("San Salvador", max_travel_km_per_day=200),
        "sin restriccion practica de traslado",
    ),
    # --- Categorias -------------------------------------------------------
    Case(
        "sin-naturaleza",
        "Concepcion de Ataco",
        _en("Concepcion de Ataco", avoided_categories=[Category.nature]),
        "evitar la categoria que domina el catalogo",
    ),
    Case(
        "solo-cultura",
        "San Salvador",
        _en("San Salvador", preferred_categories=[Category.culture]),
        "preferencia clara",
    ),
    Case(
        "sin-comidas",
        "Suchitoto",
        _en("Suchitoto", include_meals=False),
        "sin restaurantes pedidos",
    ),
    Case(
        "evitar-dos",
        "Santa Ana",
        _en(
            "Santa Ana",
            avoided_categories=[Category.nature, Category.culture],
            max_travel_km_per_day=60,
        ),
        "evitar dos de las tres categorias con material",
    ),
    # --- Paradas ----------------------------------------------------------
    Case(
        "dia-liviano",
        "Concepcion de Ataco",
        _en("Concepcion de Ataco", max_stops_per_day=2),
        "pocos lugares por dia",
    ),
    Case(
        "dia-cargado",
        "San Salvador",
        _en("San Salvador", max_stops_per_day=10, latest_end=time(21, 0)),
        "muchos lugares por dia",
    ),
    # --- Varios dias ------------------------------------------------------
    Case(
        "semana-completa",
        "San Salvador",
        _en("San Salvador", days=7, radius_m=25_000),
        "el maximo de dias en la zona mas densa",
    ),
    Case(
        "una-semana-en-zona-chica",
        "Alegria",
        _en("Alegria", days=7),
        "siete dias donde no hay material: deberia reportar dias faltantes",
    ),
    Case(
        "calidad-alta",
        "San Salvador",
        _en("San Salvador", min_quality=0.6),
        "solo lugares con registro completo",
    ),
)
