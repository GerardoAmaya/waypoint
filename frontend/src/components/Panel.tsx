"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowRight,
  faCheck,
  faCopy,
  faTriangleExclamation,
} from "@fortawesome/free-solid-svg-icons";

import FotoZona from "./FotoZona";
import Linea from "./Linea";
import { itinerarioComoTexto } from "@/lib/texto";
import type { Interpretation, Itinerary } from "@/lib/types";

interface Props {
  interpretation: Interpretation | null;
  itinerary: Itinerary | null;
  selectedDay: number | null;
  onSelectDay: (dia: number) => void;
  onRevise: (mensaje: string) => Promise<void>;
  revising: boolean;
  reviseError: string | null;
  selectedStop: string | null;
  onSelectStop: (id: string | null) => void;
}

const FUENTE: Record<string, string> = {
  estimated: "Distancias estimadas",
  mixed: "Distancias medidas, algunas estimadas",
  real: "Distancias medidas sobre carretera",
};

/*
  Las tres causas piden cosas distintas: configurar algo, esperar, o nada
  porque el lugar de verdad no tiene camino. "Estimadas" a secas las mete en la
  misma bolsa y deja al viajero sin saber si tiene que hacer algo.
*/
const CAUSA: Record<string, string> = {
  no_key: "falta configurar OpenRouteService, así que salen de la línea recta",
  no_quota: "se acabó el cupo diario de rutas, así que salen de la línea recta",
  unroutable:
    "estas paradas están lejos de toda carretera y no se pueden medir, así que salen de la línea recta",
};

