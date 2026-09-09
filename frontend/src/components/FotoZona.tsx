"use client";

import { useState } from "react";

import type { AreaPhoto } from "@/lib/types";

interface Props {
  photo: AreaPhoto;
  areaName: string;
}

/**
 * La foto de la zona, arriba del panel.
 *
 * **No va una foto por parada.** Se midió sobre el catálogo cargado: de 5.652
 * lugares activos, 71 traen alguna etiqueta con imagen —el 1,3%—, y en la
 * categoría de comida son 2 de 2.718. Un hueco de imagen que queda vacío
 * diecinueve de cada veinte veces parece una aplicación rota, no un catálogo
 * incompleto. Las zonas sí son entidades con nombre propio: 18 de las 20
 * tienen foto libre.
 *
 * El crédito va visible y no en un `title`. La licencia de Commons lo exige, y
 * un dato que la licencia exige no se esconde detrás de un hover que en un
 * teléfono no existe.
 *
 * **Solo en pantalla ancha.** En móvil el panel mide 55dvh, y entre la foto,
 * el título a dos líneas y la explicación de las distancias, la primera parada
 * quedaba abajo del borde: había que desplazarse para ver el itinerario, que es
 * el producto. Ahí el presupuesto vertical es del itinerario, y encima el mapa
 * está pegado arriba mostrando el territorio de verdad, que es lo que la foto
 * viene a insinuar.
 */
export default function FotoZona({ photo, areaName }: Props) {
  // Si el archivo se renombró en Commons la imagen da 404, y una franja gris
  // con un crédito debajo es peor que no tener franja.
  const [fallo, setFallo] = useState(false);
  if (fallo) return null;

  const src = (ancho: number) =>
    `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(
      photo.file,
    )}?width=${ancho}`;

  return (
    <figure className="relative m-0 hidden h-32 shrink-0 overflow-hidden border-b border-borde lg:block">
      {/*
        <img> y no next/image, a proposito.

        Commons ya sirve la imagen redimensionada con ?width=, que es
        exactamente lo que next/image haria —asi que no aporta nada— y a cambio
        pasaria los bytes por nuestro servidor en vez de por el CDN de
        Wikimedia, que los sirve gratis. El aviso de LCP tampoco aplica: esta
        foto solo existe cuando ya hay un plan, mucho despues de la primera
        pintura.
      */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src(896)}
        srcSet={`${src(448)} 448w, ${src(896)} 896w, ${src(1344)} 1344w`}
        sizes="(min-width: 1024px) 27rem, 100vw"
        alt={`Vista de ${areaName}`}
        loading="lazy"
        decoding="async"
        onError={() => setFallo(true)}
        className="h-full w-full object-cover"
      />

      {/*
        El crédito se lee sobre una foto cualquiera, así que no puede depender
        del color de la foto: lleva su propio fondo oscuro y texto claro fijos,
        no los del tema. Es el único sitio del proyecto donde eso es correcto.
      */}
      <figcaption className="absolute right-0 bottom-0 max-w-full truncate bg-black/55 px-1.5 py-0.5 text-[10px] text-white/85 backdrop-blur-sm">
        <a
          href={photo.page}
          target="_blank"
          rel="noreferrer noopener"
          className="hover:underline"
        >
          {photo.author} · {photo.license}
        </a>
      </figcaption>
    </figure>
  );
}
