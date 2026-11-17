/**
 * Pruebas del lector de colores del servidor.
 *
 * Lee el `globals.css` de verdad a propósito: lo que puede romperse no es el
 * parseo, es el contrato —que los tokens que la tarjeta pide sigan existiendo
 * y sigan siendo colores—. Un `--verde` renombrado tiene que fallar aquí y no
 * en el chat de alguien, que es donde se vería si no.
 */

import { describe, expect, it } from "vitest";

import { material } from "./paleta-servidor";

const ES_COLOR = /^#[0-9a-f]{3,8}$/i;

describe("material", () => {
  it("lee un material crudo del CSS", () => {
    expect(material("verde")).toMatch(ES_COLOR);
    expect(material("basalto")).toMatch(ES_COLOR);
  });

  it("sigue la referencia de un nombre con significado", () => {
    // `--cat-nature: var(--verde)` es la forma normal de escribirlo en este
    // proyecto. Sin resolverla se devolvería la cadena "var(--verde)", que
    // Satori pinta como nada.
    expect(material("cat-nature")).toBe(material("verde"));
    expect(material("cat-food")).toBe(material("cafe"));
  });

  it("todos los colores que usa la tarjeta resuelven a un color", () => {
    for (const token of [
      "cafe",
      "verde",
      "ocre",
      "anil-claro",
      "acero-claro",
      "basalto",
      "basalto-borde",
      "niebla",
      "acero",
    ]) {
      expect(material(token), `--${token} no resolvió a un color`).toMatch(ES_COLOR);
    }
  });

  it("toma la definición del tema oscuro, que es el de la tarjeta", () => {
    // --cat-culture es var(--ocre) en el tema base y var(--ocre-honda) en el
    // claro. La tarjeta es oscura, así que le toca el primero.
    expect(material("cat-culture")).toBe(material("ocre"));
  });

  it("un token que no existe no deja un hueco sin pintar", () => {
    expect(material("no-existe-este-token")).toMatch(ES_COLOR);
  });

  it("una cadena de referencias demasiado larga se corta", () => {
    // No pasa con el CSS de hoy; es el seguro contra un token que se apunte a
    // sí mismo, que colgaría la generación de la imagen en vez de fallar.
    expect(material("verde", 0)).toMatch(ES_COLOR);
  });
});
