/**
 * Tests del dia como archivo de calendario.
 *
 * El formato iCalendar es viejo y estricto, y sus trampas no se ven mirando el
 * archivo: una coma sin escapar parte un valor en dos, una linea de mas de 75
 * octetos rompe lectores que hacen cumplir el limite, y un salto de linea que
 * no sea CRLF hace que algunos ni abran el archivo. Nada de eso falla en la
 * pantalla de quien lo genera: falla en el calendario de quien lo recibe.
 */

import { describe, expect, it } from "vitest";

import {
  comoIcs,
  escapar,
  HUSO,
  nombreDelArchivo,
  plegar,
} from "./calendario";
import type { Day, Stop } from "./types";

const AHORA = new Date("2026-10-21T23:00:00Z");

function parada(extra: Partial<Stop> & { nombre?: string } = {}): Stop {
  const { nombre, ...resto } = extra;
  return {
    place: {
      id: "p1",
      name: nombre ?? "Cerro Guazapa",
      category: "nature",
      subcategory: "peak",
      lat: 13.9022277,
      lon: -89.1136284,
      website: null,
      address: null,
      opening_hours: null,
    },
    arrival: "09:00:00",
    departure: "11:00:00",
    travel_minutes_from_previous: 0,
    travel_km_from_previous: 0,
    meal: null,
    geometry_from_previous: null,
    ...resto,
  } as Stop;
}

function dia(extra: Partial<Day> = {}): Day {
  return {
    number: 1,
    date: "2026-10-20",
    weather: null,
    stops: [parada()],
    travel_km: 0,
    start: "09:00:00",
    end: "11:00:00",
    mode: "driving",
    visits: 1,
    ...extra,
  } as Day;
}

const opciones = { etiqueta: () => "Naturaleza", ahora: AHORA };

/** Despliega las continuaciones para poder buscar propiedades enteras. */
function logicas(ics: string): string[] {
  const salida: string[] = [];
  for (const linea of ics.split("\r\n")) {
    if (linea.startsWith(" ") && salida.length) {
      salida[salida.length - 1] += linea.slice(1);
    } else if (linea) {
      salida.push(linea);
    }
  }
  return salida;
}

describe("sin fecha no hay calendario", () => {
  it("un dia sin fecha devuelve null", () => {
    /**
     * Es la misma regla que sigue la cabecera del dia: sin fecha no hay evento
     * posible. Devolver null y no lanzar deja que el panel decida con eso si
     * ofrecer el boton.
     */
    expect(comoIcs(dia({ date: null }), opciones)).toBeNull();
  });

  it("un dia sin paradas tampoco", () => {
    expect(comoIcs(dia({ stops: [] }), opciones)).toBeNull();
  });
});

describe("el formato", () => {
  it("separa las lineas con CRLF y termina con uno", () => {
    const ics = comoIcs(dia(), opciones)!;
    expect(ics.endsWith("\r\n")).toBe(true);
    expect(ics.replace(/\r\n/g, "")).not.toContain("\n");
  });

  it("abre y cierra todos los bloques", () => {
    const ics = comoIcs(dia({ stops: [parada(), parada()] }), opciones)!;
    const pila: string[] = [];
    for (const l of logicas(ics)) {
      if (l.startsWith("BEGIN:")) pila.push(l.slice(6));
      else if (l.startsWith("END:")) expect(pila.pop()).toBe(l.slice(4));
    }
    expect(pila).toEqual([]);
  });

  it("declara el huso de El Salvador en vez de horas flotantes", () => {
    /**
     * Flotante significa "la hora local de quien mire": alguien que planifica
     * el viaje desde Madrid veria las paradas siete horas corridas.
     */
    const ics = comoIcs(dia(), opciones)!;
    expect(ics).toContain(`TZID:${HUSO}`);
    expect(ics).toContain("TZOFFSETTO:-0600");
    expect(ics).toContain(`DTSTART;TZID=${HUSO}:20261020T090000`);
    expect(ics).toContain(`DTEND;TZID=${HUSO}:20261020T110000`);
  });

  it("un evento por parada, con lo que cada evento necesita", () => {
    const ics = comoIcs(dia({ stops: [parada(), parada(), parada()] }), opciones)!;
    const props = logicas(ics);

    expect(props.filter((l) => l === "BEGIN:VEVENT")).toHaveLength(3);
    for (const req of ["UID:", "DTSTAMP:", "DTSTART", "DTEND", "SUMMARY:"]) {
      expect(props.filter((l) => l.startsWith(req)).length).toBeGreaterThanOrEqual(3);
    }
  });
});

describe("el escapado", () => {
  it("una coma en el nombre no parte el valor", () => {
    /**
     * "La Puntilla, Zona de Restaurantes" esta en el catalogo. Sin escapar,
     * esa coma convierte el SUMMARY en dos valores y el evento llega al
     * calendario con el nombre cortado, o el archivo no se importa.
     */
    const ics = comoIcs(
      dia({ stops: [parada({ nombre: "La Puntilla, Zona de Restaurantes" })] }),
      opciones,
    )!;

    expect(ics).toContain("SUMMARY:La Puntilla\\, Zona de Restaurantes");
  });

  it("escapa la barra antes que lo demas", () => {
    // Al reves, se escaparian las barras que uno mismo acaba de poner.
    expect(escapar("a\\b,c")).toBe("a\\\\b\\,c");
  });

  it("escapa punto y coma y salto de linea", () => {
    expect(escapar("a;b")).toBe("a\\;b");
    expect(escapar("a\nb")).toBe("a\\nb");
  });
});

