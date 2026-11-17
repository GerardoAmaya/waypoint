/**
 * Pruebas del clima en pantalla.
 *
 * Lo que importa acá es no decir de más: "llueve de 14:00 a 20:00" con una
 * tarde seca en medio es la versión educada de decir algo falso.
 */

import { describe, expect, it } from "vitest";
import {
  faBolt,
  faCloud,
  faCloudRain,
  faCloudSun,
  faSmog,
  faSun,
} from "@fortawesome/free-solid-svg-icons";

import { franjas, iconoDelClima, lluviaEnPalabras } from "./clima";

describe("franjas", () => {
  it("junta las horas seguidas", () => {
    expect(franjas([14, 15, 16])).toEqual([[14, 16]]);
  });

  it("separa dos chubascos con una tarde seca en medio", () => {
    expect(franjas([14, 15, 19, 20])).toEqual([
      [14, 15],
      [19, 20],
    ]);
  });

  it("no le molesta el desorden ni los repetidos", () => {
    expect(franjas([16, 14, 15, 15])).toEqual([[14, 16]]);
  });

  it("sin horas no hay franjas", () => {
    expect(franjas([])).toEqual([]);
  });
});

describe("lluviaEnPalabras", () => {
  it("da la franja con los minutos del final", () => {
    /* Hasta las 16:00 y no "hasta las 15:00": la hora 15 llueve entera, así
       que el tramo se cierra en su borde. El ":59" de antes era exacto y se
       leía como un error de formato. */
    expect(lluviaEnPalabras([13, 14, 15])).toBe("de 13:00 a 16:00");
  });

  it("una hora sola no se dice como franja", () => {
    expect(lluviaEnPalabras([15])).toBe("a las 15:00");
  });

  it("enumera dos chubascos", () => {
    expect(lluviaEnPalabras([14, 15, 19])).toBe("de 14:00 a 16:00 y a las 19:00");
  });

  it("rellena el cero de la hora", () => {
    expect(lluviaEnPalabras([9])).toBe("a las 09:00");
  });

  it("devuelve null cuando no llueve", () => {
    expect(lluviaEnPalabras([])).toBeNull();
  });
});

describe("iconoDelClima", () => {
  it("elige por el código y no por el texto", () => {
    expect(iconoDelClima(0)).toBe(faSun);
    expect(iconoDelClima(2)).toBe(faCloudSun);
    expect(iconoDelClima(3)).toBe(faCloud);
    expect(iconoDelClima(45)).toBe(faSmog);
    expect(iconoDelClima(63)).toBe(faCloudRain);
    expect(iconoDelClima(81)).toBe(faCloudRain);
    expect(iconoDelClima(95)).toBe(faBolt);
  });

  it("un código desconocido sale como nube y no revienta", () => {
    /* La nieve existe en la tabla de la OMM y no en El Salvador. */
    expect(iconoDelClima(75)).toBe(faCloud);
  });
});

describe("la última hora del día", () => {
  it("no cierra en un 24:00 que no existe", () => {
    expect(lluviaEnPalabras([22, 23])).toBe("desde las 22:00");
  });

  it("una hora suelta se nombra, no se acota", () => {
    expect(lluviaEnPalabras([23])).toBe("a las 23:00");
  });
});
