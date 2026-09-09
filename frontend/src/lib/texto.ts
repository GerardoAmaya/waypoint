/**
 * El itinerario como texto plano.
 *
 * Un plan de viaje termina pegado en un chat o en una nota del telefono, y
 * hasta ahora la unica forma de sacarlo de la pantalla era una captura. El
 * texto plano viaja a todas partes, se puede editar, y no depende de que el
 * backend siga en linea.
 *
 * Se escribe a mano y no con una plantilla: son treinta lineas y a cambio el
 * resultado se lee como lo escribiria una persona, con las horas alineadas.
 */

import { CATEGORIA } from "./categorias";
import type { Interpretation, Itinerary } from "./types";

const FUENTE_TEXTO: Record<string, string> = {
  estimated: "Distancias estimadas en línea recta",
  mixed: "Distancias medidas sobre carretera, algunas estimadas",
  real: "Distancias medidas sobre carretera",
};

const hora = (valor: string | null) => (valor ? valor.slice(0, 5) : "");

export function itinerarioComoTexto(
  itinerario: Itinerary,
  interpretacion: Interpretation | null,
): string {
  const lineas: string[] = [];
  const dias = itinerario.days.length;

  lineas.push(interpretacion?.area?.name ?? "Itinerario");
  lineas.push(
    `${dias} ${dias === 1 ? "día" : "días"} · ${itinerario.total_stops} paradas`,
  );
  lineas.push(FUENTE_TEXTO[itinerario.travel.source] ?? "");
  lineas.push("");

  for (const dia of itinerario.days) {
    lineas.push(
      `DÍA ${dia.number} · ${hora(dia.start)}–${hora(dia.end)} · ${dia.travel_km.toFixed(1)} km`,
    );

    for (const parada of dia.stops) {
      const etiqueta =
        parada.meal === "lunch"
          ? "Almuerzo"
          : parada.meal === "dinner"
            ? "Cena"
            : CATEGORIA[parada.place.category].nombre;

      lineas.push(
        `  ${hora(parada.arrival)}  ${parada.place.name} (${etiqueta})`,
      );
      lineas.push(`         hasta las ${hora(parada.departure)}`);

      if (parada.travel_km_from_previous > 0) {
        lineas.push(
          `         ${parada.travel_km_from_previous.toFixed(1)} km · ${parada.travel_minutes_from_previous} min desde la parada anterior`,
        );
      }
    }

    // Los avisos del dia van con el dia, igual que en pantalla.
    for (const v of itinerario.violations.filter((x) => x.day === dia.number)) {
      lineas.push(`  ! ${v.detail}`);
    }
    for (const a of itinerario.advice.filter((x) => x.day === dia.number)) {
      lineas.push(`  * ${a.detail}`);
    }

    lineas.push("");
  }

  const generales = itinerario.violations.filter((v) => v.day === null);
  if (generales.length) {
    for (const v of generales) lineas.push(`! ${v.detail}`);
    lineas.push("");
  }

  lineas.push("Armado con Waypoint · lugares reales, distancias medidas");

  return lineas.join("\n");
}
