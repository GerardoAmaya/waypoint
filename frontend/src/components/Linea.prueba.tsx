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
      zona="Suchitoto"
      shareCode={null}
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

  it("la cabecera cuenta visitas, no líneas de la lista", () => {
    /*
      El punto de partida aparece dos veces en la lista y no es una visita. La
      cabecera del itinerario ya lo descontaba y la del día no, así que en la
      misma pantalla se leía "8 paradas" arriba y 6 + 3 en las pestañas.
    */
    render(
      <Linea
        day={{ ...idaYVuelta, visits: 2 }}
        advice={[]}
        violations={[]}
        mode="driving"
        selectedStop={null}
        onSelectStop={() => {}}
        zona="Suchitoto"
        shareCode={null}
      />,
    );

    expect(screen.getByText(/^2 paradas$/)).toBeInTheDocument();
    expect(screen.queryByText(/^4 paradas$/)).toBeNull();
  });

  it("el icono del traslado sigue al modo del dia", () => {
    const { container } = pinta({ mode: "walking" });

    // Los iconos de Font Awesome llevan su nombre en data-icon.
    expect(
      container.querySelector('[data-icon="person-walking"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-icon="car-side"]')).toBeNull();
  });
});

describe("la fecha del día", () => {
  it("aparece en la cabecera", () => {
    pinta({ day: dia({ date: "2026-09-11", stops: idaYVuelta.stops }) });

    /* Sitúa las horas de abajo: son las horas de ESTE día. */
    expect(screen.getByText(/viernes,? 11 de septiembre/i)).toBeInTheDocument();
  });

  it("no deja rastro cuando el viaje no tiene fecha", () => {
    pinta({ day: dia({ date: null, stops: idaYVuelta.stops }) });

    expect(screen.queryByText(/septiembre/i)).not.toBeInTheDocument();
    /* Y el resto de la cabecera sigue ahí. */
    expect(screen.getByText("10:00–14:00")).toBeInTheDocument();
  });
});

describe("el clima del día", () => {
  const soleado = {
    temp_max: 31,
    temp_min: 24,
    rain_mm: 0,
    rain_hours: [],
    description: "cielo despejado",
    code: 0,
  };

  it("muestra la temperatura y el estado", () => {
    pinta({ day: dia({ weather: soleado, stops: idaYVuelta.stops }) });

    expect(screen.getByText("31°")).toBeInTheDocument();
    expect(screen.getByText("cielo despejado")).toBeInTheDocument();
  });

  it("no dice nada de lluvia cuando no llueve", () => {
    /* "sin lluvia" ocuparía el mismo espacio para no decir nada, y es lo que
       se leería casi siempre. */
    pinta({ day: dia({ weather: soleado, stops: idaYVuelta.stops }) });

    expect(screen.queryByText(/lluvia/i)).not.toBeInTheDocument();
  });

  it("marca la franja de lluvia cuando la hay", () => {
    pinta({
      day: dia({
        weather: {
          ...soleado,
          rain_hours: [13, 14, 15],
          code: 80,
          description: "chubascos",
        },
        stops: idaYVuelta.stops,
      }),
    });

    expect(screen.getByText(/lluvia de 13:00 a 15:59/i)).toBeInTheDocument();
  });

  it("la fila queda como estaba cuando no se supo el clima", () => {
    pinta({ day: dia({ weather: null, stops: idaYVuelta.stops }) });

    expect(screen.queryByText(/despejado/i)).not.toBeInTheDocument();
    expect(screen.getByText("10:00–14:00")).toBeInTheDocument();
    expect(screen.getByText("12.3 km")).toBeInTheDocument();
  });
});

describe("la luz del dia en el hilo", () => {
  /** Un dia que cruza el ocaso: sale de tarde y cena ya de noche. */
  const hastaelAnochecer = dia({
    sunset: "18:10:00",
    stops: [
      parada({
        place: lugar({ name: "Mirador", category: "nature" }),
        arrival: "16:00:00",
        departure: "17:40:00",
      }),
      parada({
        place: lugar({ name: "Pupuseria", category: "food" }),
        arrival: "18:20:00",
        departure: "19:20:00",
        meal: "dinner",
      }),
      parada({ place: hotel, arrival: "19:40:00", departure: "19:40:00" }),
    ],
  });

  const hilos = (base: HTMLElement) =>
    Array.from(base.querySelectorAll<HTMLElement>(".waypoint-hilo"));

  it("corta el hilo donde cae el ocaso", () => {
    const { container } = pinta({ day: hastaelAnochecer });
    const [primero] = hilos(container);

    // El hilo va de la llegada al mirador (16:00) a la llegada a la pupuseria
    // (18:20): 140 minutos, y el ocaso cae a los 130. El corte repetido es lo
    // que hace que se lea como un momento y no como un atardecer difuso.
    expect(primero.style.backgroundImage).toContain("var(--borde) 92.9%");
    expect(primero.style.backgroundImage).toContain("var(--acento) 92.9%");
  });

  it("el tramo que ya va de noche no lleva nada de dia", () => {
    const { container } = pinta({ day: hastaelAnochecer });
    const [, segundo] = hilos(container);

    // 18:20 a 19:40, entero despues del ocaso: el corte va al principio.
    expect(segundo.style.backgroundImage).toContain("var(--acento) 0.0%");
  });

  it("dice con palabras que ya es de noche", () => {
    // El color del hilo no es informacion para quien no lo ve.
    pinta({ day: hastaelAnochecer });

    expect(screen.getByText(/18:20/).textContent).toContain("ya de noche");
    // 16:00 sale dos veces: en la hora de la parada y en el resumen del dia.
    for (const nodo of screen.getAllByText(/16:00/)) {
      expect(nodo.textContent).not.toContain("ya de noche");
    }
  });

  it("sin ocaso el hilo se queda como estaba", () => {
    // Un itinerario sin fecha no tiene ocaso calculado. Pintar el degradado
    // igual seria inventarse a que hora anochece.
    const { container } = pinta({
      day: dia({ sunset: null, stops: hastaelAnochecer.stops }),
    });

    for (const hilo of hilos(container)) {
      expect(hilo.style.backgroundImage).toBe("");
    }
    expect(screen.queryByText(/ya de noche/)).not.toBeInTheDocument();
  });

  it("escalona el dibujo del hilo con las paradas", () => {
    const { container } = pinta({ day: hastaelAnochecer });
    const retrasos = hilos(container).map((h) =>
      h.style.getPropertyValue("--retraso-hilo"),
    );

    expect(retrasos).toEqual(["0ms", "45ms"]);
  });
});
