/**
 * Qué contestó la revisión, en palabras.
 *
 * **El backend ya decía todo esto y la pantalla lo tiraba.** `POST
 * /plan/revise` devuelve qué restricción entendió (`applied`), qué paradas
 * sacó por su nombre (`removed`), qué no supo mapear (`unmapped`) y los avisos
 * del camino (`notes`). El cliente se quedaba solo con el itinerario, así que
 * un «sólo 4 paradas» borraba cuatro lugares y nadie decía cuáles: había que
 * comparar el antes y el después a ojo, y el antes ya no estaba.
 *
 * Las claves de `applied` son las del motor y no texto de pantalla, que es lo
 * correcto —una API no debería hablar castellano— y por eso la traducción vive
 * acá y no allá.
 */

import { CATEGORIA } from "./categorias";
import { COMIDA } from "./texto";
import type { Aplicado, Category, Itinerary, Revision } from "./types";

/** "07:00:00" a "07:00". Lo que viene sin segundos se queda igual. */
const hora = (valor: string) => valor.slice(0, 5);

const categoria = (clave: string) =>
  CATEGORIA[clave as Category]?.nombre.toLowerCase() ?? clave;

const comida = (clave: string) =>
  COMIDA[clave as keyof typeof COMIDA]?.toLowerCase() ?? clave;

/** "a, b y c". El español no lleva coma antes de la última conjunción. */
export function lista(partes: string[]): string {
  if (partes.length <= 1) return partes[0] ?? "";
  return `${partes.slice(0, -1).join(", ")} y ${partes[partes.length - 1]}`;
}

/**
 * Cómo se lee cada restricción que la revisión pudo tocar.
 *
 * Están las diez que el intérprete sabe devolver. Una clave que no esté acá
 * —porque el backend aprendió una nueva y esto no se actualizó— se muestra
 * cruda en vez de desaparecer: un cambio que se aplicó y no se nombra es
 * peor que uno nombrado a medias.
 */
const COMO_SE_DICE: Record<string, (v: Aplicado) => string> = {
  earliest_start: (v) => `Empieza a las ${hora(String(v))}`,
  latest_end: (v) => `Termina antes de las ${hora(String(v))}`,
  max_travel_km_per_day: (v) => `Máximo ${v} km`,
  max_stops_per_day: (v) => `Máximo ${v} ${Number(v) === 1 ? "parada" : "paradas"}`,
  preferred_categories: (v) => `Prefiere ${lista((v as string[]).map(categoria))}`,
  avoided_categories: (v) => `Evita ${lista((v as string[]).map(categoria))}`,
  include_meals: (v) => (v ? "Con comidas" : "Sin comidas"),
  must_include_meals: (v) => `Con ${lista((v as string[]).map(comida))}`,
  meal_minutes: (v) => `${v} min por comida`,
  category_minutes: (v) =>
    lista(
      Object.entries(v as Record<string, number>).map(
        ([c, m]) => `${m} min en ${categoria(c)}`,
      ),
    ),
};

export interface LoQueCambio {
  /** Las restricciones que entendió, ya en castellano. */
  cambios: string[];
  /** Las paradas que sacó por su nombre. */
  quitadas: string[];
  /**
   * Las paradas que no estaban antes en ese día.
   *
   * **Rehacer un día no es un trueque de uno por uno.** Quitar una parada
   * libera su rato y el motor rellena el día con lo que quepa: sacar una
   * pizzería de un día de seis puede traer tres lugares nuevos. Decir solo lo
   * que salió deja la mitad de la historia, y la otra mitad hay que buscarla
   * comparando con un día que ya no está en pantalla.
   */
  entraron: string[];
  /** Lo que no supo usar y los avisos del camino. */
  avisos: string[];
  /**
   * Los consejos que este cambio provocó y que antes no estaban.
   *
   * **Aplicar una restricción y cumplirla no son lo mismo.** Pedir desayuno a
   * un día que empieza a las 10:00 aplica la restricción —y la revisión lo
   * dice— pero el desayuno no cabe, porque su franja cierra a las 09:30. El
   * motor ya explicaba exactamente eso; lo hacía al final de la lista de
   * paradas, debajo de siete, donde no se ve.
   */
  consecuencias: string[];
}

