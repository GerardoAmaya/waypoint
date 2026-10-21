/**
 * Tests de la separacion de pines.
 *
 * Lo que motiva el modulo: medido sobre los 60 dias del banco, 33 (55%) tienen
 * al menos un par de pines superpuestos, 69 pares en total, y los peores caen
 * en el mismo pixel. Con el abanico quedan 7 dias y 13 pares. El numero del
 * pin es el orden del recorrido, y un orden tapado no se lee ni se puede
 * tocar.
 */

import { describe, expect, it } from "vitest";

import { DIAMETRO_PIN, separar, type Punto } from "./abanico";

/** Cuanta pantalla queda entre dos pines ya corridos. */
function separacion(puntos: Punto[], corrimientos: Punto[], i: number, j: number) {
  const a = { x: puntos[i].x + corrimientos[i].x, y: puntos[i].y + corrimientos[i].y };
  const b = { x: puntos[j].x + corrimientos[j].x, y: puntos[j].y + corrimientos[j].y };
  return Math.hypot(a.x - b.x, a.y - b.y);
}

describe("los pines que no se tocan", () => {
  it("se quedan donde estan", () => {
    const puntos = [
      { x: 0, y: 0 },
      { x: 300, y: 120 },
      { x: 50, y: 400 },
    ];

    expect(separar(puntos)).toEqual([
      { x: 0, y: 0 },
      { x: 0, y: 0 },
      { x: 0, y: 0 },
    ]);
  });

  it("uno solo no se mueve", () => {
    expect(separar([{ x: 10, y: 10 }])).toEqual([{ x: 0, y: 0 }]);
  });

  it("sin paradas no revienta", () => {
    expect(separar([])).toEqual([]);
  });
});

describe("los pines encimados", () => {
  it("dejan de taparse", () => {
    // El caso de Suchitoto: tres paradas en el casco urbano, practicamente en
    // el mismo pixel.
    const puntos = [
      { x: 500, y: 300 },
      { x: 501, y: 300 },
      { x: 500, y: 302 },
    ];
    const corrimientos = separar(puntos);

    for (const [i, j] of [
      [0, 1],
      [0, 2],
      [1, 2],
    ]) {
      expect(separacion(puntos, corrimientos, i, j)).toBeGreaterThanOrEqual(
        DIAMETRO_PIN - 0.01,
      );
    }
  });

  it("dos se separan exactamente un diametro, ni un pixel mas", () => {
    /**
     * El abanico miente un poco sobre donde esta cada parada. El precio se
     * paga lo justo: lo minimo para despegarlos, no una separacion comoda.
     */
    const puntos = [
      { x: 100, y: 100 },
      { x: 104, y: 100 },
    ];
    const corrimientos = separar(puntos);

    expect(separacion(puntos, corrimientos, 0, 1)).toBeCloseTo(DIAMETRO_PIN, 5);
  });

  it("el grupo queda centrado en el punto compartido", () => {
    /**
     * El centro visual del abanico sigue siendo donde estan las paradas: lo
     * que se mueve es cada pin respecto de ese centro.
     */
    const puntos = [
      { x: 200, y: 200 },
      { x: 202, y: 198 },
      { x: 198, y: 202 },
      { x: 200, y: 204 },
    ];
    const corrimientos = separar(puntos);

    const centroAntes = {
      x: puntos.reduce((s, p) => s + p.x, 0) / puntos.length,
      y: puntos.reduce((s, p) => s + p.y, 0) / puntos.length,
    };
    const centroDespues = {
      x: puntos.reduce((s, p, i) => s + p.x + corrimientos[i].x, 0) / puntos.length,
      y: puntos.reduce((s, p, i) => s + p.y + corrimientos[i].y, 0) / puntos.length,
    };

    expect(centroDespues.x).toBeCloseTo(centroAntes.x, 5);
    expect(centroDespues.y).toBeCloseTo(centroAntes.y, 5);
  });

  it("agrupa por contacto en cadena, no solo de a pares", () => {
    /**
     * Si A tapa a B y B tapa a C, los tres van al mismo abanico aunque A y C
     * no se toquen entre si. Resolverlos de a pares dejaria a A y C donde
     * estaban y B saldria disparado entre los dos.
     */
    const puntos = [
      { x: 0, y: 0 },
      { x: 20, y: 0 },
      { x: 40, y: 0 },
    ];
    const corrimientos = separar(puntos);

    expect(corrimientos.every((c) => c.x !== 0 || c.y !== 0)).toBe(true);
    expect(separacion(puntos, corrimientos, 0, 2)).toBeGreaterThanOrEqual(
      DIAMETRO_PIN - 0.01,
    );
  });

  it("dos grupos lejanos no se mezclan", () => {
    const puntos = [
      { x: 0, y: 0 },
      { x: 4, y: 0 },
      { x: 600, y: 0 },
      { x: 604, y: 0 },
    ];
    const corrimientos = separar(puntos);

    // Cada par se abre alrededor de su propio centro; nadie cruza la pantalla.
    expect(Math.abs(corrimientos[0].x)).toBeLessThan(DIAMETRO_PIN);
    expect(Math.abs(corrimientos[2].x)).toBeLessThan(DIAMETRO_PIN);
    expect(separacion(puntos, corrimientos, 0, 1)).toBeCloseTo(DIAMETRO_PIN, 5);
    expect(separacion(puntos, corrimientos, 2, 3)).toBeCloseTo(DIAMETRO_PIN, 5);
  });
});

describe("el abanico desaparece solo", () => {
  it("al acercar, los mismos lugares dejan de necesitarlo", () => {
    /**
     * Esta es la razon de que la separacion se calcule en pixeles y se rehaga
     * en cada zoom. Dos paradas a 80 metros se tapan a zoom 12 y se ven
     * perfectamente a zoom 16: el desplazamiento existe mientras hace falta y
     * no un pixel mas.
     */
    const lejos = [
      { x: 100, y: 100 },
      { x: 108, y: 100 },
    ];
    const cerca = lejos.map((p) => ({ x: 100 + (p.x - 100) * 8, y: p.y }));

    expect(separar(lejos).some((c) => c.x !== 0)).toBe(true);
    expect(separar(cerca)).toEqual([
      { x: 0, y: 0 },
      { x: 0, y: 0 },
    ]);
  });
});
