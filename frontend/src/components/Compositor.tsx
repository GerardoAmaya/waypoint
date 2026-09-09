"use client";

import { useState } from "react";
import { motion } from "motion/react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowTurnUp,
  faRoute,
  faTriangleExclamation,
} from "@fortawesome/free-solid-svg-icons";

export type Fase = "quieto" | "leyendo" | "eligiendo" | "midiendo" | "listo";

const PASOS: { fase: Fase; texto: string }[] = [
  { fase: "leyendo", texto: "Leyendo lo que pediste" },
  { fase: "eligiendo", texto: "Buscando lugares" },
  { fase: "midiendo", texto: "Midiendo las rutas" },
];

/*
  Cada ejemplo enseña una capacidad distinta, no tres variantes de la misma.
  Los tres anteriores eran "N dias en [zona turistica] + preferencia", asi que
  quien los leia se llevaba una sola idea de lo que puede pedir.

  Entre los tres cubren las cuatro cosas que el subtitulo pide: cuantos dias,
  el modo, el horario y de donde se sale. El tercero ademas nombra un municipio
  y no una zona turistica, porque desde el nomenclator se puede decir donde se
  esta uno quedando y eso no se adivina si nadie lo muestra.
*/
const EJEMPLOS = [
  "Tres días por la Ruta de las Flores, odio madrugar",
  "Un día en Suchitoto caminando, sin museos",
  "Dos días saliendo desde Santa Tecla, en carro",
];

interface Props {
  fase: Fase;
  error: string | null;
  /** Cuantos lugares tiene el catalogo cargado. Cero mientras no lleguen. */
  catalogo: number;
  onSubmit: (mensaje: string) => void;
}

export default function Compositor({ fase, error, catalogo, onSubmit }: Props) {
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
        Escribilo como se lo contarías a alguien. Ayuda que cuentes cuántos
        días, si vas en carro o a pie, desde qué hora podés salir y dónde te
        estás quedando.
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
          placeholder="dos días por el occidente, sin madrugar"
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
            <div className="mt-6">
              <ul className="space-y-1.5">
                {EJEMPLOS.map((ejemplo) => (
                  <li key={ejemplo}>
                    <button
                      onClick={() => setTexto(ejemplo)}
                      className="group flex items-baseline gap-2 text-left text-menudo text-tinta-tenue transition-colors hover:text-tinta"
                    >
                      {/*
                        La flecha no es adorno: sin ella los ejemplos se leen
                        como texto de parrafo y nadie descubre que se pueden
                        tocar. Es la unica pista de que son acciones.
                      */}
                      <FontAwesomeIcon
                        icon={faArrowTurnUp}
                        aria-hidden
                        className="mt-0.5 size-2.5 shrink-0 rotate-90 text-acento opacity-70 transition-opacity group-hover:opacity-100"
                      />
                      <span>{ejemplo}</span>
                    </button>
                  </li>
                ))}
              </ul>

              {/*
                Sin la cifra del catalogo: a quien va a viajar no le cambia nada
                que sean cinco mil o tres mil, y decir "ninguno inventado" le
                mete una duda que no tenia. Lo que si le falta a esta pantalla
                es el pais, que hasta ahora solo se deducia del mapa.

                Se muestra solo cuando el catalogo llego de verdad. Afirmar de
                donde salen los lugares con el backend caido seria sostener algo
                que no se comprobo, que es justo lo que este proyecto no hace.
              */}
              {catalogo > 0 && (
                <p className="mt-5 text-dato text-tinta-tenue">
                  Lugares reales de El Salvador, del catálogo abierto de
                  OpenStreetMap.
                </p>
              )}
            </div>
          )
        )}
      </div>
    </div>
  );
}
