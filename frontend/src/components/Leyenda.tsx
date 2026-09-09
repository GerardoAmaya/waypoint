"use client";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

import { CATEGORIA, ORDEN_LEYENDA } from "@/lib/categorias";
import type { Category, Day } from "@/lib/types";

interface Props {
  days: Day[];
}

/**
 * Que significa cada color del mapa, y que significa el trazo punteado.
 *
 * **Solo en pantalla ancha.** En movil el mapa mide 45dvh y la leyenda le
 * tapaba la mitad, justo el itinerario que viene a explicar. Y ahi no hace
 * falta: el panel queda pegado debajo del mapa y cada parada de la linea de
 * tiempo ya trae su icono al lado del nombre de su categoria, que es donde la
 * correspondencia se aprende de verdad. La leyenda sirve cuando el panel esta
 * al costado y hay que mirar de un lado al otro.
 *
 * El mapa venia codificando dos cosas sin decirlo en ninguna parte: el color
 * del pin era la categoria y el guion del trazo era "esta distancia es
 * estimada". Lo segundo se explicaba en el panel con una frase, y lo primero no
 * se explicaba. Un codigo sin leyenda es decoracion.
 *
 * Solo lista las categorias que aparecen en el plan. Una leyenda con seis
 * entradas donde la pantalla tiene dos es una lista de posibilidades, no una
 * leyenda.
 */
export default function Leyenda({ days }: Props) {
  const presentes = new Set<Category>();
  /*
    Que clases de trazo hay en pantalla, contadas tramo por tramo.

    Antes se decidia con el travelSource del itinerario, y eso mentia en los
    dos sentidos: con un solo par sin carretera la leyenda declaraba todo
    estimado, y no habia forma de explicar un plan mixto. El trazo es un dato
    por tramo, asi que su leyenda tambien.
  */
  let hayCarretera = false;
  let hayEstimado = false;

  for (const dia of days) {
    dia.stops.forEach((parada, indice) => {
      presentes.add(parada.place.category);
      if (indice === 0) return;
      const real = parada.geometry_from_previous;
      if (real && real.length > 1) hayCarretera = true;
      else hayEstimado = true;
    });
  }
  if (!presentes.size) return null;

  const categorias = ORDEN_LEYENDA.filter((c) => presentes.has(c));

  return (
    <div className="rounded-lg border border-borde-fuerte bg-superficie/92 px-3 py-2.5 shadow-panel backdrop-blur">
      <ul className="flex flex-wrap gap-x-3 gap-y-1.5">
        {categorias.map((categoria) => {
          const { nombre, icono, color } = CATEGORIA[categoria];
          return (
            <li
              key={categoria}
              className="inline-flex items-center gap-1.5 text-dato text-tinta-suave"
            >
              <FontAwesomeIcon
                icon={icono}
                aria-hidden
                className="size-3"
                style={{ color }}
              />
              {nombre}
            </li>
          );
        })}
      </ul>

      {/*
        El guion del trazo es un dato y merece su entrada. La linea se dibuja
        con SVG en vez de con un borde punteado de CSS para que el patron sea
        el mismo que el del mapa y no "algo punteado".

        Solo se listan las clases que aparecen: si todos los tramos van por
        carretera, explicar el punteado es explicar algo que no esta.
      */}
      {(hayCarretera || hayEstimado) && (
        <div className="mt-2 space-y-1 border-t border-borde pt-2">
          {hayCarretera && <Trazo texto="por carretera" />}
          {hayEstimado && <Trazo texto="distancia estimada" guion />}
        </div>
      )}
    </div>
  );
}

/** Una entrada de la leyenda del trazo. */
function Trazo({ texto, guion = false }: { texto: string; guion?: boolean }) {
  return (
    <p className="flex items-center gap-1.5 text-dato text-tinta-tenue">
      <svg width="22" height="4" aria-hidden className="shrink-0">
        <line
          x1="0"
          y1="2"
          x2="22"
          y2="2"
          stroke="var(--anil)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray={guion ? "2 4" : undefined}
        />
      </svg>
      {texto}
    </p>
  );
}
