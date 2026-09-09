/**
 * El tema: preferencia guardada, preferencia del sistema, y el atributo que
 * decide.
 *
 * Tres estados y no dos. "Sistema" tiene que ser un destino y no solo el punto
 * de partida: quien cambia el tema del telefono al atardecer espera que la
 * pagina lo siga, y un interruptor de dos posiciones deja al usuario clavado
 * en lo que eligio una vez y sin forma de volver.
 *
 * Se expone como almacen externo (suscribir/leer) y no como estado de React
 * porque eso es lo que es: vive en localStorage, lo puede cambiar otra pestana,
 * y React solo lo observa. Con useSyncExternalStore el primer render del
 * servidor sale con "sistema" sin provocar un desajuste de hidratacion, y de
 * paso el tema queda sincronizado entre pestanas.
 */

/**
 * Los valores son los de la plataforma —light y dark— y no su traduccion.
 *
 * La primera version usaba "claro" y "oscuro" tambien en el atributo, y el
 * interruptor no hacia nada: globals.css selecciona [data-theme="light"], que
 * es el valor que entienden color-scheme y prefers-color-scheme. Traducir aca
 * obligaba a mantener un diccionario entre el estado y el CSS, y ese
 * diccionario es justo lo que se rompio. Los nombres en castellano viven en la
 * interfaz, que es donde se leen.
 */
export type Tema = "sistema" | "light" | "dark";

export const CLAVE_TEMA = "waypoint-tema";

/** localStorage no avisa a la pestana que escribe, solo a las demas. */
const EVENTO_LOCAL = "waypoint:tema";

/**
 * Se ejecuta en el <head>, antes de la primera pintura.
 *
 * Sin esto la pagina sale con el tema por defecto y salta al elegido cuando
 * React hidrata: un destello blanco en cada carga para quien eligio claro
 * teniendo el sistema en oscuro. Es la razon por la que este script va inline y
 * bloqueando en vez de en un componente.
 *
 * Va envuelto en try porque localStorage tira excepcion —no devuelve vacio— en
 * Safari con las cookies de terceros bloqueadas dentro de un iframe.
 */
export const SCRIPT_TEMA = `try{var t=localStorage.getItem("${CLAVE_TEMA}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export function leerTema(): Tema {
  try {
    const guardado = localStorage.getItem(CLAVE_TEMA);
    if (guardado === "light" || guardado === "dark") return guardado;
  } catch {
    /* almacenamiento bloqueado: se cae a la preferencia del sistema */
  }
  return "sistema";
}

/** En el servidor no hay preferencia que leer; la resuelve el CSS. */
export function leerTemaEnServidor(): Tema {
  return "sistema";
}

export function suscribirTema(avisar: () => void): () => void {
  window.addEventListener("storage", avisar);
  window.addEventListener(EVENTO_LOCAL, avisar);
  return () => {
    window.removeEventListener("storage", avisar);
    window.removeEventListener(EVENTO_LOCAL, avisar);
  };
}

export function aplicarTema(tema: Tema): void {
  const raiz = document.documentElement;

  if (tema === "sistema") {
    delete raiz.dataset.theme;
  } else {
    raiz.dataset.theme = tema;
  }

  try {
    if (tema === "sistema") localStorage.removeItem(CLAVE_TEMA);
    else localStorage.setItem(CLAVE_TEMA, tema);
  } catch {
    /* el tema se aplica igual, solo no sobrevive a la recarga */
  }

  window.dispatchEvent(new Event(EVENTO_LOCAL));
}
