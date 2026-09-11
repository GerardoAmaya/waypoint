/**
 * El clima de un día, para mostrarlo.
 *
 * El icono se elige por el código WMO y no por la descripción: decidir entre
 * sol, nube y tormenta comparando la cadena "chubascos ligeros" ataría el
 * dibujo a la redacción del backend, y cambiar una palabra allá apagaría un
 * icono acá sin que nada lo delate.
 */

import {
  faBolt,
  faCloud,
  faCloudRain,
  faCloudSun,
  faSmog,
  faSun,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";

/**
 * Del código WMO a un icono.
 *
 * Los tramos son los de la tabla de la OMM: 0-1 despejado, 2 con nubes y sol,
 * 3 nublado, 45-48 neblina, 51-67 llovizna y lluvia, 80-82 chubascos, 95+
 * tormenta. Un código que no caiga en ninguno sale como nube, que es lo más
 * neutro que se puede dibujar.
 */
export function iconoDelClima(code: number): IconDefinition {
  if (code <= 1) return faSun;
  if (code === 2) return faCloudSun;
  if (code === 3) return faCloud;
  if (code === 45 || code === 48) return faSmog;
  if (code >= 51 && code <= 67) return faCloudRain;
  if (code >= 80 && code <= 82) return faCloudRain;
  if (code >= 95) return faBolt;
  /* Los tramos son cerrados a propósito y no rangos abiertos. Con `>= 51` a
     secas, los códigos de nieve —71 a 77, que existen en la tabla de la OMM y
     no en El Salvador— caían dentro de la lluvia. Lo que no sabemos dibujar
     sale como nube. */
  return faCloud;
}

/**
 * Agrupa horas sueltas en tramos seguidos: [14,15,16,19] a [[14,16],[19,19]].
 *
 * Hace falta para no decir "llueve de 14:00 a 20:00" cuando lo que hay son dos
 * chubascos con una tarde seca en medio. Es la misma regla que aplica el
 * backend para redactar el aviso; acá se repite porque lo que viaja son las
 * horas, no el texto.
 */
export function franjas(horas: number[]): Array<[number, number]> {
  const tramos: Array<[number, number]> = [];
  for (const hora of [...new Set(horas)].sort((a, b) => a - b)) {
    const ultimo = tramos[tramos.length - 1];
    if (ultimo && hora === ultimo[1] + 1) ultimo[1] = hora;
    else tramos.push([hora, hora]);
  }
  return tramos;
}

const dosDigitos = (n: number) => String(n).padStart(2, "0");

/** "de 13:00 a 15:59", o null si no llueve. */
export function lluviaEnPalabras(horas: number[]): string | null {
  const tramos = franjas(horas);
  if (!tramos.length) return null;

  const textos = tramos.map(([inicio, fin]) =>
    inicio === fin
      ? `a las ${dosDigitos(inicio)}:00`
      : `de ${dosDigitos(inicio)}:00 a ${dosDigitos(fin)}:59`,
  );

  if (textos.length === 1) return textos[0];
  return `${textos.slice(0, -1).join(", ")} y ${textos[textos.length - 1]}`;
}
