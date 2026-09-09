"use client";

import { useEffect, useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowUpRightFromSquare,
  faDiamondTurnRight,
  faMountain,
  faPhone,
  faUtensils,
} from "@fortawesome/free-solid-svg-icons";
import type { IconDefinition } from "@fortawesome/free-solid-svg-icons";

import type { Place } from "@/lib/types";

/**
 * Lo que se sabe de una parada, cuando se la elige.
 *
 * **Nada de fotos por parada.** Se midió: de 5.652 lugares del catálogo, 71
 * traen alguna etiqueta con imagen, y en comida son 2 de 2.718. Un hueco vacío
 * diecinueve de cada veinte veces parece una aplicación rota.
 *
 * Estos cuatro datos sí existen: alguno aparece en el 45% de los comedores, el
 * 31% de los alojamientos y el 24% de los lugares naturales. En miradores no
 * hay ninguno, así que lo único que siempre está es la acción de ir: eso no
 * depende de que OSM tenga el dato, solo de las coordenadas.
 */
export default function Detalle({ place }: { place: Place }) {
  const caja = useRef<HTMLDivElement>(null);

  /*
    Si la parada estaba al borde de abajo, el detalle se abria fuera de vista y
    parecia que el clic no habia hecho nada. "nearest" desplaza lo minimo: no
    mueve nada si ya se ve entero.
  */
  useEffect(() => {
    caja.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  const datos: { icono: IconDefinition; texto: string }[] = [];
  if (place.cuisine) datos.push({ icono: faUtensils, texto: place.cuisine });
  if (place.elevation_m !== null) {
    datos.push({ icono: faMountain, texto: `${place.elevation_m} m` });
  }
  if (place.phone) datos.push({ icono: faPhone, texto: place.phone });

  return (
    <div
      ref={caja}
      className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-borde pt-2.5"
    >
      {datos.map((dato) => (
        <span
          key={dato.texto}
          className="inline-flex items-center gap-1.5 text-dato text-tinta-suave"
        >
          <FontAwesomeIcon icon={dato.icono} aria-hidden className="size-3" />
          {dato.texto}
        </span>
      ))}

      {/*
        La acción que siempre se puede ofrecer. Es un enlace y no una
        integración: enlazar a un mapa está permitido, incrustar sus teselas no.
        `api=1` es la URL universal de Google Maps —abre la aplicación en el
        teléfono y el navegador en el escritorio— y va por coordenadas y no por
        nombre, porque "Mirador 3" no se encuentra buscándolo.
      */}
      <a
        href={`https://www.google.com/maps/dir/?api=1&destination=${place.lat},${place.lon}`}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1.5 rounded-md border border-borde-fuerte px-2 py-1 text-dato text-tinta-suave transition-colors hover:border-acento hover:text-tinta"
      >
        <FontAwesomeIcon icon={faDiamondTurnRight} aria-hidden className="size-3" />
        Cómo llegar
      </a>

      {place.website && (
        <a
          href={place.website}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 text-dato text-tinta-suave transition-colors hover:text-tinta"
        >
          <FontAwesomeIcon
            icon={faArrowUpRightFromSquare}
            aria-hidden
            className="size-2.5"
          />
          Sitio web
        </a>
      )}
    </div>
  );
}
