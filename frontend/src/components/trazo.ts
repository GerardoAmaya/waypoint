/**
 * Como se anima el trazo de un tramo en el mapa.
 *
 * Vive aparte de Mapa.tsx porque no necesita Leaflet: recibe el nodo SVG ya
 * creado y solo le pone clases y atributos. Asi se puede probar en jsdom, que
 * es donde el resto del mapa no entra —Leaflet mide elementos que ahi no
 * tienen tamano— y este fue justamente el lugar donde se escondio un fallo
 * visible durante meses.
 */

/**
 * El tramo se dibuja de principio a fin, escalonado con los demas.
 *
 * **La longitud se normaliza con `pathLength`, no se mide.** Antes se leia
 * `getTotalLength()` y se guardaba en una variable CSS, y ese numero quedaba
 * pegado al trazo para siempre. Dos cosas lo volvian falso:
 *
 * - Se media al agregar la linea, pero el mapa encuadra el itinerario
 *   *despues*. El trazo se reproyectaba mas largo y el dasharray se quedaba
 *   con el valor viejo.
 * - Cada zoom vuelve a proyectar el trazo y cambia su largo en pixeles. El
 *   dasharray no se enteraba nunca.
 *
 * Cuando el dasharray queda mas corto que el trazo, el navegador repite el
 * patron: raya, hueco, raya. Medido sobre un itinerario de tres dias, un tramo
 * tenia dasharray de 443 px sobre un trazo de 1.889 —ya entrecortado al
 * cargar— y al acercar dos pasos el trazo pasaba a 3.557 y la linea se partia
 * en ocho pedazos.
 *
 * `pathLength="1"` le dice al navegador que mida ese trazo como si midiera 1,
 * sea cual sea su largo real. Entonces `stroke-dasharray: 1` es exactamente el
 * trazo entero a cualquier zoom, y el dashoffset va de 1 a 0 para dibujarlo.
 * Es la respuesta de SVG a este problema y no depende de volver a medir nada.
 *
 * Los tramos punteados no se dibujan, aparecen. Ahi el guion es el dato —dice
 * que la distancia salio de la linea recta— y animar el trazado tendria que
 * sobrescribir el dasharray, que es justamente borrar la informacion. Por eso
 * a esos no se les toca `pathLength`: su guion esta en pixeles, y normalizar
 * el trazo a 1 lo convertiria en un guion del largo del tramo entero.
 */
export function animarTramo(
  nodo: SVGPathElement | null,
  orden: number,
  solido: boolean,
): void {
  if (!nodo) return;

  const retraso = Math.min(orden * 160, 900);
  nodo.style.setProperty("--retraso", `${retraso}ms`);

  if (!solido) {
    nodo.classList.add("waypoint-tramo-aparece");
    return;
  }

  nodo.setAttribute("pathLength", "1");
  nodo.classList.add("waypoint-tramo-traza");
}
