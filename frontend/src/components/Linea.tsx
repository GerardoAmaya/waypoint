"use client";

import { AnimatePresence, motion } from "motion/react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faCarSide,
  faClock,
  faLightbulb,
  faLocationDot,
  faPersonWalking,
  faRoute,
  faTriangleExclamation,
  faUtensils,
} from "@fortawesome/free-solid-svg-icons";

import Detalle from "./Detalle";
import { CATEGORIA } from "@/lib/categorias";
import type { Advice, Day, Mode, Stop, Violation } from "@/lib/types";

interface Props {
  day: Day;
  advice: Advice[];
  violations: Violation[];
  mode: Mode;
  /** El id del lugar elegido, o null. */
  selectedStop: string | null;
  onSelectStop: (id: string | null) => void;
}

const hora = (valor: string | null) => (valor ? valor.slice(0, 5) : "");

export default function Linea({
  day,
  advice,
  violations,
  mode,
  selectedStop,
  onSelectStop,
}: Props) {
  const delDia = advice.filter((a) => a.day === day.number);
  const rotas = violations.filter((v) => v.day === day.number);
  /* El icono del traslado sigue al modo del itinerario: caminando o en carro
     no son el mismo dato, y son 40 km o 40 minutos muy distintos. */
  const iconoTraslado = mode === "walking" ? faPersonWalking : faCarSide;

  /*
    Un dia que vuelve al punto de partida tiene el mismo lugar al principio y
    al final, y sin decirlo parece un error de duplicado. Se deduce de las
    paradas en vez de pedirle un campo al backend: que la ultima sea la primera
    ES lo que significa "vuelvo a donde empece".
  */
  const primera = day.stops[0];
  const ultima = day.stops[day.stops.length - 1];
  const vuelveAlInicio =
    day.stops.length > 2 && primera.place.id === ultima.place.id;

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-borde pb-3 text-dato text-tinta-suave">
        <span className="inline-flex items-center gap-1.5">
          <FontAwesomeIcon icon={faClock} aria-hidden className="size-3 text-tinta-tenue" />
          <span className="dato">
            {hora(day.start)}–{hora(day.end)}
          </span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <FontAwesomeIcon icon={faRoute} aria-hidden className="size-3 text-tinta-tenue" />
          <span className="dato">{day.travel_km.toFixed(1)} km</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-tinta-tenue">
          <FontAwesomeIcon icon={faLocationDot} aria-hidden className="size-3" />
          {/*
            La cuenta del backend y no day.stops.length: el punto de partida
            aparece en la lista pero no es una visita, y sumar las pestañas
            tenia que dar el total de la cabecera.
          */}
          {day.visits} {day.visits === 1 ? "parada" : "paradas"}
        </span>
      </div>

      <ol className="relative">
        <AnimatePresence mode="popLayout" initial={false}>
          {day.stops.map((parada, indice) => (
            <motion.li
              /*
                La posicion entra en la clave porque un dia que vuelve al punto
                de partida tiene el mismo lugar dos veces, y dos elementos con
                la misma clave rompen React. El precio es que reordenar una
                parada la vuelve a montar en vez de moverla; se paga solo al
                revisar un dia, y a cambio el viaje de ida y vuelta existe.
              */
              key={`${parada.place.id}-${indice}`}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28, delay: indice * 0.045 }}
              className="grid grid-cols-[3.25rem_1.5rem_1fr] gap-x-2.5 pb-4 last:pb-0 sm:grid-cols-[3.5rem_1.5rem_1fr] sm:gap-x-3 sm:pb-6"
            >
              {/*
                El punto tiene columna propia. La primera version lo colocaba
                con un desplazamiento negativo sobre la columna de la hora y le
                tapaba el ultimo digito: "10:00" se leia "10:0".
              */}
              <span className="dato pt-1 text-right text-menudo text-tinta-suave">
                {hora(parada.arrival)}
              </span>

              <span className="relative flex justify-center">
                <Marca parada={parada} />
                {/* El hilo une las paradas del dia y se corta en la ultima. */}
                {indice < day.stops.length - 1 && (
                  <span
                    aria-hidden
                    className="absolute top-7 bottom-[-1rem] w-px bg-borde sm:bottom-[-1.5rem]"
                  />
                )}
              </span>

              {/*
                El boton envuelve solo la columna del contenido y no la fila
                entera: el detalle trae enlaces, y un enlace dentro de un boton
                es HTML invalido y un lio de accesibilidad. La hora y la marca
                quedan como celdas propias, y asi la columna de la marca sigue
                estirandose con la fila —de eso vive el hilo que une las
                paradas.
              */}
              <div className="min-w-0">
                <button
                  onClick={() =>
                    onSelectStop(
                      parada.place.id === selectedStop ? null : parada.place.id,
                    )
                  }
                  aria-expanded={parada.place.id === selectedStop}
                  className="block w-full text-left"
                >
                <p className="text-cuerpo leading-snug font-medium text-tinta">
                  {parada.place.name}
                </p>
                <p className="mt-0.5 text-dato text-tinta-tenue">
                  {vuelveAlInicio && indice === day.stops.length - 1
                    ? "Regreso al punto de partida"
                    : vuelveAlInicio && indice === 0
                      ? `Salida · ${CATEGORIA[parada.place.category].nombre}`
                      : parada.meal === "lunch"
                        ? "Almuerzo"
                        : parada.meal === "dinner"
                          ? "Cena"
                          : CATEGORIA[parada.place.category].nombre}
                  {/*
                    Sin "hasta las" cuando la parada no dura nada. El punto de
                    partida y el regreso son los dos casos: uno se sale y el
                    otro se llega, y "llega 09:00, hasta las 09:00" se lee como
                    un error de calculo.
                  */}
                  {parada.arrival !== parada.departure && (
                    <>
                      {" · hasta las "}
                      <span className="dato">{hora(parada.departure)}</span>
                    </>
                  )}
                </p>

                {parada.travel_km_from_previous > 0 && (
                  /*
                    Parrafo normal con el icono en linea, no un inline-flex.
                    Como flex, cada trozo era un elemento independiente y
                    envolvia por su cuenta: en un panel angosto salia
                    "1.0 km · 2 / min" en una columna y "desde la parada /
                    anterior" en otra. El texto tiene que fluir como texto.
                  */
                  <p className="mt-2 text-dato text-tinta-tenue">
                    <FontAwesomeIcon
                      icon={iconoTraslado}
                      aria-hidden
                      className="mr-1.5 inline size-3 align-[-0.1em]"
                    />
                    <span className="dato">
                      {parada.travel_km_from_previous.toFixed(1)} km ·{" "}
                      {parada.travel_minutes_from_previous} min
                    </span>{" "}
                    {/*
                      En pantalla angosta la frase se va: envolvia a una
                      segunda linea en cada parada —veinte pixeles por parada,
                      ciento veinte en un dia de seis— y la posicion en la
                      lista ya dice de donde viene el traslado.
                    */}
                    <span className="hidden sm:inline">
                      desde la parada anterior
                    </span>
                  </p>
                )}
                </button>

                {parada.place.id === selectedStop && (
                  <Detalle place={parada.place} />
                )}
              </div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>

      {rotas.map((v, i) => (
        <Nota key={`v-${i}`} icono={faTriangleExclamation} texto={v.detail} />
      ))}

      {/*
        El consejo vive dentro del dia al que pertenece y no en un aviso
        flotante. Enterarse de que hay que llevar almuerzo mientras se mira
        el dia que no lo tiene es lo unico que sirve.
      */}
      {delDia.map((a, i) => (
        <Nota key={`a-${i}`} icono={faLightbulb} texto={a.detail} destacada />
      ))}
    </div>
  );
}

