"use client";

import { useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDesktop, faMoon, faSun } from "@fortawesome/free-solid-svg-icons";
import type { IconDefinition } from "@fortawesome/free-solid-svg-icons";

import {
  aplicarTema,
  leerTema,
  leerTemaEnServidor,
  suscribirTema,
  type Tema as TemaId,
} from "@/lib/tema";

const OPCIONES: { id: TemaId; icono: IconDefinition; nombre: string }[] = [
  { id: "sistema", icono: faDesktop, nombre: "Seguir al sistema" },
  { id: "light", icono: faSun, nombre: "Tema claro" },
  { id: "dark", icono: faMoon, nombre: "Tema oscuro" },
];

/**
 * Tres botones y no uno que cicla.
 *
 * Un boton que cicla entre tres estados no dice en que estado esta ni cual
 * sigue, y hay que apretarlo para averiguarlo. Aca el estado se ve, y para un
 * lector de pantalla es un grupo de tres con aria-pressed, que es exactamente
 * lo que es.
 */
export default function Tema() {
  /*
    La preferencia vive en localStorage, no en React, y la puede cambiar otra
    pestana. useSyncExternalStore es la forma de observar eso: el render del
    servidor usa "sistema" sin desajustar la hidratacion, y aplicarTema avisa a
    todas las suscripciones —incluidas las de las otras pestanas, por el evento
    storage.
  */
  const tema = useSyncExternalStore(suscribirTema, leerTema, leerTemaEnServidor);

  return (
    <div
      role="group"
      aria-label="Tema"
      className="flex items-center gap-0.5 rounded-full border border-borde-fuerte bg-superficie/92 p-1 shadow-panel backdrop-blur"
    >
      {OPCIONES.map((opcion) => {
        const activo = opcion.id === tema;
        return (
          <button
            key={opcion.id}
            onClick={() => aplicarTema(opcion.id)}
            aria-pressed={activo}
            title={opcion.nombre}
            className={`grid size-7 place-items-center rounded-full transition-colors ${
              activo
                ? "bg-acento text-sobre-acento"
                : "text-tinta-tenue hover:text-tinta"
            }`}
          >
            <FontAwesomeIcon icon={opcion.icono} className="size-3.5" />
            <span className="sr-only">{opcion.nombre}</span>
          </button>
        );
      })}
    </div>
  );
}
