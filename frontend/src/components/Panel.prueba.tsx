/**
 * Pruebas de la cabecera del panel.
 *
 * Lo que se prueba es el aviso de medición, que existe por un hueco concreto:
 * el indicador de progreso vivía en el compositor, y el compositor se
 * desmonta en cuanto llega el borrador. Desaparecía justo cuando empieza a
 * hacer falta, y dos segundos después el mapa cambia las rectas por el trazo
 * por carretera sin que nada lo hubiera anunciado.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import Panel from "./Panel";
import { dia, lugar, parada } from "@/pruebas/datos";
import type { Itinerary } from "@/lib/types";

const ITINERARIO: Itinerary = {
  days: [dia({ stops: [parada({ place: lugar({ name: "Museo de Arte" }) })] })],
  violations: [],
  advice: [],
  satisfies_all_constraints: true,
  total_stops: 1,
  unused_candidates: 0,
  travel: {
    source: "estimated",
    cached: 0,
    fetched: 0,
    estimated: 1,
    real_ratio: 0,
    requests: 0,
    reason: null,
    quota_remaining: null,
  },
};

function pinta(midiendo: boolean) {
  return render(
    <Panel
      interpretation={null}
      itinerary={ITINERARIO}
      selectedDay={1}
      onSelectDay={() => {}}
      onRevise={async () => {}}
      revising={false}
      reviseError={null}
      selectedStop={null}
      onSelectStop={() => {}}
      expandido={false}
      onToggleExpandido={() => {}}
      midiendo={midiendo}
    />,
  );
}

describe("Panel", () => {
  it("mientras mide lo dice, y no da las distancias por firmes", () => {
    pinta(true);

    expect(screen.getByText(/Midiendo las rutas por carretera/i)).toBeInTheDocument();
    expect(screen.queryByText(/Distancias estimadas/i)).toBeNull();
  });

  it("al terminar cede el sitio a de dónde salieron las distancias", () => {
    pinta(false);

    expect(screen.getByText(/Distancias estimadas/i)).toBeInTheDocument();
    expect(screen.queryByText(/Midiendo las rutas/i)).toBeNull();
  });

  it("sin cupo para medir, no dice que el mapa dibuje rectas", () => {
    /*
      Los dos cupos de ORS son distintos —50 para medir, 200 para el trazo— así
      que el mapa puede estar dibujando las calles mientras las distancias son
      estimadas. La línea decía "se acabó el cupo diario de rutas, así que salen
      de la línea recta" y se leía como que las líneas del mapa eran rectas.
    */
    render(
      <Panel
        interpretation={null}
        itinerary={{
          ...ITINERARIO,
          travel: { ...ITINERARIO.travel, reason: "no_quota" },
        }}
        selectedDay={1}
        onSelectDay={() => {}}
        onRevise={async () => {}}
        revising={false}
        reviseError={null}
        selectedStop={null}
        onSelectStop={() => {}}
        expandido={false}
        onToggleExpandido={() => {}}
        midiendo={false}
      />,
    );

    expect(screen.getByText(/cupo diario para medirlas/i)).toBeInTheDocument();
    expect(screen.getByText(/el trazo del mapa no se ve afectado/i)).toBeInTheDocument();
    expect(screen.queryByText(/cupo diario de rutas/i)).toBeNull();
  });

  it("el aviso es un role=status para quien no lo ve", () => {
    pinta(true);

    expect(screen.getByRole("status")).toHaveTextContent(/Midiendo las rutas/i);
  });
});
