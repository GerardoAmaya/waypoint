"use client";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faMap, faSatellite } from "@fortawesome/free-solid-svg-icons";
import type { IconDefinition } from "@fortawesome/free-solid-svg-icons";

import type { Fondo as FondoId } from "./Mapa";

const OPCIONES: { id: FondoId; icono: IconDefinition; nombre: string }[] = [
  { id: "mapa", icono: faMap, nombre: "Mapa" },
  { id: "satelite", icono: faSatellite, nombre: "Satélite" },
];

interface Props {
  fondo: FondoId;
  onChange: (fondo: FondoId) => void;
}

/**
 * Mapa o satélite.
 *
 * Va abajo a la izquierda y no arriba a la derecha porque es un control del
 * mapa y no de la aplicación: el tema y el reinicio son de la aplicación. Con
 * los tres juntos en una esquina no se distingue qué cambia cada uno, y en un
 * teléfono no caben en una línea.
 *
 * Lleva texto además del icono. En el interruptor de tema el icono basta —el
 * sol y la luna no se confunden— pero un satélite a 14 píxeles no dice si el
 * botón enciende la foto aérea o abre otra cosa.
 */
export default function Fondo({ fondo, onChange }: Props) {
  return (
    <div
      role="group"
      aria-label="Fondo del mapa"
      className="inline-flex items-center gap-0.5 rounded-lg border border-borde-fuerte bg-superficie/92 p-1 shadow-panel backdrop-blur"
    >
      {OPCIONES.map((opcion) => {
        const activo = opcion.id === fondo;
        return (
          <button
            key={opcion.id}
            onClick={() => onChange(opcion.id)}
            aria-pressed={activo}
            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-dato transition-colors ${
              activo
                ? "bg-acento text-sobre-acento"
                : "text-tinta-tenue hover:text-tinta"
            }`}
          >
            <FontAwesomeIcon icon={opcion.icono} aria-hidden className="size-3" />
            {opcion.nombre}
          </button>
        );
      })}
    </div>
  );
}
