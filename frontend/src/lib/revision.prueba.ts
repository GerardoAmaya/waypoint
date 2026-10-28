/**
 * Pruebas de lo que la revisión contesta.
 *
 * Lo que sale de acá es lo único que el usuario va a leer sobre un cambio que
 * ya se aplicó: si una restricción se queda sin nombre, el día se movió y la
 * pantalla se calló.
 */

import { describe, expect, it } from "vitest";

import { dijoAlgo, loQueCambio } from "./revision";
import type { Revision } from "./types";

const revision = (parcial: Partial<Revision> = {}): Revision =>
  ({
    itinerary: null,
    applied: {},
    removed: [],
    missing: [],
    unmapped: [],
    notes: [],
    ...parcial,
  }) as unknown as Revision;

describe("loQueCambio", () => {
  it("nombra las horas sin los segundos", () => {
    const { cambios } = loQueCambio(
      revision({ applied: { earliest_start: "07:00:00", latest_end: "20:30:00" } }),
    );

    expect(cambios).toEqual([
      "Empieza a las 07:00",
      "Termina antes de las 20:30",
    ]);
  });

  it("traduce las categorías al nombre que usa el resto de la pantalla", () => {
    const { cambios } = loQueCambio(
      revision({
        applied: {
          preferred_categories: ["nature", "viewpoint"],
          avoided_categories: ["culture"],
        },
      }),
    );

    expect(cambios).toEqual(["Prefiere naturaleza y mirador", "Evita cultura"]);
  });

  it("concuerda el singular de las paradas", () => {
    expect(loQueCambio(revision({ applied: { max_stops_per_day: 1 } })).cambios)
      .toEqual(["Máximo 1 parada"]);
    expect(loQueCambio(revision({ applied: { max_stops_per_day: 4 } })).cambios)
      .toEqual(["Máximo 4 paradas"]);
  });

  it("dice el sí y el no de las comidas", () => {
    expect(loQueCambio(revision({ applied: { include_meals: false } })).cambios)
      .toEqual(["Sin comidas"]);
    expect(
      loQueCambio(revision({ applied: { must_include_meals: ["breakfast", "dinner"] } }))
        .cambios,
    ).toEqual(["Con desayuno y cena"]);
  });

  it("desarma los minutos por categoría", () => {
    const { cambios } = loQueCambio(
      revision({ applied: { category_minutes: { culture: 90, nature: 120 } } }),
    );

    expect(cambios).toEqual(["90 min en cultura y 120 min en naturaleza"]);
  });

  it("una clave que no conoce sale cruda en vez de desaparecer", () => {
    // Si el backend aprende una restricción nueva y esto no se actualiza, el
    // día se mueve igual. Un cambio aplicado y sin nombrar es peor que uno
    // nombrado a medias.
    const { cambios } = loQueCambio(
      revision({ applied: { max_altitude_m: 2000 } }),
    );

    expect(cambios).toEqual(["max_altitude_m: 2000"]);
  });

  it("junta lo que no supo usar con los avisos", () => {
    // Para quien mira su itinerario los dos dicen lo mismo: no se usó.
    const { avisos } = loQueCambio(
      revision({
        unmapped: ["el cerro ese"],
        notes: ["no hay ninguna parada llamada 'museo' en ese día"],
      }),
    );

    expect(avisos).toEqual([
      "el cerro ese",
      "no hay ninguna parada llamada 'museo' en ese día",
    ]);
  });

  it("pasa las paradas que sacó tal cual", () => {
    const { quitadas } = loQueCambio(
      revision({ removed: ["Montemilia", "Palm Plaza"] }),
    );

    expect(quitadas).toEqual(["Montemilia", "Palm Plaza"]);
  });

  it("no revienta con una respuesta a medias", () => {
    // El servidor puede omitir los campos vacíos, y una pantalla que se rompe
    // por un campo que falta es peor que una que no dice nada.
    const cambio = loQueCambio({ itinerary: null } as unknown as Revision);

    expect(cambio).toEqual({ cambios: [], quitadas: [], avisos: [] });
  });
});

describe("dijoAlgo", () => {
  it("un día que se rehízo sin cambiar nada no tiene nada que contar", () => {
    expect(dijoAlgo(loQueCambio(revision()))).toBe(false);
  });

  it("cualquiera de las tres cosas cuenta", () => {
    expect(dijoAlgo(loQueCambio(revision({ applied: { include_meals: true } })))).toBe(true);
    expect(dijoAlgo(loQueCambio(revision({ removed: ["Palm Plaza"] })))).toBe(true);
    expect(dijoAlgo(loQueCambio(revision({ unmapped: ["el cerro"] })))).toBe(true);
  });
});
