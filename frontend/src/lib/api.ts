import type { Constraints, PlanEvent, Revision, Stop } from "./types";

export const API =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";

/**
 * Lee la respuesta de POST /plan evento por evento.
 *
 * No se usa EventSource porque solo habla GET y el mensaje del usuario va en
 * el cuerpo. Con fetch hay que partir el flujo a mano, que son quince lineas y
 * a cambio deja mandar un POST y abortar con AbortController.
 */
export async function* streamPlan(
  message: string,
  signal?: AbortSignal,
): AsyncGenerator<PlanEvent> {
  const respuesta = await fetch(`${API}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!respuesta.ok || !respuesta.body) {
    const detalle = await respuesta.text().catch(() => "");
    yield {
      phase: "error",
      data: { message: mensajeDeError(respuesta.status, detalle) },
    };
    return;
  }

  const lector = respuesta.body.pipeThrough(new TextDecoderStream()).getReader();
  let resto = "";

  try {
    while (true) {
      const { done, value } = await lector.read();
      if (done) break;

      resto += value;

      // Los eventos van separados por una linea en blanco. El ultimo trozo
      // puede venir cortado a la mitad, asi que se guarda para la vuelta
      // siguiente en vez de intentar parsearlo.
      const bloques = resto.split("\n\n");
      resto = bloques.pop() ?? "";

      for (const bloque of bloques) {
        const evento = parseEvento(bloque);
        if (evento) yield evento;
      }
    }
  } finally {
    lector.releaseLock();
  }
}

function parseEvento(bloque: string): PlanEvent | null {
  let nombre = "";
  let datos = "";

  for (const linea of bloque.split("\n")) {
    if (linea.startsWith("event: ")) nombre = linea.slice(7).trim();
    else if (linea.startsWith("data: ")) datos += linea.slice(6);
  }

  if (!nombre || !datos) return null;

  try {
    return { phase: nombre, data: JSON.parse(datos) } as PlanEvent;
  } catch {
    return null;
  }
}

function mensajeDeError(estado: number, detalle: string): string {
  if (estado === 422) {
    try {
      const cuerpo = JSON.parse(detalle);
      const primero = Array.isArray(cuerpo.detail) ? cuerpo.detail[0] : cuerpo.detail;
      if (typeof primero === "string") return primero;
      if (primero?.msg) return primero.msg;
    } catch {
      /* cae al mensaje generico */
    }
  }
  if (estado === 429) {
    // El backend manda cuanto falta y con que limite se choco; repetirlo aca
    // en generico perderia el unico dato accionable del mensaje.
    try {
      const cuerpo = JSON.parse(detalle);
      if (typeof cuerpo.detail === "string") return cuerpo.detail;
    } catch {
      /* cae al mensaje generico */
    }
    return "Demasiadas peticiones seguidas. Esperá un momento y probá de nuevo.";
  }
  if (estado === 0 || estado >= 500) {
    return "El planificador no respondió. Probá de nuevo en un momento.";
  }
  return "No se pudo armar el itinerario.";
}

export async function reviseDay(
  message: string,
  day: number,
  constraints: Constraints,
  days: { number: number; stops: Stop[] }[],
): Promise<Revision> {
  const respuesta = await fetch(`${API}/plan/revise`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      day,
      constraints,
      days: days.map((d) => ({
        number: d.number,
        // La etiqueta de comida viaja de vuelta para que el dia se reconstruya
        // igual: deducirla de la categoria y la hora acertaria casi siempre, y
        // "casi" en un dia que nadie pidio tocar es un dia que se mueve solo.
        stops: d.stops.map((s) => ({ place_id: s.place.id, meal: s.meal })),
      })),
    }),
  });

  if (!respuesta.ok) {
    const detalle = await respuesta.text().catch(() => "");
    throw new Error(mensajeDeError(respuesta.status, detalle));
  }

  return respuesta.json();
}

/** Los puntos del catalogo entero, para el estado vacio del mapa. */
export async function fetchField(): Promise<[number, number][]> {
  const respuesta = await fetch(`${API}/places/field`);
  if (!respuesta.ok) return [];
  const cuerpo = await respuesta.json();
  return cuerpo.points ?? [];
}
