/**
 * El dia del itinerario como archivo de calendario.
 *
 * Hasta aca el plan vivia en la pestaña: se veia, se compartia por enlace, y
 * nada mas. Un itinerario con horas es, literalmente, una agenda; bajarlo al
 * calendario es lo que lo vuelve utilizable el dia del viaje, con las alarmas
 * y la ubicacion que el telefono ya sabe manejar.
 *
 * **Solo tiene sentido con fecha.** Un itinerario sin fecha no tiene eventos
 * posibles, y es la misma regla que ya siguen el clima y la cabecera del dia.
 *
 * Se arma en el navegador y no en el servidor: son unas lineas de texto, el
 * dato ya esta en pantalla, y una ida y vuelta mas para formatear lo que ya
 * tenemos seria pagar latencia por nada.
 */

import type { Day, Stop } from "./types";

/**
 * El huso de El Salvador, fijo.
 *
 * El pais no cambia la hora y esta en -06:00 todo el año, que es el mismo
 * supuesto que hace el backend en core/reloj.py. Se declara un VTIMEZONE en
 * vez de escribir horas flotantes porque flotante significa "la hora local de
 * quien mire": alguien que planifica el viaje desde Madrid veria las paradas
 * siete horas corridas.
 */
export const HUSO = "America/El_Salvador";

const VTIMEZONE = [
  "BEGIN:VTIMEZONE",
  `TZID:${HUSO}`,
  "BEGIN:STANDARD",
  "DTSTART:19700101T000000",
  "TZOFFSETFROM:-0600",
  "TZOFFSETTO:-0600",
  "TZNAME:CST",
  "END:STANDARD",
  "END:VTIMEZONE",
];

/**
 * Escapa un texto para un campo de iCalendar.
 *
 * **Hace falta de verdad y no por prolijidad.** En el catalogo hay "La
 * Puntilla, Zona de Restaurantes": sin escapar, esa coma parte el valor en dos
 * y el evento llega al calendario con el nombre cortado o el archivo
 * directamente no se importa. El orden importa —la barra primero— o se
 * escaparian las barras que uno mismo acaba de poner.
 */
export function escapar(texto: string): string {
  return texto
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

/**
 * Parte una linea larga como manda el formato.
 *
 * iCalendar limita la linea a 75 octetos y continua con un espacio al
 * principio de la siguiente. Se cuenta en octetos y no en caracteres porque
 * una "ñ" ocupa dos: contando caracteres, un nombre con acentos se pasa del
 * limite sin que se note.
 */
export function plegar(linea: string): string {
  const bytes = new TextEncoder().encode(linea);
  if (bytes.length <= 75) return linea;

  const trozos: string[] = [];
  let actual = "";
  let largo = 0;
  // El primer trozo lleva 75 octetos; los siguientes 74, porque el espacio de
  // continuacion ocupa uno.
  let techo = 75;

  for (const caracter of linea) {
    const pesa = new TextEncoder().encode(caracter).length;
    if (largo + pesa > techo) {
      trozos.push(actual);
      actual = "";
      largo = 0;
      techo = 74;
    }
    actual += caracter;
    largo += pesa;
  }
  trozos.push(actual);

  return trozos.join("\r\n ");
}

/** "2026-10-20" y "09:00:00" como los quiere el formato: 20261020T090000. */
function sello(fecha: string, hora: string): string {
  return `${fecha.replace(/-/g, "")}T${hora.replace(/:/g, "").slice(0, 6)}`;
}

/** Lo que se lee bajo el titulo del evento. */
function descripcion(parada: Stop, etiqueta: string): string {
  const partes = [etiqueta];
  if (parada.travel_km_from_previous > 0) {
    partes.push(
      `${parada.travel_km_from_previous.toFixed(1)} km desde la parada anterior`,
    );
  }
  return partes.join(" · ");
}

export interface OpcionesDelDia {
  /** Como se llama cada parada en el panel: comida, regreso, categoria. */
  etiqueta: (parada: Stop, indice: number) => string;
  /** Para el UID, que tiene que ser estable entre descargas del mismo plan. */
  codigo?: string | null;
  /** Fijo en los tests; en produccion, el reloj. */
  ahora?: Date;
}

/**
 * El dia entero como texto iCalendar, o null si el dia no tiene fecha.
 *
 * Devuelve null en vez de lanzar porque el llamador ya decide con eso si
 * ofrecer el boton: un dia sin fecha simplemente no se puede bajar.
 */
export function comoIcs(dia: Day, opciones: OpcionesDelDia): string | null {
  if (!dia.date || !dia.stops.length) return null;

  const ahora = opciones.ahora ?? new Date();
  const marca = ahora.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

  const lineas = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Waypoint//Itinerarios por El Salvador//ES",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    ...VTIMEZONE,
  ];

  dia.stops.forEach((parada, indice) => {
    // El UID identifica al evento: si alguien baja el mismo dia dos veces, el
    // calendario tiene que actualizar el evento y no duplicarlo. Por eso lleva
    // el codigo del itinerario cuando existe, y nunca la hora de descarga.
    const base = opciones.codigo ?? dia.date;
    lineas.push(
      "BEGIN:VEVENT",
      `UID:${base}-d${dia.number}-p${indice}@waypoint`,
      `DTSTAMP:${marca}`,
      `DTSTART;TZID=${HUSO}:${sello(dia.date!, parada.arrival)}`,
      `DTEND;TZID=${HUSO}:${sello(dia.date!, parada.departure)}`,
      `SUMMARY:${escapar(parada.place.name)}`,
      `DESCRIPTION:${escapar(descripcion(parada, opciones.etiqueta(parada, indice)))}`,
      `LOCATION:${parada.place.lat},${parada.place.lon}`,
      `GEO:${parada.place.lat};${parada.place.lon}`,
      "END:VEVENT",
    );
  });

  lineas.push("END:VCALENDAR");

  // CRLF, que el formato exige y algunos lectores hacen cumplir.
  return lineas.map(plegar).join("\r\n") + "\r\n";
}

/** Un nombre de archivo que se entienda en la carpeta de descargas. */
export function nombreDelArchivo(zona: string, dia: Day): string {
  const limpio = zona
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .toLowerCase();
  return `${limpio || "itinerario"}-dia-${dia.number}.ics`;
}
