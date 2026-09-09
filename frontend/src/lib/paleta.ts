/**
 * Los materiales del proyecto, leidos del CSS en tiempo de ejecucion.
 *
 * Leaflet escribe el color como atributo de presentacion del SVG y ahi var()
 * no resuelve de forma fiable, asi que el mapa necesita literales. La primera
 * version los mantenia a mano en una constante paralela a globals.css, con un
 * comentario en cada lado pidiendo que se cambiaran juntos; se desincronizaron
 * igual —tinta-suave termino con dos valores distintos.
 *
 * Resolverlos con getComputedStyle deja el CSS como fuente unica y de paso
 * hace que el mapa siga al tema sin trabajo extra, si algun dia un material
 * llega a depender del tema.
 *
 * Solo corre en el cliente: Mapa se carga con ssr:false porque Leaflet toca
 * window al importarse.
 */

const MATERIALES = [
  "niebla",
  "grafito",
  "anil",
  "anil-claro",
  "cafe",
  "verde",
  "ocre",
  "acero-claro",
  "acero-profundo",
] as const;

export type Material = (typeof MATERIALES)[number];

export type Materiales = Record<Material, string>;

/**
 * Si la hoja no cargo, getPropertyValue devuelve cadena vacia y Leaflet
 * dibujaria con su azul por defecto. En ese escenario la pagina entera esta sin
 * estilos y un pin de color raro es el menor de los problemas, pero un negro
 * legible es mejor que un fallo silencioso a azul de biblioteca.
 */
const RESPALDO = "#1f2429";

export function leerMateriales(): Materiales {
  const estilo = getComputedStyle(document.documentElement);
  const salida = {} as Materiales;
  for (const material of MATERIALES) {
    salida[material] =
      estilo.getPropertyValue(`--${material}`).trim() || RESPALDO;
  }
  return salida;
}
