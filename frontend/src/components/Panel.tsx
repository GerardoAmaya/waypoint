"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";

import Linea from "./Linea";
import type { Interpretation, Itinerary } from "@/lib/types";

interface Props {
  interpretation: Interpretation | null;
  itinerary: Itinerary | null;
  selectedDay: number | null;
  onSelectDay: (dia: number) => void;
  onRevise: (mensaje: string) => Promise<void>;
  revising: boolean;
  reviseError: string | null;
}

const FUENTE: Record<string, string> = {
  estimated: "Distancias estimadas desde la línea recta",
  mixed: "Distancias reales, algunas estimadas",
  real: "Distancias reales de carretera",
};

export default function Panel({
  interpretation,
  itinerary,
  selectedDay,
  onSelectDay,
  onRevise,
  revising,
  reviseError,
}: Props) {
  const [cambio, setCambio] = useState("");

  if (!itinerary || !itinerary.days.length) return null;

  const dia =
    itinerary.days.find((d) => d.number === selectedDay) ?? itinerary.days[0];

  const enviar = async () => {
    const texto = cambio.trim();
    if (!texto || revising) return;
    await onRevise(texto);
    setCambio("");
  };

  return (
    <section className="flex h-full flex-col bg-niebla text-tinta">
      <header className="border-b border-niebla-honda px-6 pt-6 pb-4">
        <h1 className="text-titulo leading-tight font-semibold tracking-tight">
          {interpretation?.area?.name ?? "Tu itinerario"}
        </h1>
        <p className="mt-1 text-menudo text-tinta-suave">
          {itinerary.days.length}{" "}
          {itinerary.days.length === 1 ? "día" : "días"} · {itinerary.total_stops}{" "}
          paradas · {FUENTE[itinerary.travel.source]}
        </p>

        {/*
          Lo que el modelo entendio y no pudo representar se muestra, no se
          descarta. Que el usuario vea que "tranquilo" quedo afuera es mejor
          que dejarlo creer que se tuvo en cuenta.
        */}
        {!!interpretation?.unmapped?.length && (
          <p className="mt-3 border-l-2 border-anil pl-3 text-menudo leading-relaxed text-tinta-suave">
            No supe cómo usar esto: {interpretation.unmapped.join(", ")}. El resto
            sí está aplicado.
          </p>
        )}

        {!!interpretation?.notes?.length && (
          <ul className="mt-2 space-y-1">
            {interpretation.notes.map((n, i) => (
              <li key={i} className="text-dato text-tinta-tenue">
                {n}
              </li>
            ))}
          </ul>
        )}
      </header>

      {itinerary.days.length > 1 && (
        <nav
          aria-label="Días del itinerario"
          className="flex gap-1 border-b border-niebla-honda px-6 py-3"
        >
          {itinerary.days.map((d) => {
            const activo = d.number === dia.number;
            return (
              <button
                key={d.number}
                onClick={() => onSelectDay(d.number)}
                aria-current={activo ? "true" : undefined}
                className={`relative rounded px-3 py-1.5 text-menudo transition-colors ${
                  activo ? "text-niebla" : "text-tinta-suave hover:text-tinta"
                }`}
              >
                {activo && (
                  <motion.span
                    layoutId="dia-activo"
                    className="absolute inset-0 -z-10 rounded bg-anil"
                    transition={{ type: "spring", stiffness: 380, damping: 32 }}
                  />
                )}
                Día {d.number}
              </button>
            );
          })}
        </nav>
      )}

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={dia.number}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
          >
            <Linea
              day={dia}
              advice={itinerary.advice}
              violations={itinerary.violations}
            />
          </motion.div>
        </AnimatePresence>

        {itinerary.violations
          .filter((v) => v.day === null)
          .map((v, i) => (
            <p
              key={i}
              className="mt-6 border-l-2 border-cafe pl-3 text-menudo text-tinta-suave"
            >
              {v.detail}
            </p>
          ))}
      </div>

      <footer className="border-t border-niebla-honda px-6 py-4">
        <label
          htmlFor="revisar"
          className="text-dato text-tinta-tenue"
        >
          Cambiar el día {dia.number}
        </label>
        <div className="mt-2 flex gap-2">
          <input
            id="revisar"
            value={cambio}
            onChange={(e) => setCambio(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void enviar();
            }}
            disabled={revising}
            placeholder="menos carro, o sacá el museo"
            className="min-w-0 flex-1 rounded border border-niebla-honda bg-white px-3 py-2 text-menudo text-tinta placeholder:text-tinta-tenue disabled:opacity-60"
          />
          <button
            onClick={() => void enviar()}
            disabled={revising || !cambio.trim()}
            className="rounded bg-anil px-4 py-2 text-menudo text-niebla transition-opacity disabled:opacity-40"
          >
            {revising ? "Rehaciendo" : "Aplicar"}
          </button>
        </div>
        {reviseError && (
          <p className="mt-2 text-dato leading-relaxed text-cafe">{reviseError}</p>
        )}
      </footer>
    </section>
  );
}
