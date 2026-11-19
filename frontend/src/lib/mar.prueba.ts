/**
 * Pruebas de cómo se lee el mar.
 *
 * Lo que decide si esto es un dato o un adorno es el periodo: si la pantalla
 * dijera solo la altura, dos días que no se parecen en nada se verían iguales.
 */

import { describe, expect, it } from "vitest";

import {
  aguaEnPalabras,
  lecturaDelMar,
  medidasDelMar,
  rumbo,
  tipoDeMarejada,
} from "./mar";
import type { DaySea } from "./types";

const mar = (parcial: Partial<DaySea> = {}): DaySea => ({
  wave_height_m: 1.2,
  wave_period_s: 13.4,
  wave_direction_deg: 211,
  water_temp_c: 30.9,
  ...parcial,
});

describe("tipoDeMarejada", () => {
  it("separa la marejada de fondo del mar de viento", () => {
    // La escala de los partes de oleaje: bajo 10 s es viento local, de 13 en
    // adelante es marejada de fondo. Medido sobre el archivo de El Tunco, el
    // periodo va de 8 a 15 s según el día, así que las tres categorías salen.
    expect(tipoDeMarejada(14)).toBe("marejada de fondo");
    expect(tipoDeMarejada(13)).toBe("marejada de fondo");
    expect(tipoDeMarejada(11)).toBe("marejada");
    expect(tipoDeMarejada(8)).toBe("mar de viento");
  });
});

describe("rumbo", () => {
  it("nombra los ocho rumbos como los dice una persona", () => {
    expect(rumbo(0)).toBe("del norte");
    expect(rumbo(90)).toBe("del este");
    expect(rumbo(180)).toBe("del sur");
    expect(rumbo(270)).toBe("del oeste");
  });

  it("211° es del suroeste, que es la marejada clásica del país", () => {
    expect(rumbo(211)).toBe("del suroeste");
  });

  it("cada rumbo cubre su sector centrado, no desplazado", () => {
    expect(rumbo(359)).toBe("del norte");
    expect(rumbo(23)).toBe("del noreste");
    expect(rumbo(22)).toBe("del norte");
  });

  it("no se rompe con grados fuera de rango", () => {
    expect(rumbo(360)).toBe("del norte");
    expect(rumbo(-90)).toBe("del oeste");
  });
});

describe("medidasDelMar y lecturaDelMar", () => {
  it("los números van aparte de las palabras", () => {
    // Van en tipografías distintas: la fila del clima ya separa "31°" de
    // "mayormente despejado", y la frase entera en monoespaciada se parte.
    expect(medidasDelMar(mar())).toBe("1,2 m · 13 s");
    expect(lecturaDelMar(mar())).toBe("del suroeste · marejada de fondo");
  });

  it("dos días con la misma altura no se leen igual", () => {
    // Es la razón de que el periodo esté ahí: sin él estos dos serían
    // indistinguibles, y no se parecen en nada.
    expect(lecturaDelMar(mar({ wave_period_s: 14 }))).toContain("marejada de fondo");
    expect(lecturaDelMar(mar({ wave_period_s: 7 }))).toContain("mar de viento");
  });

  it("los decimales van con coma, como el resto de la pantalla", () => {
    expect(medidasDelMar(mar({ wave_height_m: 1.16 }))).toContain("1,2 m");
    expect(medidasDelMar(mar({ wave_height_m: 0.8 }))).toContain("0,8 m");
  });

  it("redondea al decimal, que es toda la precisión que el parte tiene", () => {
    /*
      Sin el medio exacto a propósito: 0.85 no existe en coma flotante —es
      0.8499…— así que toFixed da "0.8" y no "0.9". No es un fallo que valga
      la pena arreglar en un pronóstico de oleaje, pero una prueba escrita
      sobre ese valor habría fallado por la aritmética y no por el código.
    */
    expect(medidasDelMar(mar({ wave_height_m: 1.04 }))).toContain("1,0 m");
    expect(medidasDelMar(mar({ wave_height_m: 1.88 }))).toContain("1,9 m");
  });

  it("sin mar no dice nada", () => {
    expect(medidasDelMar(null)).toBeNull();
    expect(lecturaDelMar(null)).toBeNull();
  });
});

describe("aguaEnPalabras", () => {
  it("redondea al grado", () => {
    expect(aguaEnPalabras(mar({ water_temp_c: 30.9 }))).toBe("agua a 31°");
  });

  it("sin temperatura no la inventa", () => {
    expect(aguaEnPalabras(mar({ water_temp_c: null }))).toBeNull();
    expect(aguaEnPalabras(null)).toBeNull();
  });
});
