/**
 * Pruebas del interruptor de tema.
 *
 * El bug que justifica estas pruebas: el atributo se escribia traducido
 * —data-theme="claro"— y globals.css selecciona [data-theme="light"], asi que
 * el interruptor cambiaba de estado y la pagina no cambiaba de color. Nada lo
 * habria delatado salvo mirar la pantalla.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Tema from "./Tema";
import { CLAVE_TEMA, SCRIPT_TEMA } from "@/lib/tema";

const boton = (nombre: RegExp) => screen.getByRole("button", { name: nombre });

describe("Tema", () => {
  it("arranca siguiendo al sistema", () => {
    render(<Tema />);

    expect(boton(/seguir al sistema/i)).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("escribe en el atributo el valor que entiende el CSS y no su nombre", async () => {
    const usuario = userEvent.setup();
    render(<Tema />);

    await usuario.click(boton(/tema oscuro/i));

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    await usuario.click(boton(/tema claro/i));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
  });

  it("guarda la eleccion con el mismo valor", async () => {
    const usuario = userEvent.setup();
    render(<Tema />);

    await usuario.click(boton(/tema oscuro/i));

    expect(window.localStorage.getItem(CLAVE_TEMA)).toBe("dark");
  });

  it("volver al sistema retira el atributo en vez de fijar un color", async () => {
    const usuario = userEvent.setup();
    render(<Tema />);

    await usuario.click(boton(/tema oscuro/i));
    await usuario.click(boton(/seguir al sistema/i));

    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });

  it("lo elegido antes se lee al montar", () => {
    window.localStorage.setItem(CLAVE_TEMA, "dark");

    render(<Tema />);

    expect(boton(/tema oscuro/i)).toHaveAttribute("aria-pressed", "true");
  });

  it("un valor guardado que no reconoce se ignora", () => {
    window.localStorage.setItem(CLAVE_TEMA, "claro");

    render(<Tema />);

    expect(boton(/seguir al sistema/i)).toHaveAttribute("aria-pressed", "true");
  });

  it("el script del <head> escribe los mismos valores que el interruptor", () => {
    /* Son dos caminos distintos al mismo atributo —uno corre antes de la
       primera pintura y el otro en React— y si se separan vuelve el destello
       al cargar. */
    expect(SCRIPT_TEMA).toContain('"light"');
    expect(SCRIPT_TEMA).toContain('"dark"');
    expect(SCRIPT_TEMA).not.toContain("claro");
    expect(SCRIPT_TEMA).not.toContain("oscuro");
  });
});
