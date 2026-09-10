/**
 * Lo que hace falta antes de cada prueba.
 *
 * jsdom no trae matchMedia, y el proyecto lo usa para dos cosas de verdad: el
 * tema del sistema y prefers-reduced-motion. Sin este doble, montar cualquier
 * componente que lea una de las dos revienta antes de llegar a la asercion.
 */
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Los matchers de DOM: toBeDisabled, toHaveValue, toHaveTextContent. Sin
// ellos cada asercion se escribe leyendo propiedades a mano y el test deja de
// decir lo que comprueba.
import "@testing-library/jest-dom/vitest";

if (!window.matchMedia) {
  window.matchMedia = (consulta: string) =>
    ({
      matches: false,
      media: consulta,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

// jsdom tampoco implementa scrollIntoView, y el detalle de una parada lo usa
// al abrirse para no quedar debajo del borde del panel. Sin el doble, elegir
// una parada revienta dentro de un useEffect.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// El almacenamiento es por navegador y las pruebas comparten el mismo: sin
// limpiarlo, el tema que elige una prueba lo hereda la siguiente.
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
