/**
 * Un itinerario compartido, resumido para la tarjeta del enlace.
 *
 * **Compartir ya existía y el enlace no se previsualizaba.** Toda la función
 * consiste en pegar la URL en un chat, y hasta ahora salía el mismo texto para
 * los tres días por la Ruta de las Flores que para una tarde en San Salvador:
 * el título del sitio. El único sitio donde el producto se encuentra con otra
 * gente no sabía decir qué plan era.
 *
 * Esto vive aparte de la imagen a propósito. La imagen es JSX para Satori y no
 * se puede probar sin pintarla; qué dice la tarjeta sí, y es lo que puede
 * salir mal: un día sin fecha, un itinerario sin zona, un viaje de un día que
 * dice "1 días".
 */

import { fechaCorta } from "./fecha";
import type { Category, Interpretation, Itinerary } from "./types";

export interface Tarjeta {
  /** La zona, o un respaldo cuando el itinerario no salió de una. */
  titulo: string;
  /** "14 nov – 16 nov", o null si el viaje no trae fechas. */
  fechas: string | null;
  /** Una fila por día, con una categoría por parada en orden. */
  dias: { etiqueta: string; paradas: Category[] }[];
  /** "18 paradas · 124 km". */
  resumen: string;
}

/** "1 día" y no "1 días": sale en la tarjeta, que es donde se nota. */
const plural = (n: number, singular: string, plural: string) =>
  `${n} ${n === 1 ? singular : plural}`;

/**
 * Los kilómetros del viaje entero.
 *
 * Se suman los días en vez de leer un total porque el itinerario no trae uno:
 * `travel_km` es por día. Redondeado a entero, que es la precisión que una
 * tarjeta puede sostener.
 */
function kilometros(itinerary: Itinerary): number {
  return Math.round(itinerary.days.reduce((suma, d) => suma + d.travel_km, 0));
}

export function describir(
  interpretation: Interpretation | null,
  itinerary: Itinerary,
): Tarjeta {
  const dias = itinerary.days.map((dia) => ({
    // Con fecha, la fecha; sin ella, el número, que es lo que enseña la
    // pantalla cuando el viaje no dice cuándo.
    etiqueta: fechaCorta(dia.date) ?? `Día ${dia.number}`,
    paradas: dia.stops.map((p) => p.place.category),
  }));

  const primera = fechaCorta(itinerary.days[0]?.date ?? null);
  const ultima = fechaCorta(
    itinerary.days[itinerary.days.length - 1]?.date ?? null,
  );

  return {
    titulo: interpretation?.area?.name ?? "Un itinerario por El Salvador",
    // Un viaje de un solo día no es un rango: "14 nov – 14 nov" se lee como
    // un error de formato, no como un día.
    fechas: primera && ultima && primera !== ultima ? `${primera} – ${ultima}` : primera,
    dias,
    resumen: [
      plural(itinerary.days.length, "día", "días"),
      plural(itinerary.total_stops, "parada", "paradas"),
      `${kilometros(itinerary)} km`,
    ].join(" · "),
  };
}