export default function Panel({
  interpretation,
  itinerary,
  selectedDay,
  onSelectDay,
  onRevise,
  revising,
  reviseError,
  selectedStop,
  onSelectStop,
}: Props) {
  const [cambio, setCambio] = useState("");
  const [copiado, setCopiado] = useState(false);
  const pestanas = useRef<HTMLDivElement>(null);

  if (!itinerary || !itinerary.days.length) return null;

  const dia =
    itinerary.days.find((d) => d.number === selectedDay) ?? itinerary.days[0];

  const enviar = async () => {
    const texto = cambio.trim();
    if (!texto || revising) return;
    await onRevise(texto);
    setCambio("");
  };

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(
        itinerarioComoTexto(itinerary, interpretation),
      );
      setCopiado(true);
      window.setTimeout(() => setCopiado(false), 2000);
    } catch {
      /* Sin permiso de portapapeles no hay nada que decirle al usuario que
         pueda arreglar; el boton simplemente no confirma. */
    }
  };

  /*
    Flechas entre dias, que es como se navega un grupo de pestanas. Con solo
    tabulador hay que pasar por cada dia para llegar al contenido, y con siete
    dias eso son siete paradas antes del itinerario.
  */
  const teclaEnPestanas = (e: React.KeyboardEvent) => {
    const paso = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!paso) return;
    e.preventDefault();

    const indice = itinerary.days.findIndex((d) => d.number === dia.number);
    const siguiente =
      itinerary.days[
        (indice + paso + itinerary.days.length) % itinerary.days.length
      ];
    onSelectDay(siguiente.number);

    // El foco sigue a la seleccion: si se queda atras, la flecha siguiente
    // vuelve a partir del dia viejo.
    const botones = pestanas.current?.querySelectorAll<HTMLButtonElement>(
      '[role="tab"]',
    );
    botones?.[itinerary.days.indexOf(siguiente)]?.focus();
  };

  return (
    <section className="flex h-full flex-col border-borde-lienzo bg-superficie text-tinta max-lg:border-t lg:border-r">
      {interpretation?.area?.photo && (
        <FotoZona
          photo={interpretation.area.photo}
          areaName={interpretation.area.name}
        />
      )}

      <header className="border-b border-borde px-6 pt-6 pb-4 lg:pt-5">
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-titulo leading-tight font-semibold tracking-tight">
            {interpretation?.area?.name ?? "Tu itinerario"}
          </h1>

          {/*
            Copiar y no descargar: el plan termina en un chat o en una nota, y
            un .txt en la carpeta de descargas del telefono no llega a ninguno
            de los dos lados.
          */}
          <button
            onClick={() => void copiar()}
            className="mt-1 inline-flex shrink-0 items-center gap-1.5 rounded-md border border-borde-fuerte px-2.5 py-1.5 text-dato text-tinta-suave transition-colors hover:border-acento hover:text-tinta"
          >
            <FontAwesomeIcon
              icon={copiado ? faCheck : faCopy}
              aria-hidden
              className="size-3"
            />
            {copiado ? "Copiado" : "Copiar"}
          </button>
        </div>

        <p className="mt-1 text-menudo text-tinta-suave">
          {itinerary.days.length} {itinerary.days.length === 1 ? "día" : "días"} ·{" "}
          {itinerary.total_stops} paradas
        </p>
        <p className="mt-1 text-dato leading-relaxed text-tinta-tenue">
          {FUENTE[itinerary.travel.source]}
          {itinerary.travel.reason && CAUSA[itinerary.travel.reason]
            ? `: ${CAUSA[itinerary.travel.reason]}`
            : ""}
        </p>

        {/*
          Lo que el modelo entendio y no pudo representar se muestra, no se
          descarta. Que el usuario vea que "tranquilo" quedo afuera es mejor
          que dejarlo creer que se tuvo en cuenta.
        */}
        {!!interpretation?.unmapped?.length && (
          <p className="mt-3 border-l-2 border-acento pl-3 text-menudo leading-relaxed text-tinta-suave">
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
        <div
          ref={pestanas}
          role="tablist"
          aria-label="Días del itinerario"
          onKeyDown={teclaEnPestanas}
          className="flex gap-1 border-b border-borde px-6 py-3"
        >
          {itinerary.days.map((d) => {
            const activo = d.number === dia.number;
            return (
              <button
                key={d.number}
                role="tab"
                id={`pestana-dia-${d.number}`}
                aria-selected={activo}
                aria-controls="panel-dia"
                /* Un solo punto de tabulacion para el grupo entero: dentro se
                   navega con flechas. Es el patron de pestanas de ARIA. */
                tabIndex={activo ? 0 : -1}
                onClick={() => onSelectDay(d.number)}
                className={`relative rounded-md px-3 py-1.5 text-menudo transition-colors ${
                  activo ? "text-sobre-acento" : "text-tinta-suave hover:text-tinta"
                }`}
              >
                {/*
                  z-0 y no -z-10: con indice negativo la pildora se va detras
                  del fondo del panel y queda texto niebla sobre panel niebla,
                  que es invisible. El dia activo desaparecia de las pestanas.
                */}
                {activo && (
                  <motion.span
                    layoutId="dia-activo"
                    className="absolute inset-0 z-0 rounded-md bg-acento"
                    transition={{ type: "spring", stiffness: 380, damping: 32 }}
                  />
                )}
                <span className="relative z-10">Día {d.number}</span>
              </button>
            );
          })}
        </div>
      )}

      <div
        id="panel-dia"
        role={itinerary.days.length > 1 ? "tabpanel" : undefined}
        aria-labelledby={
          itinerary.days.length > 1 ? `pestana-dia-${dia.number}` : undefined
        }
        className="flex-1 overflow-y-auto px-6 py-6"
      >
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
              /* El modo del dia, no el del itinerario: pueden diferir. */
              mode={dia.mode}
              selectedStop={selectedStop}
              onSelectStop={onSelectStop}
            />
          </motion.div>
        </AnimatePresence>

        {itinerary.violations
          .filter((v) => v.day === null)
          .map((v, i) => (
            <p
              key={i}
              className="mt-6 flex gap-2.5 border-l-2 border-aviso pl-3 text-menudo text-tinta-suave"
            >
              <FontAwesomeIcon
                icon={faTriangleExclamation}
                aria-hidden
                className="mt-0.5 size-3 shrink-0 text-aviso"
              />
              <span>{v.detail}</span>
            </p>
          ))}
      </div>

      <footer className="border-t border-borde px-6 py-4">
        <label htmlFor="revisar" className="text-dato text-tinta-tenue">
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
            className="min-w-0 flex-1 rounded-md border border-borde-fuerte bg-superficie-alta px-3 py-2 text-menudo text-tinta transition-colors placeholder:text-tinta-tenue focus:border-acento disabled:opacity-60"
          />
          <button
            onClick={() => void enviar()}
            disabled={revising || !cambio.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-acento px-4 py-2 text-menudo text-sobre-acento transition-opacity disabled:opacity-40"
          >
            {revising ? "Rehaciendo" : "Aplicar"}
            {!revising && (
              <FontAwesomeIcon icon={faArrowRight} aria-hidden className="size-3" />
            )}
          </button>
        </div>
        {reviseError && (
          <p className="mt-2 text-dato leading-relaxed text-aviso">{reviseError}</p>
        )}
      </footer>
    </section>
  );
}
