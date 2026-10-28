/**
 * Pruebas de dónde se acaba la luz.
 *
 * El valor que sale de acá se convierte en la posición exacta del corte de un
 * degradado, así que un error acá no se ve como un error: se ve como un
 * itinerario que dice que el mirador de las seis de la tarde es de noche.
 */

import { describe, expect, it } from "vitest";

import { esDeNoche, fraccionConLuz } from "./luz";

const OCASO = "18:10:00";

describe("fraccionConLuz", () => {
  it("un tramo que termina antes del ocaso va entero con luz", () => {
    expect(fraccionConLuz("14:00:00", "15:30:00", OCASO)).toBe(1);
  });

  it("un tramo que empieza después del ocaso va entero de noche", () => {
    expect(fraccionConLuz("19:00:00", "20:00:00", OCASO)).toBe(0);
  });

  it("parte el tramo justo donde cae el ocaso", () => {
    // 17:10 a 19:10: dos horas, y el ocaso cae en la primera.
    expect(fraccionConLuz("17:10:00", "19:10:00", OCASO)).toBeCloseTo(0.5);
    // 18:00 a 18:20: el ocaso cae a la mitad.
    expect(fraccionConLuz("18:00:00", "18:20:00", OCASO)).toBeCloseTo(0.5);
    // 17:40 a 18:20: media hora de luz de cuarenta minutos.
    expect(fraccionConLuz("17:40:00", "18:20:00", OCASO)).toBeCloseTo(0.75);
  });

  it("el ocaso exacto en un extremo no parte nada", () => {
    expect(fraccionConLuz("16:00:00", "18:10:00", OCASO)).toBe(1);
    expect(fraccionConLuz("18:10:00", "19:00:00", OCASO)).toBe(0);
  });

  it("un tramo de duración cero no divide por cero", () => {
    expect(fraccionConLuz("17:00:00", "17:00:00", OCASO)).toBe(1);
    expect(fraccionConLuz("19:00:00", "19:00:00", OCASO)).toBe(0);
  });

  it("sin ocaso no inventa nada", () => {
    // Un itinerario sin fecha no tiene ocaso calculado, y entonces el hilo se
    // queda del color de siempre en vez de mentir con un degradado.
    expect(fraccionConLuz("14:00:00", "15:00:00", null)).toBeNull();
    expect(fraccionConLuz(null, "15:00:00", OCASO)).toBeNull();
    expect(fraccionConLuz("14:00:00", null, OCASO)).toBeNull();
  });

  it("acepta horas sin segundos", () => {
    expect(fraccionConLuz("17:40", "18:20", "18:10")).toBeCloseTo(0.75);
  });

  it("siempre devuelve algo que sirve de porcentaje", () => {
    // Lo que sale de acá entra en un linear-gradient: fuera de [0, 1] el corte
    // se sale del hilo y el degradado deja de decir nada.
    for (const [desde, hasta] of [
      ["06:00:00", "22:00:00"],
      ["18:09:00", "18:11:00"],
      ["05:00:00", "06:00:00"],
      ["21:00:00", "23:59:00"],
    ]) {
      const valor = fraccionConLuz(desde, hasta, OCASO);
      expect(valor).not.toBeNull();
      expect(valor).toBeGreaterThanOrEqual(0);
      expect(valor).toBeLessThanOrEqual(1);
    }
  });
});

describe("esDeNoche", () => {
  it("distingue el antes del después", () => {
    expect(esDeNoche("17:00:00", OCASO)).toBe(false);
    expect(esDeNoche("19:00:00", OCASO)).toBe(true);
  });

  it("el minuto exacto del ocaso ya cuenta como noche", () => {
    expect(esDeNoche("18:10:00", OCASO)).toBe(true);
    expect(esDeNoche("18:09:00", OCASO)).toBe(false);
  });

  it("sin ocaso u hora no afirma que sea de noche", () => {
    expect(esDeNoche("19:00:00", null)).toBe(false);
    expect(esDeNoche(null, OCASO)).toBe(false);
  });

  it("sigue al ocaso, que no es una constante", () => {
    // El motor lo calcula de la latitud y la fecha: en El Salvador va de las
    // 17:25 de noviembre a las 18:28 de junio. Las seis de la tarde son de
    // noche en noviembre y de día en junio, y eso tiene que notarse.
    expect(esDeNoche("18:00:00", "17:25:00")).toBe(true);
    expect(esDeNoche("18:00:00", "18:28:00")).toBe(false);
  });
});
