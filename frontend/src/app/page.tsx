"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

import Compositor, { type Fase } from "@/components/Compositor";
import Panel from "@/components/Panel";
import { fetchField, reviseDay, streamPlan } from "@/lib/api";
import type { Constraints, Interpretation, Itinerary } from "@/lib/types";

// Leaflet toca window al importarse, asi que el mapa no puede renderizarse en
// el servidor.
const Mapa = dynamic(() => import("@/components/Mapa"), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-basalto" />,
});

export default function Home() {
  const [field, setField] = useState<[number, number][]>([]);
  const [fase, setFase] = useState<Fase>("quieto");
  const [interpretacion, setInterpretacion] = useState<Interpretation | null>(null);
  const [itinerario, setItinerario] = useState<Itinerary | null>(null);
  const [diaActivo, setDiaActivo] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revisando, setRevisando] = useState(false);
  const [errorRevision, setErrorRevision] = useState<string | null>(null);
  const aborto = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchField().then(setField).catch(() => setField([]));
    return () => aborto.current?.abort();
  }, []);

  const armar = useCallback(async (mensaje: string) => {
    aborto.current?.abort();
    const control = new AbortController();
    aborto.current = control;

    setError(null);
    setItinerario(null);
    setInterpretacion(null);
    setDiaActivo(null);
    setFase("leyendo");

    try {
      for await (const evento of streamPlan(mensaje, control.signal)) {
        switch (evento.phase) {
          case "interpretation":
            setInterpretacion(evento.data);
            setFase("eligiendo");
            break;
          case "candidates":
            setFase("midiendo");
            break;
          case "draft":
            // El borrador ya es un itinerario completo: si ORS falla o se acabo
            // el cupo, esto es lo que queda en pantalla, y es usable.
            setItinerario(evento.data);
            setDiaActivo((actual) => actual ?? evento.data.days[0]?.number ?? null);
            break;
          case "plan":
            setItinerario(evento.data);
            setFase("listo");
            break;
          case "error":
            setError(evento.data.message);
            setFase("quieto");
            break;
        }
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError("Se cortó la conexión con el planificador.");
      setFase("quieto");
    }
  }, []);

  const revisar = useCallback(
    async (mensaje: string) => {
      if (!itinerario || !interpretacion?.constraints || !diaActivo) return;
      setRevisando(true);
      setErrorRevision(null);
      try {
        const resultado = await reviseDay(
          mensaje,
          diaActivo,
          interpretacion.constraints as Constraints,
          itinerario.days,
        );
        setItinerario(resultado.itinerary);
      } catch (e) {
        setErrorRevision((e as Error).message);
      } finally {
        setRevisando(false);
      }
    },
    [itinerario, interpretacion, diaActivo],
  );

  const reiniciar = useCallback(() => {
    aborto.current?.abort();
    setItinerario(null);
    setInterpretacion(null);
    setDiaActivo(null);
    setError(null);
    setFase("quieto");
  }, []);

  const conPlan = Boolean(itinerario?.days.length);

  return (
    <main className="flex h-dvh flex-col overflow-hidden lg:flex-row">
      <div className="relative min-h-0 flex-1 order-1 lg:order-2">
        <Mapa
          field={field}
          days={itinerario?.days ?? []}
          selectedDay={diaActivo}
          travelSource={itinerario?.travel.source ?? null}
          onSelectDay={setDiaActivo}
        />

        {/*
          Antes de que haya plan, la caja vive sobre el mapa y el pais es el
          fondo. Cuando el plan llega, se retira a un boton en la esquina: la
          pantalla pasa a ser del itinerario.
        */}
        {/*
          z-[1000] no es un numero magico: los paneles de Leaflet van de 200 a
          700 y sus controles a 800. Sin un indice explicito, esta capa queda
          por debajo del mapa y no se ve nada. Es el bug que dejo la primera
          version sin compositor en pantalla.
        */}
        <div
          className={`pointer-events-none absolute inset-0 z-[1000] flex ${
            conPlan
              ? "items-start justify-end p-4"
              : "items-center justify-center bg-basalto/55 p-6 backdrop-blur-[2px]"
          }`}
        >
          <div className="pointer-events-auto">
            <Compositor
              fase={fase}
              error={error}
              compacto={conPlan}
              onSubmit={(m) => void armar(m)}
              onReset={reiniciar}
            />
          </div>
        </div>
      </div>

      <AnimatePresence>
        {conPlan && (
          <motion.aside
            key="panel"
            initial={{ opacity: 0, x: -24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ type: "spring", stiffness: 260, damping: 30 }}
            className="order-2 h-[55dvh] w-full shrink-0 lg:order-1 lg:h-auto lg:w-[27rem]"
          >
            <Panel
              interpretation={interpretacion}
              itinerary={itinerario}
              selectedDay={diaActivo}
              onSelectDay={setDiaActivo}
              onRevise={revisar}
              revising={revisando}
              reviseError={errorRevision}
            />
          </motion.aside>
        )}
      </AnimatePresence>
    </main>
  );
}
