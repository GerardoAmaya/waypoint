/**
 * Pruebas de qué trecho va bajo agua.
 *
 * Lo que sale de acá se convierte en la posición de una franja de lluvia sobre
 * la línea de tiempo. Un error no se ve como un error: se ve como un
 * itinerario que dice que llueve sobre la parada equivocada.
 */

import { describe, expect, it } from "vitest";

import { tramosDeLluvia } from "./lluvia";

describe("tramosDeLluvia", () => {
  it("marca la hora que coincide y nada más", () => {
    // Tramo de 12:00 a 16:00 —cuatro horas— con lluvia a las 14:00. La hora
    // vale el intervalo entero, así que es el tercer cuarto del tramo.
    expect(tramosDeLluvia("12:00:00", "16:00:00", [14])).toEqual([[0.5, 0.75]]);
  });

  it("pega las horas seguidas en un solo trecho", () => {
    // Tres horas de chubasco son una franja, no tres rayas.
    expect(tramosDeLluvia("12:00:00", "16:00:00", [13, 14, 15])).toEqual([
      [0.25, 1],
    ]);
  });

  it("no junta dos chubascos con una tarde seca en medio", () => {
    expect(tramosDeLluvia("12:00:00", "16:00:00", [12, 15])).toEqual([
      [0, 0.25],
      [0.75, 1],
    ]);
  });

  it("recorta la lluvia que se sale del tramo", () => {
    // Llueve a las 11:00 y a las 16:00, y el tramo va de 11:30 a 16:30: de la
    // primera entra media hora, de la segunda también.
    expect(tramosDeLluvia("11:30:00", "16:30:00", [11, 16])).toEqual([
      [0, 0.1],
      [0.9, 1],
    ]);
  });

  it("no le molesta el desorden ni los repetidos", () => {
    expect(tramosDeLluvia("12:00:00", "16:00:00", [15, 13, 14, 14])).toEqual([
      [0.25, 1],
    ]);
  });

  it("la lluvia de otra hora no pinta nada", () => {
    expect(tramosDeLluvia("12:00:00", "16:00:00", [21])).toEqual([]);
  });

  it("sin pronóstico no hay nada que pintar", () => {
    expect(tramosDeLluvia("12:00:00", "16:00:00", null)).toEqual([]);
    expect(tramosDeLluvia("12:00:00", "16:00:00", [])).toEqual([]);
    expect(tramosDeLluvia(null, "16:00:00", [14])).toEqual([]);
    expect(tramosDeLluvia("12:00:00", null, [14])).toEqual([]);
  });

  it("un tramo que no dura nada no tiene dónde pintar", () => {
    // Pasa de verdad: un día que vuelve al punto de partida llega y sale a la
    // misma hora. Dividir por cero ahí daría Infinity y una franja sin fin.
    expect(tramosDeLluvia("14:00:00", "14:00:00", [14])).toEqual([]);
    expect(tramosDeLluvia("15:00:00", "14:00:00", [14])).toEqual([]);
  });

  it("siempre devuelve fracciones que sirven de porcentaje", () => {
    for (const horas of [[9], [9, 10, 11], [13, 19], [0], [23]]) {
      for (const [a, b] of tramosDeLluvia("09:30:00", "19:45:00", horas)) {
        expect(a).toBeGreaterThanOrEqual(0);
        expect(b).toBeLessThanOrEqual(1);
        expect(b).toBeGreaterThan(a);
      }
    }
  });
});
