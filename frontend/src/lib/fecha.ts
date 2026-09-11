/**
 * Fechas del itinerario, en palabras.
 *
 * **`new Date("2026-09-11")` no sirve aca y el motivo es sutil.** Una fecha ISO
 * sin hora la parsea el navegador como medianoche UTC, y al mostrarla en hora
 * de El Salvador —seis horas menos— cae en el dia anterior: el itinerario del
 * viernes aparece fechado el jueves. El backend manda un dia del calendario,
 * no un instante, asi que se construye como fecha local y nunca se convierte.
 */

/** "2026-09-11" a una fecha local, sin pasar por UTC. */
function desdeISO(iso: string): Date | null {
  const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!partes) return null;

  const [, año, mes, dia] = partes;
  const fecha = new Date(Number(año), Number(mes) - 1, Number(dia));
  // Un 31 de febrero se desborda a marzo en vez de fallar; comparar el dia lo
  // detecta.
  return fecha.getDate() === Number(dia) ? fecha : null;
}

const CON_DIA_SEMANA = new Intl.DateTimeFormat("es-SV", {
  weekday: "long",
  day: "numeric",
  month: "long",
});

/**
 * "viernes, 11 de septiembre", o null si la fecha no viene o no se entiende.
 *
 * La coma la pone el formato de es-SV y se deja: es la convencion del idioma,
 * y quitarla a mano seria discutir con CLDR por gusto.
 */
export function fechaEnPalabras(iso: string | null): string | null {
  if (!iso) return null;
  const fecha = desdeISO(iso);
  return fecha ? CON_DIA_SEMANA.format(fecha) : null;
}

/** "11 sep", para donde no cabe el nombre del dia. */
export function fechaCorta(iso: string | null): string | null {
  if (!iso) return null;
  const fecha = desdeISO(iso);
  if (!fecha) return null;
  return new Intl.DateTimeFormat("es-SV", {
    day: "numeric",
    month: "short",
  })
    .format(fecha)
    .replace(".", "");
}