/**
 * Los consejos del día revisado que no estaban antes.
 *
 * Se diferencia contra el itinerario anterior en vez de mostrar todos los del
 * día porque los que ya estaban —que llueve sobre el mirador— siguen abajo,
 * donde viven, y repetirlos arriba convertiría la respuesta en un resumen del
 * día en vez de en la respuesta a lo que se acaba de pedir.
 *
 * El texto es la identidad: dos consejos del mismo tipo se distinguen por lo
 * que dicen, y es lo que se compara porque es lo que se lee.
 */
/**
 * Los nombres de las paradas de un día, en orden.
 *
 * Con `?.` en cada paso por lo mismo que el resto del módulo: esto lee lo que
 * manda el servidor, y una pantalla que se rompe por un campo que falta es
 * peor que una que no dice nada.
 */
function paradasDe(itinerario: Itinerary, dia: number): string[] {
  return (
    itinerario.days
      ?.find((d) => d.number === dia)
      ?.stops?.map((p) => p.place.name) ?? []
  );
}

function consecuenciasDe(
  antes: Itinerary | null | undefined,
  despues: Itinerary,
  dia: number,
): string[] {
  const deEseDia = (it: Itinerary) =>
    (it.advice ?? []).filter((a) => a.day === dia).map((a) => a.detail);

  // Sin el itinerario de antes no hay con qué comparar. Devolver todos los
  // consejos del día sería decir que este cambio los provocó, y entre
  // atribuir de más y callar, este proyecto calla: un día con lluvia pedida
  // hace rato no se volvió lluvioso porque alguien moviera la hora de inicio.
  if (!antes) return [];

  const previos = new Set(deEseDia(antes));
  return deEseDia(despues).filter((detalle) => !previos.has(detalle));
}

/**
 * La respuesta de una revisión, lista para mostrar.
 *
 * Todo vacío significa que el día se rehizo sin que cambiara ninguna
 * restricción, que pasa y no es un error: pedir lo que el día ya cumplía lo
 * deja igual. Quien llama decide si eso merece decirse.
 */
export function loQueCambio(
  revision: Revision,
  antes?: Itinerary | null,
  dia?: number,
): LoQueCambio {
  const cambios = Object.entries(revision.applied ?? {}).map(([clave, valor]) =>
    (COMO_SE_DICE[clave] ?? (() => `${clave}: ${valor}`))(valor),
  );

  const antesDelDia = antes && dia ? paradasDe(antes, dia) : null;
  const despuesDelDia =
    dia && revision.itinerary ? paradasDe(revision.itinerary, dia) : [];
  const yaEstaban = new Set(antesDelDia ?? []);

  return {
    cambios,
    quitadas: revision.removed ?? [],
    // Sin el día de antes no se puede saber qué es nuevo, y llamar nuevas a
    // todas las paradas sería decir que el cambio rehízo el día entero.
    entraron: antesDelDia
      ? [...new Set(despuesDelDia.filter((n) => !yaEstaban.has(n)))]
      : [],
    // Los dos dicen lo mismo desde dos sitios —"no supe qué hacer con esto"—
    // y separarlos en pantalla obligaría a explicar la diferencia, que no le
    // importa a nadie que esté mirando su itinerario.
    avisos: [...(revision.unmapped ?? []), ...(revision.notes ?? [])],
    // Sin el itinerario de antes no hay con qué comparar, y enseñar todos los
    // consejos del día sería decir que este cambio los provocó.
    consecuencias:
      dia && revision.itinerary
        ? consecuenciasDe(antes, revision.itinerary, dia)
        : [],
  };
}

/** Si la revisión tiene algo que contar. */
export function dijoAlgo(cambio: LoQueCambio): boolean {
  return (
    cambio.cambios.length > 0 ||
    cambio.quitadas.length > 0 ||
    cambio.avisos.length > 0 ||
    cambio.entraron.length > 0 ||
    cambio.consecuencias.length > 0
  );
}
