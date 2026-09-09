"use client";

import { AnimatePresence, motion } from "motion/react";

import {
  CATEGORY_COLOR,
  CATEGORY_LABEL,
  PALETA,
  type Advice,
  type Day,
  type Violation,
} from "@/lib/types";

interface Props {
  day: Day;
  advice: Advice[];
  violations: Violation[];
}

const hora = (valor: string | null) => (valor ? valor.slice(0, 5) : "");

export default function Linea({ day, advice, violations }: Props) {
  const delDia = advice.filter((a) => a.day === day.number);
  const rotas = violations.filter((v) => v.day === day.number);

  return (
    <div>
      <div className="mb-5 flex items-baseline gap-3 border-b border-niebla-honda pb-3">
        <span className="dato text-dato text-tinta-suave">
          {hora(day.start)}–{hora(day.end)}
        </span>
        <span className="dato text-dato text-tinta-suave">
          {day.travel_km.toFixed(1)} km
        </span>
        <span className="text-dato text-tinta-tenue">
          {day.stops.length} {day.stops.length === 1 ? "parada" : "paradas"}
        </span>
      </div>

      <ol className="relative">
        <AnimatePresence mode="popLayout" initial={false}>
          {day.stops.map((parada, indice) => (
            <motion.li
              key={parada.place.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28, delay: indice * 0.045 }}
              className="relative grid grid-cols-[3.25rem_1fr] gap-x-4 pb-6 last:pb-0"
            >
              {/* El hilo une las paradas del dia y se corta en la ultima. */}
              {indice < day.stops.length - 1 && (
                <span
                  aria-hidden
                  className="absolute left-[3.9rem] top-6 bottom-0 w-px bg-niebla-honda"
                />
              )}

              <span className="dato pt-0.5 text-right text-menudo text-tinta-suave">
                {hora(parada.arrival)}
              </span>

              <div className="relative">
                <span
                  aria-hidden
                  className="absolute -left-[1.35rem] top-1.5 size-2.5 rounded-full ring-4 ring-niebla"
                  style={{
                    background:
                      CATEGORY_COLOR[parada.place.category] ?? PALETA.anil,
                  }}
                />
                <p className="text-cuerpo font-medium leading-snug text-tinta">
                  {parada.place.name}
                </p>
                <p className="mt-0.5 text-dato text-tinta-tenue">
                  {parada.meal === "lunch"
                    ? "Almuerzo"
                    : parada.meal === "dinner"
                      ? "Cena"
                      : (CATEGORY_LABEL[parada.place.category] ?? "")}
                  {" · hasta las "}
                  <span className="dato">{hora(parada.departure)}</span>
                </p>

                {parada.travel_km_from_previous > 0 && (
                  <p className="dato mt-2 text-dato text-tinta-tenue">
                    {parada.travel_km_from_previous.toFixed(1)} km ·{" "}
                    {parada.travel_minutes_from_previous} min desde la parada anterior
                  </p>
                )}
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>

      {rotas.map((v, i) => (
        <p
          key={`v-${i}`}
          className="mt-4 border-l-2 border-cafe pl-3 text-menudo text-tinta-suave"
        >
          {v.detail}
        </p>
      ))}

      {/*
        El consejo vive dentro del dia al que pertenece y no en un aviso
        flotante. Enterarse de que hay que llevar almuerzo mientras se mira
        el dia que no lo tiene es lo unico que sirve.
      */}
      {delDia.map((a, i) => (
        <p
          key={`a-${i}`}
          className="mt-4 rounded border border-ocre/30 bg-ocre/5 px-3 py-2 text-menudo leading-relaxed text-tinta-suave"
        >
          {a.detail}
        </p>
      ))}
    </div>
  );
}
