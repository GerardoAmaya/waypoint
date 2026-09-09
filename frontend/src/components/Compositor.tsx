"use client";

import { useState } from "react";
import { motion } from "motion/react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRoute, faTriangleExclamation } from "@fortawesome/free-solid-svg-icons";

export type Fase = "quieto" | "leyendo" | "eligiendo" | "midiendo" | "listo";

const PASOS: { fase: Fase; texto: string }[] = [
  { fase: "leyendo", texto: "Leyendo lo que pediste" },
  { fase: "eligiendo", texto: "Buscando lugares" },
  { fase: "midiendo", texto: "Midiendo las rutas" },
];

const EJEMPLOS = [
  "Tres días por la Ruta de las Flores, odio madrugar",
  "Un día en Suchitoto caminando, sin museos",
  "Dos días en Santa Ana sin pasarme el día en el carro",
];

interface Props {
  fase: Fase;
  error: string | null;
  onSubmit: (mensaje: string) => void;
}

export default function Compositor({ fase, error, onSubmit }: Props) {
  const [texto, setTexto] = useState("");
  const trabajando = fase !== "quieto" && fase !== "listo";

  const enviar = () => {
    const limpio = texto.trim();
    if (!limpio || trabajando) return;
    onSubmit(limpio);
  };

  return (
    /*
      Una pieza sobre el mapa y no un velo encima. Oscurecer el pais entero para
      que se lea un titular tapa justo lo que el estado vacio quiere mostrar: que
      hay material, y donde esta.

      El borde es el fuerte y no el divisor: en tema claro esta caja flota sobre
      un mapa igual de claro, y sin un borde que llegue a contraste el panel se
      deshace contra el territorio. Es lo mismo que hundio la primera version de
      esta pantalla, resuelto con borde y elevacion en vez de con luminosidad.
    */
    <div className="w-full max-w-2xl rounded-xl border border-borde-fuerte bg-superficie/94 px-6 py-7 shadow-panel backdrop-blur-sm sm:px-8 sm:py-9">
      <h1 className="text-obra leading-[0.92] font-extralight tracking-tight text-tinta">
        Contame el viaje
        <br />
        que querés hacer.
      </h1>
      <p className="mt-4 max-w-md text-guia sm:mt-5 leading-snug font-light text-tinta-suave">
        Escribilo como se lo contarías a alguien. El plan sale sobre lugares que
        existen, con distancias medidas.
      </p>

      <div className="mt-6 sm:mt-8">
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
          placeholder="Tres días por la Ruta de las Flores, odio madrugar y no quiero pasarme el día en el carro"
          className="w-full resize-none rounded-lg border border-borde-fuerte bg-superficie-alta px-4 py-3.5 text-cuerpo leading-relaxed text-tinta transition-colors placeholder:text-tinta-tenue focus:border-acento disabled:opacity-60"
        />

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            onClick={enviar}
            disabled={trabajando || !texto.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-acento px-5 py-2.5 text-cuerpo text-sobre-acento transition-opacity disabled:opacity-40"
          >
            <FontAwesomeIcon icon={faRoute} aria-hidden className="size-3.5" />
            Armar el itinerario
          </button>

          {trabajando && (
            <div className="flex items-center gap-3" role="status" aria-live="polite">
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
                        ? "text-tinta"
                        : hecho
                          ? "text-tinta-tenue"
                          : "text-tinta-tenue/50"
                    }`}
                  >
                    {actual && (
                      <motion.span
                        aria-hidden
                        className="mr-1.5 inline-block size-1.5 rounded-full bg-acento align-middle"
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
          <p className="mt-4 flex max-w-lg gap-2.5 border-l-2 border-aviso pl-3 text-menudo leading-relaxed text-tinta-suave">
            <FontAwesomeIcon
              icon={faTriangleExclamation}
              aria-hidden
              className="mt-0.5 size-3 shrink-0 text-aviso"
            />
            <span>{error}</span>
          </p>
        ) : (
          !trabajando && (
            <ul className="mt-6 space-y-1.5">
              {EJEMPLOS.map((ejemplo) => (
                <li key={ejemplo}>
                  <button
                    onClick={() => setTexto(ejemplo)}
                    className="text-left text-menudo text-tinta-tenue transition-colors hover:text-tinta"
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
