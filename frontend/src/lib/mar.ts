/**
 * Cómo está el mar, en palabras.
 *
 * **El periodo importa tanto como la altura.** Metro y medio con periodo de
 * 14 segundos es marejada de fondo del Pacífico sur —olas largas, limpias, las
 * que hacen famosas a las puntas salvadoreñas— y metro y medio con periodo de
 * 7 es mar picado por viento local. El mismo número de altura, dos días que no
 * se parecen en nada, y enseñar solo la altura sería enseñar la mitad que no
 * decide.
 *
 * Los cortes no son de gusto: en la escala que usan los partes de oleaje, por
 * debajo de 10 s el mar es de viento, entre 10 y 13 es marejada, y de 13 para
 * arriba es marejada de fondo. Medido sobre el archivo de El Tunco, el periodo
 * va de 8 a 15 s según el día, así que las tres categorías salen.
 */

import type { DaySea } from "./types";

/** Los ocho rumbos, que es lo que una persona dice. */
const RUMBOS = [
  "del norte",
  "del noreste",
  "del este",
  "del sureste",
  "del sur",
  "del suroeste",
  "del oeste",
  "del noroeste",
] as const;

export function rumbo(grados: number): string {
  // +22.5 para que cada rumbo cubra su sector centrado, no desplazado.
  return RUMBOS[Math.floor((((grados % 360) + 360) % 360 + 22.5) / 45) % 8];
}

/** "marejada de fondo", "marejada" o "mar de viento". */
export function tipoDeMarejada(periodoS: number): string {
  if (periodoS >= 13) return "marejada de fondo";
  if (periodoS >= 10) return "marejada";
  return "mar de viento";
}

/**
 * Los números: "1,2 m · 13 s".
 *
 * Separados de las palabras porque van en otra tipografía. La fila del clima
 * ya hace eso —"31°" en monoespaciada y "mayormente despejado" en texto— y
 * meter la frase entera en monoespaciada la alarga hasta partirla en dos
 * líneas.
 *
 * Los decimales con coma, que es la convención del idioma y la que el resto
 * de la pantalla usa.
 */
export function medidasDelMar(mar: DaySea | null): string | null {
  if (!mar) return null;
  const altura = mar.wave_height_m.toFixed(1).replace(".", ",");
  return `${altura} m · ${Math.round(mar.wave_period_s)} s`;
}

/** Las palabras: "del suroeste · marejada de fondo". */
export function lecturaDelMar(mar: DaySea | null): string | null {
  if (!mar) return null;
  return `${rumbo(mar.wave_direction_deg)} · ${tipoDeMarejada(mar.wave_period_s)}`;
}

/** "agua a 31°", o null si no vino. */
export function aguaEnPalabras(mar: DaySea | null): string | null {
  if (!mar || mar.water_temp_c === null) return null;
  return `agua a ${Math.round(mar.water_temp_c)}°`;
}
