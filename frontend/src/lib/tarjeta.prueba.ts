/**
 * Pruebas de lo que dice la tarjeta del enlace compartido.
 *
 * Es el único texto del producto que se lee antes de abrirlo, y en un chat
 * donde el autor no está para corregirlo. Un "1 días" ahí vale por diez en
 * cualquier otra pantalla.
 */

import { describe, expect, it } from "vitest";

import { describir } from "./tarjeta";
import { dia, itinerario, lugar, parada } from "@/pruebas/datos";
import type { Interpretation } from "./types";

const zona = (name: string | null): Interpretation =>
  ({
    area: name ? { name, lat: 13.9, lon: -89.5, radius_m: 15000, source: "zone", photo: null } : null,
    constraints: null,
    unmapped: [],
    notes: [],
  }) as Interpretation;

describe("describir", () => {
  it("pone la zona de título", () => {
    const it_ = itinerario({ days: [dia()] });

    expect(describir(zona("Ruta de las Flores"), it_).titulo).toBe(
      "Ruta de las Flores",
    );
  });

  it("sin zona no deja la tarjeta sin título", () => {
    // Un itinerario puede salir de un punto del catálogo y no de una zona del
    // nomenclátor. La tarjeta se publica igual.
    const it_ = itinerario({ days: [dia()] });

    expect(describir(zona(null), it_).titulo).toBe("Un itinerario por El Salvador");
    expect(describir(null, it_).titulo).toBe("Un itinerario por El Salvador");
  });

  it("concuerda el singular", () => {
    // "1 días" en una tarjeta que se lee en un chat, sin nadie que lo corrija.
    const uno = itinerario({ days: [dia({ travel_km: 12 })], total_stops: 1 });

    expect(describir(null, uno).resumen).toBe("1 día · 1 parada · 12 km");
  });

  it("suma los kilómetros de todos los días", () => {
    // El itinerario no trae un total: travel_km es por día.
    const dos = itinerario({
      days: [dia({ number: 1, travel_km: 42.1 }), dia({ number: 2, travel_km: 31.4 })],
      total_stops: 12,
    });

    expect(describir(null, dos).resumen).toBe("2 días · 12 paradas · 74 km");
  });

  it("da el rango de fechas del viaje", () => {
    const dos = itinerario({
      days: [dia({ number: 1, date: "2026-11-14" }), dia({ number: 2, date: "2026-11-16" })],
    });

    expect(describir(null, dos).fechas).toBe("14 nov – 16 nov");
  });

  it("un viaje de un día no es un rango", () => {
    // "14 nov – 14 nov" se lee como un error de formato, no como un día.
    const uno = itinerario({ days: [dia({ date: "2026-11-14" })] });

    expect(describir(null, uno).fechas).toBe("14 nov");
  });

  it("sin fechas no inventa ninguna", () => {
    const sin = itinerario({ days: [dia({ date: null })] });

    expect(describir(null, sin).fechas).toBeNull();
  });

  it("cada día lleva sus paradas en orden, por categoría", () => {
    // Es lo que dibuja la tira de puntos: cuántas paradas tiene cada día y de
    // qué tipo. Sin esto la tarjeta sería la misma para todos los viajes.
    const con = itinerario({
      days: [
        dia({
          number: 1,
          date: "2026-11-14",
          stops: [
            parada({ place: lugar({ category: "lodging" }) }),
            parada({ place: lugar({ category: "nature" }) }),
            parada({ place: lugar({ category: "food" }) }),
          ],
        }),
      ],
    });

    expect(describir(null, con).dias).toEqual([
      { etiqueta: "14 nov", paradas: ["lodging", "nature", "food"] },
    ]);
  });

  it("un día sin fecha se nombra por su número", () => {
    const sin = itinerario({ days: [dia({ number: 2, date: null, stops: [parada()] })] });

    expect(describir(null, sin).dias[0].etiqueta).toBe("Día 2");
  });
});
