/**
 * Constructores de datos para las pruebas.
 *
 * Escritos a mano y no copiados de una respuesta real: un dia de ejemplo con
 * treinta campos esconde cual de ellos es el que la prueba mira.
 */
import type { Day, Place, Stop } from "@/lib/types";

let contador = 0;

export function lugar(parcial: Partial<Place> = {}): Place {
  contador += 1;
  return {
    id: `lugar-${contador}`,
    name: `Lugar ${contador}`,
    category: "culture",
    subcategory: null,
    lat: 13.7,
    lon: -89.22,
    quality_score: 0.6,
    distance_m: null,
    cuisine: null,
    elevation_m: null,
    phone: null,
    website: null,
    ...parcial,
  };
}

export function parada(parcial: Partial<Stop> = {}): Stop {
  return {
    place: lugar(),
    arrival: "10:00:00",
    departure: "11:15:00",
    travel_minutes_from_previous: 10,
    travel_km_from_previous: 2.4,
    meal: null,
    geometry_from_previous: null,
    ...parcial,
  };
}

export function dia(parcial: Partial<Day> = {}): Day {
  const stops = parcial.stops ?? [parada()];
  return {
    number: 1,
    travel_km: 12.3,
    start: stops[0]?.arrival ?? null,
    end: stops[stops.length - 1]?.departure ?? null,
    mode: "driving",
    ...parcial,
    stops,
  };
}
