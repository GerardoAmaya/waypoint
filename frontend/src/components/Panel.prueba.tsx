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
import { dia, itinerario, lugar, parada } from "@/pruebas/datos";

const ITINERARIO = itinerario({
  days: [dia({ stops: [parada({ place: lugar({ name: "Museo de Arte" }) })] })],
});

function pinta(midiendo: boolean, itinerario = ITINERARIO) {
  return render(
    <Panel
      interpretation={null}
      itinerary={itinerario}
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

    expect(
      screen.getByText(/Midiendo las rutas por carretera/i),
    ).toBeInTheDocument();
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
    expect(
      screen.getByText(/el trazo del mapa no se ve afectado/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/cupo diario de rutas/i)).toBeNull();
  });

  it("el aviso es un role=status para quien no lo ve", () => {
    pinta(true);

    expect(screen.getByRole("status")).toHaveTextContent(/Midiendo las rutas/i);
  });
});

describe("el crédito del clima", () => {
  const conClima = (source: string | null, reason: string | null) =>
    itinerario({
      days: ITINERARIO.days,
      weather: {
        source,
        reason,
        attribution: "Datos del clima de Open-Meteo (CC-BY 4.0)",
      },
    });

  it("aparece cuando hubo pronóstico, con el aviso de licencia a un clic", () => {
    /* No es decorativo: Open-Meteo es CC-BY 4.0 y atribuir es la condición de
       poder usarlo. Va pegado a la línea de las distancias para no ocupar un
       renglón propio, y el nombre lleva a la licencia, que es lo que la
       atribución tiene que dejar alcanzable. */
    pinta(false, conClima("forecast", null));

    const credito = screen.getByRole("link", { name: "Open-Meteo" });

    expect(credito).toHaveAttribute(
      "href",
      "https://open-meteo.com/en/license",
    );
    expect(
      screen.getByText(/Distancias estimadas.*clima de/),
    ).toBeInTheDocument();
  });

  it("dice por qué no hay clima para una fecha lejana", () => {
    /* Quien planifica para diciembre tiene que saber que el dato no existe
       todavía, en vez de deducir que no va a llover. */
    pinta(false, conClima(null, "fuera_de_pronostico"));

    expect(screen.getByText(/dieciséis días/)).toBeInTheDocument();
    expect(screen.queryByText(/Open-Meteo/)).not.toBeInTheDocument();
  });
});
