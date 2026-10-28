/**
 * Pruebas de la cabecera del panel.
 *
 * Lo que se prueba es el aviso de medición, que existe por un hueco concreto:
 * el indicador de progreso vivía en el compositor, y el compositor se
 * desmonta en cuanto llega el borrador. Desaparecía justo cuando empieza a
 * hacer falta, y dos segundos después el mapa cambia las rectas por el trazo
 * por carretera sin que nada lo hubiera anunciado.
 */
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import Panel from "./Panel";
import { dia, itinerario, lugar, parada } from "@/pruebas/datos";

const ITINERARIO = itinerario({
  days: [dia({ stops: [parada({ place: lugar({ name: "Museo de Arte" }) })] })],
});

function pinta(
  midiendo: boolean,
  itinerario = ITINERARIO,
  extra: Partial<ComponentProps<typeof Panel>> = {},
) {
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
      loDicho={null}
      onDeshacer={null}
      midiendo={midiendo}
      {...extra}
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
    // Por `pinta` y no armando otro <Panel> a mano: la copia de la lista de
    // props se queda vieja en cuanto el componente aprende uno nuevo, y lo
    // que falla entonces es la compilacion de un test que no cambio.
    pinta(false, {
      ...ITINERARIO,
      travel: { ...ITINERARIO.travel, reason: "no_quota" },
    });

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

describe("lo que contesta una revisión", () => {
  const dicho = {
    cambios: ["Empieza a las 07:00", "Máximo 4 paradas"],
    quitadas: ["Montemilia", "Palm Plaza"],
    avisos: [],
    consecuencias: [],
  };

  it("dice qué entendió y qué paradas sacó", () => {
    // El motor nombra las paradas que quita una por una. Decir «saqué 4» sin
    // cuáles obliga a comparar el antes y el después, y el antes ya no está.
    pinta(false, ITINERARIO, { loDicho: dicho });

    expect(screen.getByText("Empieza a las 07:00")).toBeInTheDocument();
    expect(screen.getByText("Máximo 4 paradas")).toBeInTheDocument();
    expect(screen.getByText(/Saqué Montemilia y Palm Plaza/)).toBeInTheDocument();
  });

  it("avisa de lo que no supo usar", () => {
    pinta(false, ITINERARIO, {
      loDicho: { cambios: [], quitadas: [], avisos: ["el cerro ese"], consecuencias: [] },
    });

    expect(screen.getByText(/No supe qué hacer con: el cerro ese/)).toBeInTheDocument();
  });

  it("un día que se rehízo sin cambiar nada no inventa una respuesta", () => {
    const { container } = pinta(false, ITINERARIO, {
      loDicho: { cambios: [], quitadas: [], avisos: [], consecuencias: [] },
    });

    expect(container.querySelector(".border-acento")).toBeNull();
  });

  it("sin revisiones no hay nada que contar", () => {
    pinta(false);

    expect(screen.queryByText(/No supe qué hacer con/)).toBeNull();
  });
});

describe("volver al itinerario anterior", () => {
  it("no ofrece la salida mientras no exista", () => {
    // Un botón apagado desde el primer segundo enseña una puerta que todavía
    // no está y hace preguntarse qué falta para abrirla.
    pinta(false, ITINERARIO, { onDeshacer: null });

    expect(screen.queryByRole("button", { name: /Volver al anterior/i })).toBeNull();
  });

  it("aparece en cuanto hay adónde volver, y llama al volver", async () => {
    const volver = vi.fn();
    pinta(false, ITINERARIO, { onDeshacer: volver });

    await userEvent.click(
      screen.getByRole("button", { name: /Volver al anterior/i }),
    );

    expect(volver).toHaveBeenCalledOnce();
  });

  it("no se puede volver mientras el día se está rehaciendo", () => {
    // Deshacer a mitad de una revisión dejaría el resultado pisando el plan
    // al que se acaba de volver.
    pinta(false, ITINERARIO, { onDeshacer: () => {}, revising: true });

    expect(screen.getByRole("button", { name: /Volver al anterior/i })).toBeDisabled();
  });
});

describe("lo que el cambio provocó", () => {
  it("dice por qué lo que pediste no cupo, donde lo pediste", () => {
    /*
      El caso reportado desde la demo: «agregá desayuno» a un día que empieza
      a las 10:00. La restricción se aplica —arriba se lee «Con desayuno»— y
      el desayuno no cabe, porque su franja cerró a las 09:30. El motor lo
      explicaba al final de la lista de paradas, debajo de siete, o sea fuera
      de pantalla, mientras aquí arriba la revisión declaraba el éxito.
    */
    pinta(false, ITINERARIO, {
      loDicho: {
        cambios: ["Con desayuno"],
        quitadas: [],
        avisos: [],
        consecuencias: [
          "Pediste desayuno y este día no llega: empieza a las 10:00, después de que cierra la franja de desayuno a las 09:30",
        ],
      },
    });

    expect(screen.getByText("Con desayuno")).toBeInTheDocument();
    expect(
      screen.getByText(/después de que cierra la franja de desayuno a las 09:30/),
    ).toBeInTheDocument();
  });

  it("una consecuencia sola ya merece abrir la respuesta", () => {
    // Un cambio puede no aplicar ninguna restricción nueva y aun así tener
    // algo que contar.
    pinta(false, ITINERARIO, {
      loDicho: {
        cambios: [],
        quitadas: [],
        avisos: [],
        consecuencias: ["Llevá almuerzo: el comedor más cercano suma 14 km"],
      },
    });

    expect(screen.getByText(/Llevá almuerzo/)).toBeInTheDocument();
  });
});
