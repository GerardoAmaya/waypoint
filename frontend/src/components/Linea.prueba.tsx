/**
 * Pruebas de la linea de tiempo del dia.
 *
 * Todo lo que se comprueba aca se rompio de verdad alguna vez: el dia que
 * vuelve al punto de partida repetia clave de React con el mismo lugar dos
 * veces, y decia "llega 09:00, hasta las 09:00" en las paradas que no duran
 * nada, que se lee como un error de calculo.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Linea from "./Linea";
import { dia, lugar, parada } from "@/pruebas/datos";

const hotel = lugar({ name: "Hotel Barceló", category: "lodging" });

/** Un dia que sale del hotel, visita y vuelve: el mismo lugar dos veces. */
const idaYVuelta = dia({
  stops: [
    parada({ place: hotel, arrival: "10:00:00", departure: "10:00:00" }),
    parada({
      place: lugar({ name: "Museo de Arte" }),
      arrival: "10:09:00",
      departure: "12:09:00",
    }),
    parada({
      place: lugar({ name: "El Xolo Maíz", category: "food" }),
      arrival: "12:19:00",
      departure: "13:49:00",
      meal: "lunch",
    }),
    parada({ place: hotel, arrival: "14:00:00", departure: "14:00:00" }),
  ],
});

function pinta(propios = {}) {
  return render(
    <Linea
      day={idaYVuelta}
      advice={[]}
      violations={[]}
      mode="driving"
      selectedStop={null}
      onSelectStop={() => {}}
      {...propios}
    />,
  );
}

describe("Linea", () => {
  it("el mismo lugar dos veces se pinta dos veces", () => {
    pinta();

    expect(screen.getAllByText("Hotel Barceló")).toHaveLength(2);
  });

  it("distingue la salida del regreso en vez de parecer un duplicado", () => {
    pinta();

    expect(screen.getByText(/^Salida ·/)).toBeInTheDocument();
    expect(screen.getByText("Regreso al punto de partida")).toBeInTheDocument();
  });

  it("no dice 'hasta las' en una parada que no dura nada", () => {
    pinta();

    // El almuerzo si lo dice; la salida y el regreso, no.
    expect(screen.getAllByText(/hasta las/)).toHaveLength(2);
  });

  it("la comida se nombra por lo que es y no por su categoria", () => {
    pinta();

    expect(screen.getByText(/^Almuerzo/)).toBeInTheDocument();
    expect(screen.queryByText(/^Comida/)).toBeNull();
  });

  it("al pulsar una parada la elige, y al volver a pulsarla la suelta", async () => {
    const usuario = userEvent.setup();
    const onSelectStop = vi.fn();
    const { unmount } = pinta({ onSelectStop });

    await usuario.click(screen.getByRole("button", { name: /Museo de Arte/ }));
    expect(onSelectStop).toHaveBeenCalledWith(idaYVuelta.stops[1].place.id);

    unmount();
    onSelectStop.mockClear();
    pinta({ onSelectStop, selectedStop: idaYVuelta.stops[1].place.id });

    await usuario.click(screen.getByRole("button", { name: /Museo de Arte/ }));
    expect(onSelectStop).toHaveBeenCalledWith(null);
  });

  it("el icono del traslado sigue al modo del dia", () => {
    const { container } = pinta({ mode: "walking" });

    // Los iconos de Font Awesome llevan su nombre en data-icon.
    expect(container.querySelector('[data-icon="person-walking"]')).not.toBeNull();
    expect(container.querySelector('[data-icon="car-side"]')).toBeNull();
  });
});
