/**
 * Tests del formato de fechas.
 *
 * El caso que importa es el primero: una fecha ISO parseada como UTC y
 * mostrada en hora de El Salvador cae en el dia anterior. Es un fallo de un
 * dia entero que no se nota leyendo el codigo.
 */

import { describe, expect, it } from "vitest";

import { fechaCorta, fechaEnPalabras } from "./fecha";

describe("fechaEnPalabras", () => {
  it("no se corre un día hacia atrás", () => {
    /* new Date("2026-09-11").toLocaleDateString() da el 10 al oeste de
       Greenwich. Esta es la razon de ser del modulo. */
    expect(fechaEnPalabras("2026-09-11")).toContain("11");
    expect(fechaEnPalabras("2026-09-11")).toContain("septiembre");
  });

  it("dice el día de la semana", () => {
    expect(fechaEnPalabras("2026-09-11")).toContain("viernes");
  });

  it("devuelve null cuando no hay fecha", () => {
    expect(fechaEnPalabras(null)).toBeNull();
    expect(fechaEnPalabras("")).toBeNull();
  });

  it("devuelve null en vez de inventar una fecha imposible", () => {
    /* El 31 de febrero se desborda a marzo si no se comprueba, y mostrar
       "3 de marzo" cuando el backend dijo febrero es peor que no mostrar
       nada. */
    expect(fechaEnPalabras("2026-02-31")).toBeNull();
    expect(fechaEnPalabras("mañana")).toBeNull();
    expect(fechaEnPalabras("2026-9-1")).toBeNull();
  });

  it("cruza el fin de año sin perder el día", () => {
    expect(fechaEnPalabras("2026-12-31")).toContain("31");
    expect(fechaEnPalabras("2027-01-01")).toContain("1");
  });
});

describe("fechaCorta", () => {
  it("da el día y el mes abreviado, sin punto", () => {
    const corta = fechaCorta("2026-09-11");

    expect(corta).toContain("11");
    expect(corta).not.toContain(".");
  });

  it("devuelve null cuando no hay fecha", () => {
    expect(fechaCorta(null)).toBeNull();
  });
});