describe("el plegado de lineas", () => {
  it("deja en paz lo que entra en 75 octetos", () => {
    expect(plegar("SUMMARY:Cerro Guazapa")).toBe("SUMMARY:Cerro Guazapa");
  });

  it("parte lo largo con un espacio de continuacion", () => {
    const linea = "SUMMARY:" + "a".repeat(120);
    const plegada = plegar(linea);

    expect(plegada).toContain("\r\n ");
    for (const trozo of plegada.split("\r\n")) {
      expect(new TextEncoder().encode(trozo).length).toBeLessThanOrEqual(75);
    }
    // Lo plegado tiene que poder desplegarse sin perder nada.
    expect(plegada.split("\r\n ").join("")).toBe(linea);
  });

  it("cuenta octetos y no caracteres", () => {
    /**
     * Una "ñ" ocupa dos octetos. Contando caracteres, un nombre con acentos
     * se pasa del limite sin que se note: 70 eñes son 140 octetos.
     */
    const linea = "SUMMARY:" + "ñ".repeat(70);
    for (const trozo of plegar(linea).split("\r\n")) {
      expect(new TextEncoder().encode(trozo).length).toBeLessThanOrEqual(75);
    }
  });

  it("ninguna linea del archivo se pasa del limite", () => {
    const largo = "Mirador del Cerro de las Pavas y Centro Recreativo Municipal";
    const ics = comoIcs(dia({ stops: [parada({ nombre: largo })] }), opciones)!;

    for (const linea of ics.split("\r\n")) {
      expect(new TextEncoder().encode(linea).length).toBeLessThanOrEqual(75);
    }
  });
});

describe("el UID", () => {
  it("no cambia entre descargas del mismo dia", () => {
    /**
     * Si cambiara, bajar el mismo dia dos veces duplicaria los eventos en vez
     * de actualizarlos. Por eso no lleva la hora de descarga.
     */
    const primera = comoIcs(dia(), { ...opciones, codigo: "abc123" })!;
    const segunda = comoIcs(dia(), {
      ...opciones,
      codigo: "abc123",
      ahora: new Date("2026-11-01T10:00:00Z"),
    })!;

    const uid = (ics: string) => logicas(ics).filter((l) => l.startsWith("UID:"));
    expect(uid(primera)).toEqual(uid(segunda));
  });

  it("distingue las paradas entre si", () => {
    const ics = comoIcs(dia({ stops: [parada(), parada()] }), opciones)!;
    const uids = logicas(ics).filter((l) => l.startsWith("UID:"));

    expect(new Set(uids).size).toBe(2);
  });

  it("distingue un dia de otro", () => {
    const uno = comoIcs(dia({ number: 1 }), { ...opciones, codigo: "abc" })!;
    const dos = comoIcs(dia({ number: 2 }), { ...opciones, codigo: "abc" })!;

    expect(logicas(uno).find((l) => l.startsWith("UID:"))).not.toBe(
      logicas(dos).find((l) => l.startsWith("UID:")),
    );
  });
});

describe("lo que se lee en el evento", () => {
  it("el titulo es el nombre del lugar", () => {
    const ics = comoIcs(dia({ stops: [parada({ nombre: "Cafe Museo" })] }), opciones)!;
    expect(ics).toContain("SUMMARY:Cafe Museo");
  });

  it("la etiqueta es la misma que muestra el panel", () => {
    /**
     * Se recibe del panel en vez de recalcularla: si la lista dice "Almuerzo"
     * y el evento dijera "Comida", serian dos verdades del mismo dato.
     */
    const ics = comoIcs(dia(), { ...opciones, etiqueta: () => "Almuerzo" })!;
    expect(ics).toContain("DESCRIPTION:Almuerzo");
  });

  it("suma el traslado cuando lo hubo", () => {
    const ics = comoIcs(
      dia({ stops: [parada({ travel_km_from_previous: 6.14 })] }),
      opciones,
    )!;
    expect(logicas(ics)).toContain(
      "DESCRIPTION:Naturaleza · 6.1 km desde la parada anterior",
    );
  });

  it("lleva la ubicacion para que el telefono sepa adonde ir", () => {
    const ics = comoIcs(dia(), opciones)!;
    expect(ics).toContain("LOCATION:13.9022277,-89.1136284");
    expect(ics).toContain("GEO:13.9022277;-89.1136284");
  });
});

describe("el nombre del archivo", () => {
  it("se entiende en la carpeta de descargas", () => {
    expect(nombreDelArchivo("Suchitoto", dia())).toBe("suchitoto-dia-1.ics");
  });

  it("quita acentos y espacios", () => {
    expect(nombreDelArchivo("Concepción de Ataco", dia({ number: 2 }))).toBe(
      "concepcion-de-ataco-dia-2.ics",
    );
  });

  it("aguanta una zona sin nada aprovechable", () => {
    expect(nombreDelArchivo("—", dia())).toBe("itinerario-dia-1.ics");
  });
});
