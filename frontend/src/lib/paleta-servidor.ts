/**
 * Los materiales del proyecto, leídos del CSS en el servidor.
 *
 * **Es [paleta.ts](./paleta.ts) para donde no hay navegador.** La imagen de la
 * tarjeta se genera con Satori, que no resuelve `var()` ni tiene
 * `getComputedStyle`: necesita literales, igual que Leaflet.
 *
 * Y se leen del CSS en vez de copiarse a mano por la razón que ese módulo ya
 * documenta: la primera versión del mapa mantenía una constante paralela a
 * `globals.css` con un comentario en cada lado pidiendo que se cambiaran
 * juntos, y se desincronizaron igual. Una tarjeta con el verde viejo es peor
 * que un pin con el verde viejo, porque la tarjeta se queda en el chat de otra
 * persona.
 *
 * Se lee una vez al cargar el módulo, no por petición: el archivo no cambia
 * entre peticiones y el coste es de arranque.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";

/** Si el token no está, el mismo respaldo legible que usa el cliente. */
const RESPALDO = "#1f2429";

const CSS = await readFile(join(process.cwd(), "src/app/globals.css"), "utf8");

/**
 * El valor de un token de `:root`, ya resuelto si apunta a otro token.
 *
 * `--cat-nature: var(--verde)` es la forma normal de escribirlo en este
 * proyecto —los nombres con significado apuntan a los materiales crudos— así
 * que sin seguir la referencia se devolvería la cadena "var(--verde)", que
 * Satori pinta como nada.
 *
 * Solo se mira el tema oscuro, que es el de base y el de la tarjeta.
 */
export function material(nombre: string, saltos = 4): string {
  const encontrado = CSS.match(
    new RegExp(`--${nombre}\\s*:\\s*([^;]+);`),
  )?.[1]?.trim();
  if (!encontrado) return RESPALDO;

  const referencia = encontrado.match(/^var\(\s*--([\w-]+)\s*\)$/);
  if (referencia) {
    // Un token que se apunta a sí mismo, o una cadena larga, no puede colgar
    // la generación de la imagen.
    return saltos > 0 ? material(referencia[1], saltos - 1) : RESPALDO;
  }
  return encontrado;
}
