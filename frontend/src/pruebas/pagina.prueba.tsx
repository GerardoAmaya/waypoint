/**
 * Pruebas de la pagina, que es donde vive el estado que se comparte.
 *
 * **La que importa es la del texto que sobrevive.** El compositor se desmonta
 * en cuanto llega el plan, y mientras el texto vivia dentro de el, volver con
 * "Empezar de nuevo" te devolvia la peticion de ejemplo donde estaba la tuya.
 * Es exactamente la clase de bug que ninguna prueba de componente suelto ve:
 * los dos componentes estaban bien, lo que estaba mal era de quien era el
 * dato.
 *
 * El mapa se sustituye por un hueco: Leaflet toca window al importarse y mide
 * elementos que en jsdom no tienen tamaño. Lo que se prueba aca es el estado
 * de la pantalla, no el mapa.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Home from "@/app/page";
import { dia, lugar, parada } from "@/pruebas/datos";
import type { Itinerary, PlanEvent } from "@/lib/types";

vi.mock("@/components/Mapa", () => ({
  default: () => <div data-testid="mapa" />,
}));

const ITINERARIO: Itinerary = {
  days: [
    dia({
      stops: [
        parada({ place: lugar({ name: "Museo de Arte" }) }),
        parada({
          place: lugar({ name: "Cerro Verde", category: "nature" }),
          arrival: "12:30:00",
          departure: "14:15:00",
        }),
      ],
    }),
  ],
  violations: [],
  advice: [],
  satisfies_all_constraints: true,
  total_stops: 2,
  unused_candidates: 4,
  travel: {
    source: "estimated",
    cached: 0,
    fetched: 0,
    estimated: 2,
    real_ratio: 0,
    requests: 0,
    reason: null,
    quota_remaining: null,
  },
};

const eventos: PlanEvent[] = [
  {
    phase: "interpretation",
    data: {
      area: {
        name: "Suchitoto",
        lat: 13.9,
        lon: -89.0,
        radius_m: 15000,
        source: "zone",
        photo: null,
      },
      constraints: null,
      unmapped: [],
      notes: [],
    },
  },
  { phase: "plan", data: ITINERARIO },
];

vi.mock("@/lib/api", () => ({
  API: "http://localhost:8100",
  fetchField: vi.fn().mockResolvedValue([]),
  streamPlan: vi.fn(async function* () {
    for (const evento of eventos) yield evento;
  }),
  reviseDay: vi.fn(),
}));

const caja = () => screen.getByRole("textbox", { name: /viaje/i });

describe("Home", () => {
  it("lo que escribiste sigue ahí después de volver del itinerario", async () => {
    const usuario = userEvent.setup();
    render(<Home />);

    await usuario.clear(caja());
    await usuario.type(caja(), "Un día en Suchitoto caminando");
    await usuario.click(screen.getByRole("button", { name: /armar el itinerario/i }));

    // El plan llego: el compositor se fue y el panel entro.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /empezar de nuevo/i })).toBeInTheDocument();
    });
    expect(screen.queryByRole("textbox", { name: /viaje/i })).toBeNull();

    await usuario.click(screen.getByRole("button", { name: /empezar de nuevo/i }));

    expect(caja()).toHaveValue("Un día en Suchitoto caminando");
  });

  it("el itinerario que llega se anuncia para quien no lo ve", async () => {
    const usuario = userEvent.setup();
    render(<Home />);

    await usuario.click(screen.getByRole("button", { name: /armar el itinerario/i }));

    await waitFor(() => {
      expect(screen.getByText(/Itinerario listo: 1 día, 2 paradas\./)).toBeInTheDocument();
    });
  });

  it("empezar de nuevo retira el itinerario y devuelve la caja", async () => {
    const usuario = userEvent.setup();
    render(<Home />);

    await usuario.click(screen.getByRole("button", { name: /armar el itinerario/i }));
    await waitFor(() => {
      expect(screen.getByText("Museo de Arte")).toBeInTheDocument();
    });

    await usuario.click(screen.getByRole("button", { name: /empezar de nuevo/i }));

    // El panel se va con animacion de salida, asi que sigue en el DOM el
    // instante siguiente al clic: se espera a que termine de irse.
    await waitFor(() => {
      expect(screen.queryByText("Museo de Arte")).toBeNull();
    });
    expect(caja()).toBeInTheDocument();
  });
});
