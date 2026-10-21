/**
 * Tests del trazo animado.
 *
 * El fallo que motiva estos tests: la longitud del trazo se media una vez con
 * `getTotalLength()` y se guardaba en una variable CSS que alimentaba el
 * `stroke-dasharray`. Ese numero envejecia —el mapa encuadra el itinerario
 * despues de crear las lineas, y cada zoom vuelve a proyectarlas— y cuando el
 * dasharray queda mas corto que el trazo, el navegador repite el patron y la
 * ruta se ve partida en pedazos. Medido en Chrome sobre un itinerario de tres
 * dias: dasharray de 443 px sobre un trazo de 1.889, ya entrecortado al
 * cargar, y 3.557 tras acercar dos pasos.
 */

import { describe, expect, it } from "vitest";

import { animarTramo } from "./trazo";

function trazo(): SVGPathElement {
  return document.createElementNS("http://www.w3.org/2000/svg", "path");
}

describe("el tramo con carretera", () => {
  it("normaliza su longitud en vez de medirla", () => {
    const nodo = trazo();

    animarTramo(nodo, 0, true);

    // **Este es el test que falla con el codigo viejo.** Sin pathLength, el
    // dasharray queda en pixeles medidos a un zoom que ya cambio.
    expect(nodo.getAttribute("pathLength")).toBe("1");
    expect(nodo.style.getPropertyValue("--largo")).toBe("");
  });

  it("no depende de que el nodo sepa medirse", () => {
    const nodo = trazo();

    // jsdom no implementa getTotalLength. Que esto no reviente es la prueba
    // de que ya no se le pregunta al trazo cuanto mide.
    expect(() => animarTramo(nodo, 0, true)).not.toThrow();
  });

  it("se dibuja de principio a fin", () => {
    const nodo = trazo();
    animarTramo(nodo, 0, true);
    expect(nodo.classList.contains("waypoint-tramo-traza")).toBe(true);
  });
});

describe("el tramo estimado", () => {
  it("aparece en vez de dibujarse", () => {
    const nodo = trazo();
    animarTramo(nodo, 0, false);

    expect(nodo.classList.contains("waypoint-tramo-aparece")).toBe(true);
    expect(nodo.classList.contains("waypoint-tramo-traza")).toBe(false);
  });

  it("conserva su guion, que es el dato", () => {
    /**
     * Su dasharray esta en pixeles y dice que la distancia salio de la linea
     * recta. Normalizar el trazo a 1 convertiria ese guion de 2 px en uno del
     * largo del tramo entero, o sea en una linea solida: seria borrar la
     * informacion que el guion codifica.
     */
    const nodo = trazo();
    animarTramo(nodo, 0, false);

    expect(nodo.getAttribute("pathLength")).toBeNull();
  });
});

describe("el escalonado", () => {
  it("reparte la entrada de los tramos", () => {
    const primero = trazo();
    const segundo = trazo();

    animarTramo(primero, 0, true);
    animarTramo(segundo, 1, true);

    expect(primero.style.getPropertyValue("--retraso")).toBe("0ms");
    expect(segundo.style.getPropertyValue("--retraso")).toBe("160ms");
  });

  it("pone un techo, para que un dia largo no tarde una eternidad en salir", () => {
    const nodo = trazo();
    animarTramo(nodo, 40, true);

    expect(nodo.style.getPropertyValue("--retraso")).toBe("900ms");
  });
});

describe("sin nodo", () => {
  it("no hace nada en vez de reventar", () => {
    expect(() => animarTramo(null, 0, true)).not.toThrow();
  });
});
