/**
 * Dónde se acaba la luz dentro de la línea de tiempo del día.
 *
 * **El hilo que une las paradas ya es un eje de tiempo**: cada tramo va de la
 * hora de una parada a la de la siguiente. Si ese eje cambia de color justo
 * donde se pone el sol, la posición del cambio *es* el dato — se ve de un
 * vistazo qué paradas quedan con luz y cuáles ya de noche, sin leer ninguna
 * hora.
 *
 * El ocaso no es una constante. El motor lo calcula de la latitud y la fecha
 * —`services/sol.py`— y en El Salvador va de las 17:25 a las 18:28 según el
 * mes: una hora de diferencia entre junio y noviembre. Esa misma cuenta es la
 * que el itinerario usa para no mandar a nadie a un mirador a oscuras.
 */

/** "18:28:00" o "18:28" a minutos desde medianoche. */
function minutos(hora: string): number {
  const [h, m] = hora.split(":");
  return Number(h) * 60 + Number(m);
}

/**
 * Qué parte del tramo transcurre con luz, de 0 a 1.
 *
 * 1 es el tramo entero de día, 0 el tramo entero de noche, y un valor
 * intermedio dice exactamente dónde cae el ocaso. Devuelve null cuando no se
 * puede saber —sin fecha no hay ocaso calculado— y entonces el hilo se queda
 * como estaba, que es la respuesta honesta.
 */
export function fraccionConLuz(
  desde: string | null,
  hasta: string | null,
  ocaso: string | null,
): number | null {
  if (!desde || !hasta || !ocaso) return null;

  const inicio = minutos(desde);
  const fin = minutos(hasta);
  const noche = minutos(ocaso);

  if (noche >= fin) return 1;
  if (noche <= inicio) return 0;
  // Un tramo de duración cero no tiene dónde poner el corte: cuenta entero
  // según de qué lado del ocaso esté.
  if (fin === inicio) return noche > inicio ? 1 : 0;

  return (noche - inicio) / (fin - inicio);
}

/** Si a esa hora ya se puso el sol. */
export function esDeNoche(hora: string | null, ocaso: string | null): boolean {
  if (!hora || !ocaso) return false;
  return minutos(hora) >= minutos(ocaso);
}
