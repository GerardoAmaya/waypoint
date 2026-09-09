"use client";

import { useState } from "react";
import { motion } from "motion/react";

export type Fase = "quieto" | "leyendo" | "eligiendo" | "midiendo" | "listo";

const PASOS: { fase: Fase; texto: string }[] = [
  { fase: "leyendo", texto: "Leyendo lo que pediste" },
  { fase: "eligiendo", texto: "Buscando lugares" },
  { fase: "midiendo", texto: "Midiendo las rutas" },
];

const EJEMPLOS = [
  "tres días por la Ruta de las Flores, odio madrugar",
  "un día en Suchitoto caminando, sin museos",
  "dos días en Santa Ana sin pasarme el día en el carro",
];

interface Props {
  fase: Fase;
  error: string | null;
  compacto: boolean;
  onSubmit: (mensaje: string) => void;
  onReset: () => void;
}

export default function Compositor({
  fase,
  error,
  compacto,
  onSubmit,
  onReset,
}: Props) {
  const [texto, setTexto] = useState("");
  const trabajando = fase !== "quieto" && fase !== "listo";

  const enviar = () => {
    const limpio = texto.trim();
    if (!limpio || trabajando) return;
    onSubmit(limpio);
  };

  if (compacto) {
    return (
      <button
        onClick={onReset}
        className="rounded-full border border-basalto-borde bg-basalto-alto/90 px-4 py-2 text-menudo text-niebla backdrop-blur transition-colors hover:border-anil-claro"
      >
        Empezar de nuevo
      </button>
    );
  }

  return (
    <div className="w-full max-w-2xl">
      <h1 className="text-obra leading-[0.92] font-extralight tracking-tight text-niebla">
        Contame el viaje
        <br />
        que querés hacer.
      </h1>
      <p className="mt-5 max-w-md text-guia leading-snug font-light text-niebla/55">
        Escribilo como se lo contarías a alguien. El plan sale sobre lugares que
        existen, con distancias medidas.
      </p>

      <div className="mt-8">
        <textarea
          aria-label="Contá el viaje que querés hacer"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              enviar();
            }
          }}
          disabled={trabajando}
          rows={3}
          placeholder="tres días por la Ruta de las Flores, odio madrugar y no quiero pasarme el día en el carro"
          className="w-full resize-none rounded-lg border border-basalto-borde bg-basalto-alto/80 px-4 py-3.5 text-cuerpo leading-relaxed text-niebla backdrop-blur placeholder:text-niebla/30 focus:border-anil-claro disabled:opacity-60"
        />

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            onClick={enviar}
            disabled={trabajando || !texto.trim()}
            className="rounded bg-anil px-5 py-2.5 text-cuerpo text-niebla transition-opacity disabled:opacity-40"
          >
            Armar el itinerario
          </button>

          {trabajando && (
            <div className="flex items-center gap-2" role="status" aria-live="polite">
              {PASOS.map((paso) => {
                const indice = PASOS.findIndex((p) => p.fase === fase);
                const propio = PASOS.findIndex((p) => p.fase === paso.fase);
                const hecho = propio < indice;
                const actual = propio === indice;
                return (
                  <span
                    key={paso.fase}
                    className={`text-dato ${
                      actual
                        ? "text-niebla"
                        : hecho
                          ? "text-niebla/35"
                          : "text-niebla/20"
                    }`}
                  >
                    {actual && (
                      <motion.span
                        aria-hidden
                        className="mr-1.5 inline-block size-1.5 rounded-full bg-anil-claro align-middle"
                        animate={{ opacity: [1, 0.25, 1] }}
                        transition={{ duration: 1.4, repeat: Infinity }}
                      />
                    )}
                    {paso.texto}
                  </span>
                );
              })}
            </div>
          )}
        </div>

        {error ? (
          <p className="mt-4 max-w-lg border-l-2 border-cafe pl-3 text-menudo leading-relaxed text-niebla/70">
            {error}
          </p>
        ) : (
          !trabajando && (
            <ul className="mt-6 space-y-1.5">
              {EJEMPLOS.map((ejemplo) => (
                <li key={ejemplo}>
                  <button
                    onClick={() => setTexto(ejemplo)}
                    className="text-left text-menudo text-niebla/40 transition-colors hover:text-niebla/75"
                  >
                    {ejemplo}
                  </button>
                </li>
              ))}
            </ul>
          )
        )}
      </div>
    </div>
  );
}