/**
 * La marca de la parada: icono de categoria dentro de un disco de su color.
 *
 * Antes era un punto de color a secas, y el color por si solo no es
 * informacion accesible —quien no distingue el cafe del verde se quedaba sin
 * saber si la parada era un comedor o un cerro. El icono lo dice, y el color
 * pasa a reforzarlo.
 */
function Marca({ parada }: { parada: Stop }) {
  const categoria = CATEGORIA[parada.place.category];
  const icono = parada.meal ? faUtensils : categoria.icono;
  const color = parada.meal ? "var(--cat-food)" : categoria.color;

  return (
    <span
      aria-hidden
      className="grid size-6 shrink-0 place-items-center rounded-full border"
      style={{
        color,
        borderColor: `color-mix(in srgb, ${color} 45%, transparent)`,
        background: `color-mix(in srgb, ${color} 14%, transparent)`,
      }}
    >
      <FontAwesomeIcon icon={icono} className="size-2.5" />
    </span>
  );
}

/** Un aviso del dia: limite incumplido o consejo. */
function Nota({
  icono,
  texto,
  destacada = false,
}: {
  icono: typeof faLightbulb;
  texto: string;
  destacada?: boolean;
}) {
  return (
    <p
      className={`mt-4 flex gap-2.5 text-menudo leading-relaxed text-tinta-suave ${
        destacada
          ? "rounded-md border border-aviso/40 bg-aviso/10 px-3 py-2"
          : "border-l-2 border-aviso pl-3"
      }`}
    >
      <FontAwesomeIcon
        icon={icono}
        aria-hidden
        className="mt-0.5 size-3 shrink-0 text-aviso"
      />
      <span>{texto}</span>
    </p>
  );
}
