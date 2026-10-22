/**
 * Los itinerarios que armaste, para poder volver a ellos.
 *
 * Hasta aca un plan se perdia al cerrar la pestaña, salvo que uno se acordara
 * de copiar el enlace. Y era una perdida tonta: **el servidor ya guarda todos
 * los itinerarios**, porque eso es lo que hacen los codigos de compartir. Lo
 * unico que faltaba era que el navegador recordara cuales fueron tuyos.
 *
 * Por eso aca no se guarda contenido sino punteros: el codigo, y lo justo para
 * reconocer el plan en una lista sin tener que pedirlo. Si alguien limpia el
 * navegador pierde la lista, no los itinerarios; si todavia tiene el enlace,
 * el plan sigue ahi.
 *
 * **Se recuerda lo que vos armaste, no lo que abriste de un enlace ajeno.** Un
 * enlace que te mandaron ya lo tenes —esta en el mensaje donde te llego—; un
 * plan que armaste y cerraste no esta en ningun lado. La perdida que esto
 * arregla es la segunda.
 */

/** La clave sigue la convencion de CLAVE_TEMA en lib/tema.ts. */
export const CLAVE_RECIENTES = "waypoint-recientes";

/**
 * Cuantos se recuerdan.
 *
 * La pantalla de entrada ya tiene la caja de texto y tres ejemplos; una lista
 * larga la convierte en un panel de administracion. Cinco entran sin empujar
 * nada y cubren una sesion de pruebas.
 */
export const CUANTOS = 5;

export interface Reciente {
  codigo: string;
  /** Como se llama en la cabecera: "Suchitoto", "Ruta de las Flores". */
  zona: string;
  dias: number;
  paradas: number;
  /** Cuando se armo, en ISO. Para ordenar y para decir "hace dos dias". */
  guardado: string;
}

/**
 * Valida una entrada venida de localStorage.
 *
 * **No es paranoia: el contenido de localStorage es entrada externa.** Puede
 * venir de una version anterior de este mismo codigo con otros campos, de otra
 * pestaña a medio escribir, o de alguien que lo edito a mano. Una lista que se
 * renderiza con `reciente.zona.length` revienta la pantalla de entrada entera
 * —lo primero que ve cualquiera— por un dato que no controlamos.
 */
function valida(valor: unknown): valor is Reciente {
  if (typeof valor !== "object" || valor === null) return false;
  const r = valor as Record<string, unknown>;
  return (
    typeof r.codigo === "string" &&
    r.codigo.length > 0 &&
    typeof r.zona === "string" &&
    typeof r.dias === "number" &&
    Number.isFinite(r.dias) &&
    typeof r.paradas === "number" &&
    Number.isFinite(r.paradas) &&
    typeof r.guardado === "string"
  );
}

/**
 * Los itinerarios recordados, del mas nuevo al mas viejo.
 *
 * Nunca lanza. localStorage **tira excepcion** —no devuelve vacio— cuando el
 * navegador bloquea el almacenamiento, que es el caso de una ventana privada
 * con cookies de terceros apagadas. Es la misma razon por la que lib/tema.ts
 * envuelve sus accesos.
 */
export function leer(): Reciente[] {
  try {
    const crudo = localStorage.getItem(CLAVE_RECIENTES);
    if (!crudo) return [];
    const datos: unknown = JSON.parse(crudo);
    if (!Array.isArray(datos)) return [];
    // Se descartan las entradas rotas en vez de la lista entera: una sola
    // malformada no tiene por que borrar las otras cuatro.
    return datos.filter(valida).slice(0, CUANTOS);
  } catch {
    return [];
  }
}

function escribir(lista: Reciente[]): void {
  try {
    localStorage.setItem(CLAVE_RECIENTES, JSON.stringify(lista));
  } catch {
    // Sin almacenamiento, la lista no se recuerda y el resto sigue andando.
  }
}

/**
 * Recuerda un itinerario recien armado.
 *
 * Si el codigo ya estaba, sube al principio en vez de duplicarse: revisar un
 * dia vuelve a emitir el plan, y sin esto la lista se llenaria de copias del
 * mismo viaje.
 */
export function recordar(nuevo: Reciente): void {
  const resto = leer().filter((r) => r.codigo !== nuevo.codigo);
  escribir([nuevo, ...resto].slice(0, CUANTOS));
}

/**
 * Olvida uno.
 *
 * Lo usa el boton de quitar y tambien la apertura fallida: si el servidor ya
 * no tiene ese itinerario, dejarlo en la lista es ofrecer una puerta que no
 * abre.
 */
export function olvidar(codigo: string): void {
  escribir(leer().filter((r) => r.codigo !== codigo));
}
