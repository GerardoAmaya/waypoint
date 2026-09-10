"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowRight,
  faCheck,
  faChevronDown,
  faCopy,
  faPenToSquare,
  faTriangleExclamation,
} from "@fortawesome/free-solid-svg-icons";

import Asa from "./Asa";
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
  expandido: boolean;
  onToggleExpandido: () => void;
  /**
   * Si el itinerario en pantalla es el borrador y las rutas se siguen midiendo.
   *
   * **El indicador de progreso vivia en el compositor, que se desmonta justo
   * cuando empieza a hacer falta.** El borrador llega sin tocar la red y ya es
   * un itinerario completo, asi que la pantalla pasa a ser del panel; dos
   * segundos despues llegan las distancias reales y el mapa cambia las rectas
   * por el trazo por carretera. Sin avisar, ese cambio se lee como un fallo.
   *
   * En 9 de 11 casos medidos solo cambian las lineas. En los otros dos cambian
   * las paradas, porque las distancias reales no son las estimadas y el dia se
   * rehace: mas razon para decir que todavia no esta firme.
   */
  midiendo: boolean;
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
  expandido,
  onToggleExpandido,
  midiendo,
}: Props) {
  const [cambio, setCambio] = useState("");
  const [copiado, setCopiado] = useState(false);
  /*
    En pantalla angosta el pie de revision empieza cerrado. Medido: se llevaba
    102 px de los 429 del panel, permanentes, por un campo que se usa de vez en
    cuando. En pantalla ancha no cuesta nada y queda abierto.
  */
  const [revisionAbierta, setRevisionAbierta] = useState(false);
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
      <Asa expandido={expandido} onToggle={onToggleExpandido} />

      {interpretation?.area?.photo && (
        <FotoZona
          photo={interpretation.area.photo}
          areaName={interpretation.area.name}
        />
      )}

      <header className="border-b border-borde px-5 pt-2 pb-3 sm:px-6 sm:pt-6 sm:pb-4 lg:pt-5">
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

        {/*
          Expandido en pantalla angosta la cabecera se queda con lo que
          identifica al panel y suelta el resto. No se pierde nada: es lo que
          se lee de un vistazo al abrirlo, y colapsandolo vuelve. Son noventa
          pixeles, que en un telefono son dos paradas mas del itinerario.
        */}
        <p
          className={`mt-1 text-menudo text-tinta-suave lg:block ${
            expandido ? "hidden" : ""
          }`}
        >
          {itinerary.days.length} {itinerary.days.length === 1 ? "día" : "días"} ·{" "}
          {itinerary.total_stops} paradas
        </p>
        <p
          className={`mt-1 text-dato leading-relaxed text-tinta-tenue lg:block ${
            expandido ? "hidden" : ""
          }`}
        >
          {midiendo ? (
            <span className="inline-flex items-center gap-1.5" role="status">
              <motion.span
                aria-hidden
                className="inline-block size-1.5 rounded-full bg-acento"
                animate={{ opacity: [1, 0.25, 1] }}
                transition={{ duration: 1.4, repeat: Infinity }}
              />
              Midiendo las rutas por carretera…
            </span>
          ) : (
            <>
              {FUENTE[itinerary.travel.source]}
              {itinerary.travel.reason && CAUSA[itinerary.travel.reason]
                ? `: ${CAUSA[itinerary.travel.reason]}`
                : ""}
            </>
          )}
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
          className="flex shrink-0 gap-1 border-b border-borde px-5 py-2 sm:px-6 sm:py-3"
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
        className="flex-1 overflow-y-auto px-5 py-4 sm:px-6 sm:py-6"
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

      <footer className="shrink-0 border-t border-borde px-6 py-3 lg:py-4">
        {/*
          Cerrado es un boton de una linea; abierto es el campo. En pantalla
          ancha nunca esta cerrado, asi que el desplegable no molesta ahi.
        */}
        <button
          onClick={() => setRevisionAbierta((v) => !v)}
          aria-expanded={revisionAbierta}
          aria-controls="revisar"
          className="flex w-full items-center gap-2 text-left text-dato text-tinta-tenue transition-colors hover:text-tinta lg:hidden"
        >
          <FontAwesomeIcon
            icon={revisionAbierta ? faChevronDown : faPenToSquare}
            aria-hidden
            className="size-3"
          />
          Cambiar el día {dia.number}
        </button>

        <label
          htmlFor="revisar"
          className="hidden text-dato text-tinta-tenue lg:block"
        >
          Cambiar el día {dia.number}
        </label>

        <div
          className={`mt-2 gap-2 lg:flex ${revisionAbierta ? "flex" : "hidden"}`}
        >
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
