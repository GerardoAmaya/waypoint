/**
 * Pruebas de la caja donde se escribe el viaje.
 *
 * Lo que se prueba es lo que ya se rompio una vez: que el texto no viva aca
 * —se perdia al volver del itinerario—, que el boton no se pueda pulsar en
 * vacio, y que Enter mande y Mayus+Enter no.
 */
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Compositor, { PETICION_INICIAL } from "./Compositor";

/** El compositor no guarda su texto: quien lo monta se lo da. */
function Anfitrion({
  onSubmit = () => {},
  inicial = PETICION_INICIAL,
}: {
  onSubmit?: (mensaje: string) => void;
  inicial?: string;
}) {
  const [texto, setTexto] = useState(inicial);
  return (
    <Compositor
      fase="quieto"
      error={null}
      texto={texto}
      onTextoChange={setTexto}
      onSubmit={onSubmit}
    />
  );
}

const caja = () => screen.getByRole("textbox");
const armar = () => screen.getByRole("button", { name: /armar el itinerario/i });

describe("Compositor", () => {
  it("arranca con una peticion escrita y el boton disponible", () => {
    render(<Anfitrion />);

    expect(caja()).toHaveValue(PETICION_INICIAL);
    expect(armar()).toBeEnabled();
  });

  it("no se puede armar nada con la caja vacia", async () => {
    const usuario = userEvent.setup();
    render(<Anfitrion inicial="" />);

    expect(armar()).toBeDisabled();

    await usuario.type(caja(), "un dia en Suchitoto");

    expect(armar()).toBeEnabled();
  });

  it("no manda espacios en blanco por texto", async () => {
    const usuario = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Anfitrion inicial="" onSubmit={onSubmit} />);

    await usuario.type(caja(), "   ");
    await usuario.click(armar());

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("recorta el texto antes de mandarlo", async () => {
    const usuario = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Anfitrion inicial="" onSubmit={onSubmit} />);

    await usuario.type(caja(), "  dos dias por el occidente  ");
    await usuario.click(armar());

    expect(onSubmit).toHaveBeenCalledWith("dos dias por el occidente");
  });

  it("un ejemplo se copia a la caja al pulsarlo", async () => {
    const usuario = userEvent.setup();
    render(<Anfitrion />);

    const ejemplo = screen.getByRole("button", { name: /Ruta de las Flores/i });
    await usuario.click(ejemplo);

    expect(caja()).toHaveValue("Tres días por la Ruta de las Flores, odio madrugar");
  });

  it("Enter manda y Mayus+Enter escribe una linea", async () => {
    const usuario = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Anfitrion inicial="" onSubmit={onSubmit} />);

    await usuario.click(caja());
    await usuario.keyboard("un dia{Shift>}{Enter}{/Shift}caminando");

    expect(onSubmit).not.toHaveBeenCalled();
    expect(caja()).toHaveValue("un dia\ncaminando");

    await usuario.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("un dia\ncaminando");
  });

  it("mientras trabaja no se puede escribir ni volver a mandar", () => {
    render(
      <Compositor
        fase="midiendo"
        error={null}
        texto="dos dias"
        onTextoChange={() => {}}
        onSubmit={() => {}}
      />,
    );

    expect(caja()).toBeDisabled();
    expect(armar()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/Midiendo las rutas/i);
  });

  it("con error a la vista, los ejemplos se retiran", () => {
    render(
      <Compositor
        fase="quieto"
        error="No encontré esa zona"
        texto="algo"
        onTextoChange={() => {}}
        onSubmit={() => {}}
      />,
    );

    expect(screen.getByText("No encontré esa zona")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /Ruta de las Flores/i })).toBeNull();
  });
});
