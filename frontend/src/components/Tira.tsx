"use client";

import { CATEGORIA } from "@/lib/categorias";
import { describir } from "@/lib/tarjeta";
import type { Interpretation, Itinerary } from "@/lib/types";

/**
 * La forma del viaje: una fila por día, un punto por parada.
 *
 * **Es lo único visual que el itinerario podía permitirse.** Las fotos por
 * parada están descartadas por tres mediciones independientes: la etiqueta
 * `image` de OpenStreetMap sale en el 0,1% de 6.449 lugares, algún enlace a
 * Wikidata o Wikipedia en el 1,8% de los destinos, y las fotos geolocalizadas
 * de Commons a menos de 300 metros en el 7%. Un hueco de imagen vacío nueve de
 * cada diez veces parece una aplicación rota.
 *
 * Esto no inventa nada: es el itinerario dibujado. Se ve de un vistazo cuántas
 * paradas tiene cada día y de qué tipo, que es la pregunta que uno se hace
 * antes de abrir ninguna pestaña —«¿cuál día va cargado?»—.
 *
 * Es la misma composición que la tarjeta del enlace compartido, y comparte con
 * ella `describir`: una sola definición de la forma de un viaje.
 *
 * **Y es el selector de día, no un adorno encima de otro.** La primera versión
 * la puso sobre las píldoras de «Día 1 · Día 2 · Día 3» y al mirarla se veían
 * dos selectores apilados diciendo lo mismo. Así que la tira se quedó con el
 * papel —con su `role="tab"` y su navegación por flechas— y las píldoras se
 * fueron, lo que además devuelve alto al panel, que en móvil es justo lo que
 * falta.
 */

/**
 * Cuántos puntos caben antes de que se aprieten.
 *
 * Pasado eso el resto se dice con un "+n": la tira existe para que se vea la
 * forma del día, y catorce puntos de seis píxeles no tienen forma.
 */
const PUNTOS_QUE_CABEN = 10;

export default function Tira({
  interpretation,
  itinerary,
  selectedDay,
  onSelectDay,
  refLista,
  onTecla,
}: {
  interpretation: Interpretation | null;
  itinerary: Itinerary;
  selectedDay: number;
  onSelectDay: (dia: number) => void;
  refLista?: React.Ref<HTMLDivElement>;
  onTecla?: (e: React.KeyboardEvent) => void;
}) {
  // Un solo día no tiene forma que comparar, y tampoco hay entre qué elegir.
  if (itinerary.days.length < 2) return null;

  const { dias } = describir(interpretation, itinerary);

  return (
    <div
      ref={refLista}
      role="tablist"
      aria-label="Días del itinerario"
      onKeyDown={onTecla}
      className="flex shrink-0 flex-col gap-0.5 border-b border-borde px-3 py-2 sm:px-4"
    >
      {dias.map((fila, i) => {
        const numero = itinerary.days[i].number;
        const activo = numero === selectedDay;
        const visibles = fila.paradas.slice(0, PUNTOS_QUE_CABEN);
        const resto = fila.paradas.length - visibles.length;

        return (
          <button
            key={numero}
            role="tab"
            id={`pestana-dia-${numero}`}
            aria-selected={activo}
            aria-controls="panel-dia"
            /* Un solo punto de tabulacion para el grupo: dentro se navega con
               flechas. Es el patron de pestañas de ARIA. */
            tabIndex={activo ? 0 : -1}
            onClick={() => onSelectDay(numero)}
            aria-label={`Día ${numero}, ${fila.paradas.length} paradas`}
            /*
              El día elegido se marca con fondo y una barra, no tiñéndolo del
              acento. **Los colores de los puntos son el dato**, y sobre el
              azul del acento el verde de naturaleza y el gris de alojamiento
              se pierden: se vio al mirarlo.
            */
            className={`relative flex items-center gap-2.5 rounded-md py-1 pr-1.5 pl-3 text-left transition-colors ${
              activo ? "bg-superficie-alta" : "hover:bg-superficie-alta/60"
            }`}
          >
            {activo && (
              <span
                aria-hidden
                className="absolute top-1.5 bottom-1.5 left-0 w-0.5 rounded-full bg-acento"
              />
            )}

            <span
              className={`dato w-14 shrink-0 text-menudo ${
                activo ? "text-tinta" : "text-tinta-tenue"
              }`}
            >
              {fila.etiqueta}
            </span>

            <span aria-hidden className="flex items-center">
              {visibles.map((categoria, j) => (
                <span key={j} className="flex items-center">
                  {/* El tramo entre dos paradas, que es lo que hace que se lea
                      como un día y no como una fila de fichas. */}
                  {j > 0 && <span className="h-px w-1.5 bg-borde" />}
                  <span
                    className="size-1.5 rounded-full transition-opacity"
                    style={{
                      background: CATEGORIA[categoria]?.color ?? "var(--acero)",
                      opacity: activo ? 1 : 0.6,
                    }}
                  />
                </span>
              ))}
              {resto > 0 && (
                <span className="dato ml-1.5 text-dato text-tinta-tenue">+{resto}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
