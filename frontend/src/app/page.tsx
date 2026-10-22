"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRotateLeft } from "@fortawesome/free-solid-svg-icons";

import Compositor, {
  PETICION_INICIAL,
  type Fase,
} from "@/components/Compositor";
import Fondo from "@/components/Fondo";
import Leyenda from "@/components/Leyenda";
import Panel from "@/components/Panel";
import Tema from "@/components/Tema";
import { fetchCompartido, fetchField, reviseDay, streamPlan } from "@/lib/api";
import { leer, olvidar, recordar, type Reciente } from "@/lib/recientes";
import type { Fondo as FondoId, ParadaElegida } from "@/components/Mapa";
import type { Constraints, Interpretation, Itinerary } from "@/lib/types";

// Leaflet toca window al importarse, asi que el mapa no puede renderizarse en
// el servidor.
const Mapa = dynamic(() => import("@/components/Mapa"), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-superficie-mapa" />,
});

export default function Home() {
  const [field, setField] = useState<[number, number][]>([]);
  const [fondo, setFondo] = useState<FondoId>("mapa");
  const [fase, setFase] = useState<Fase>("quieto");
  /*
    La peticion escrita vive aca y no dentro del compositor porque el
    compositor se desmonta cuando llega el plan: ahi se perdia lo que la
    persona habia escrito, y al volver se encontraba el ejemplo. Ver Props en
    Compositor.
  */
  const [peticion, setPeticion] = useState(PETICION_INICIAL);
  const [interpretacion, setInterpretacion] = useState<Interpretation | null>(
    null,
  );
  const [itinerario, setItinerario] = useState<Itinerary | null>(null);
  const [diaActivo, setDiaActivo] = useState<number | null>(null);
  /*
    La parada elegida lleva de donde salio la eleccion, y no es un detalle: si
    vino del panel el mapa tiene que volar hasta ella, y si vino de un pin ya
    esta a la vista y volar seria moverle el mapa a alguien que acaba de
    apuntar con el dedo.
  */
  const [parada, setParada] = useState<ParadaElegida | null>(null);
  /*
    El panel arrastrable, solo en pantalla angosta. Vive aca y no dentro de
    Panel porque lo que cambia es la altura del <aside>, que es de la pagina.
  */
  const [panelExpandido, setPanelExpandido] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revisando, setRevisando] = useState(false);
  const [errorRevision, setErrorRevision] = useState<string | null>(null);
  const aborto = useRef<AbortController | null>(null);
  /*
    La lista vive en estado ademas de en localStorage porque la pantalla de
    entrada tiene que repintarse cuando cambia: armar un plan la suma, y
    quitar uno la resta, sin recargar.
  */
  const [recientes, setRecientes] = useState<Reciente[]>([]);

  const abrirCompartido = useCallback(async (codigo: string) => {
    setFase("leyendo");
    setError(null);
    try {
      const guardado = await fetchCompartido(codigo);
      setInterpretacion(guardado.interpretation);
      setItinerario(guardado.itinerary);
      setDiaActivo(guardado.itinerary.days[0]?.number ?? null);
      setFase("listo");
    } catch (e) {
      setError((e as Error).message);
      setFase("quieto");
      // Un código que no existe no deja la URL colgada apuntando a nada.
      window.history.replaceState({}, "", "/");
      /*
        Y se saca de la lista: si el servidor ya no lo tiene, dejarlo ahi es
        ofrecer una puerta que no abre. Solo por no encontrarlo, no por un
        fallo de red —esa distincion la hace fetchCompartido con el 404.
      */
      if ((e as Error).message.includes("no existe")) {
        olvidar(codigo);
        setRecientes(leer());
      }
    }
  }, []);

  useEffect(() => {
    fetchField()
      .then(setField)
      .catch(() => setField([]));

    /*
      La lista de recientes se lee al montar y no en el primer render: en el
      servidor no hay localStorage, y leerlo durante el render daria una
      pantalla distinta de la que el servidor acaba de mandar.

      El desactivado de la regla cubre este efecto entero, incluido el
      abrirCompartido de mas abajo: los dos son cargas de arranque, no bucles
      de render.
    */
    /* eslint-disable-next-line react-hooks/set-state-in-effect */
    setRecientes(leer());

    /*
      La ruta /i/<codigo> abre un itinerario guardado. Se lee de la URL y no de
      una prop porque la misma pantalla sirve para los dos casos: armar uno
      nuevo y abrir uno compartido.
    */
    const codigo = window.location.pathname.match(/^\/i\/([a-z0-9]+)$/)?.[1];
    /*
      Montar la pantalla con un itinerario que viene de la URL es una carga, y
      el indicador de "leyendo" solo sirve si aparece antes de esperar a la
      red. El desactivado de la regla esta arriba, en setRecientes.
    */
    if (codigo) void abrirCompartido(codigo);

    /*
      El botón atrás: volver a "/" limpia la pantalla, y volver a un /i/<codigo>
      reabre ese itinerario. Sin esto, atrás cambiaba la URL y dejaba el
      itinerario anterior puesto.
    */
    const alNavegar = () => {
      const destino = window.location.pathname.match(/^\/i\/([a-z0-9]+)$/)?.[1];
      if (destino) {
        abrirCompartido(destino);
        return;
      }
      aborto.current?.abort();
      setItinerario(null);
      setInterpretacion(null);
      setDiaActivo(null);
      setParada(null);
      setError(null);
      setFase("quieto");
    };
    window.addEventListener("popstate", alNavegar);

    return () => {
      aborto.current?.abort();
      window.removeEventListener("popstate", alNavegar);
    };
  }, [abrirCompartido]);

  const armar = useCallback(async (mensaje: string) => {
    aborto.current?.abort();
    const control = new AbortController();
    aborto.current = control;

    setError(null);
    setItinerario(null);
    setInterpretacion(null);
    setDiaActivo(null);
    setParada(null);
    setFase("leyendo");

    /*
      La interpretacion tambien en una variable y no solo en el estado: la
      necesita la rama "plan" de mas abajo, y leerla de `interpretacion` ahi
      daria el valor con el que se creo esta funcion, no el que acaba de
      llegar. Es el mismo stream, asi que la variable siempre va al dia.
    */
    let interpretado: Interpretation | null = null;

    try {
      for await (const evento of streamPlan(mensaje, control.signal)) {
        switch (evento.phase) {
          case "interpretation":
            interpretado = evento.data;
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
            setDiaActivo(
              (actual) => actual ?? evento.data.days[0]?.number ?? null,
            );
            break;
          case "plan":
            setItinerario(evento.data);
            setFase("listo");
            /*
              La URL pasa a ser la del itinerario en cuanto existe. Dos cosas
              a la vez: compartir es copiar la barra de direcciones, y el botón
              atrás del navegador vuelve a la pantalla de inicio en vez de
              salirse del sitio, que era una queja aparte.
            */
            if (evento.data.share_code) {
              window.history.pushState({}, "", `/i/${evento.data.share_code}`);
              /*
                Y se recuerda, para que el plan no se pierda al cerrar la
                pestaña. Se guarda el codigo y nada mas: el contenido ya esta
                en la base. Ver lib/recientes.ts.
              */
              recordar({
                codigo: evento.data.share_code,
                zona: interpretado?.area?.name ?? "Tu itinerario",
                dias: evento.data.days.length,
                paradas: evento.data.total_stops,
                guardado: new Date().toISOString(),
              });
              setRecientes(leer());
            }
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
        // El dia se rehizo: la parada elegida puede ya no estar en el.
        setParada(null);
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
    setParada(null);
    setPanelExpandido(false);
    setError(null);
    setFase("quieto");
  }, []);

  const conPlan = Boolean(itinerario?.days.length);

  return (
    /*
      La regla de prefers-reduced-motion en globals.css no alcanza a Motion:
      Motion escribe sus valores en el estilo del elemento desde JS, y ahi una
      duracion de transicion en CSS no interviene. Sin esto, el piso de calidad
      del PLAN.md quedaba declarado y a medio cumplir.
    */
    <MotionConfig reducedMotion="user">
      <main className="flex h-dvh flex-col overflow-hidden lg:flex-row">
        <div
          className={`relative order-1 min-h-0 flex-1 lg:order-2 ${
            panelExpandido ? "waypoint-mapa-encogido" : ""
          }`}
        >
          <Mapa
            fondo={fondo}
            field={field}
            days={itinerario?.days ?? []}
            selectedDay={diaActivo}
            travelSource={itinerario?.travel.source ?? null}
            onSelectDay={setDiaActivo}
            parada={parada}
            onSelectStop={(id) => setParada({ id, origen: "mapa" })}
          />

          {/*
            El foco suave del estado vacio, que se retira con el plan. Va aca y
            no dentro de Mapa porque no es asunto del mapa: es la jerarquia de
            la pantalla. Ver waypoint-desenfoque en globals.css.
          */}
          <div
            className="waypoint-desenfoque"
            data-nitido={conPlan}
            aria-hidden
          />

          {/*
            z-[1000] no es un numero magico: los paneles de Leaflet van de 200 a
            700 y sus controles a 800. Sin un indice explicito, esta capa queda
            por debajo del mapa y no se ve nada. Es el bug que dejo la primera
            version sin compositor en pantalla.
          */}

          {/*
            Antes de que haya plan, la caja vive sobre el mapa y el pais es el
            fondo. Cuando el plan llega, se retira y la pantalla pasa a ser del
            itinerario: lo unico que queda arriba es el cromo de la esquina.
          */}
          {!conPlan && (
            <div className="pointer-events-none absolute inset-0 z-[1000] flex items-center justify-center p-6">
              <div className="pointer-events-auto">
                <Compositor
                  fase={fase}
                  error={error}
                  texto={peticion}
                  onTextoChange={setPeticion}
                  onSubmit={(m) => void armar(m)}
                  recientes={recientes}
                  onAbrirReciente={(codigo) => {
                    /*
                      La URL cambia tambien: abrir uno de la lista tiene que
                      dejar la pantalla igual que si el enlace hubiera llegado
                      de afuera, con su direccion y su botón atrás.
                    */
                    window.history.pushState({}, "", `/i/${codigo}`);
                    void abrirCompartido(codigo);
                  }}
                  onOlvidarReciente={(codigo) => {
                    olvidar(codigo);
                    setRecientes(leer());
                  }}
                />
              </div>
            </div>
          )}

          {/*
            El cromo de la esquina: tema siempre, reinicio solo con plan. Va
            despues del compositor en el DOM a proposito: los dos estan en
            z-1000 y ahi gana el ultimo, asi que el interruptor de tema queda
            alcanzable aunque la tarjeta del estado vacio le pase por encima.
          */}
          <div className="absolute top-4 right-4 z-[1000] flex items-center gap-2">
            {conPlan && (
              <button
                onClick={reiniciar}
                className="inline-flex items-center gap-2 rounded-full border border-borde-fuerte bg-superficie/92 px-4 py-2 text-menudo text-tinta shadow-panel backdrop-blur transition-colors hover:border-acento"
              >
                <FontAwesomeIcon
                  icon={faRotateLeft}
                  aria-hidden
                  className="size-3"
                />
                Empezar de nuevo
              </button>
            )}
            <Tema />
          </div>

          {/*
            Los controles del mapa, abajo a la izquierda: el zoom de Leaflet
            esta abajo a la derecha y arriba a la derecha vive el cromo de la
            aplicacion.
          */}
          <div
            className={`absolute bottom-4 left-4 z-[1000] flex max-w-[min(22rem,calc(100%-2rem))] flex-col items-start gap-2 lg:flex ${
              panelExpandido ? "hidden" : "flex"
            }`}
          >
            <Fondo fondo={fondo} onChange={setFondo} />
            {conPlan && itinerario && (
              <div className="hidden lg:block">
                <Leyenda days={itinerario.days} />
              </div>
            )}
          </div>
        </div>

        {/*
          El momento en que el plan aterriza es visual, y quien usa lector de
          pantalla no lo recibia: el mapa es role="application" y el panel
          entraba sin anunciarse. Una linea, y una sola vez por plan.
        */}
        <p aria-live="polite" className="sr-only">
          {conPlan && itinerario
            ? `Itinerario listo: ${itinerario.days.length} ${
                itinerario.days.length === 1 ? "día" : "días"
              }, ${itinerario.total_stops} paradas.`
            : ""}
        </p>

        <AnimatePresence>
          {conPlan && (
            <motion.aside
              key="panel"
              initial={{ opacity: 0, x: -24 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -24 }}
              transition={{ type: "spring", stiffness: 260, damping: 30 }}
              /*
              La transicion va en CSS y no en Motion para que la regla de
              prefers-reduced-motion la alcance: ahi el panel salta a su sitio
              en vez de hacer esperar a quien pidio no esperar.

              Expandido deja el mapa asomando: sin esa franja, el panel a
              pantalla completa parece otra pantalla y se pierde de donde vino.
            */
              className={`order-2 w-full shrink-0 transition-[height] duration-300 ease-out lg:order-1 lg:h-auto lg:w-[27rem] lg:transition-none ${
                panelExpandido ? "h-[88dvh]" : "h-[55dvh]"
              }`}
            >
              <Panel
                interpretation={interpretacion}
                itinerary={itinerario}
                selectedDay={diaActivo}
                onSelectDay={setDiaActivo}
                onRevise={revisar}
                revising={revisando}
                reviseError={errorRevision}
                midiendo={fase === "midiendo"}
                expandido={panelExpandido}
                onToggleExpandido={() => setPanelExpandido((v) => !v)}
                selectedStop={parada?.id ?? null}
                onSelectStop={(id) =>
                  setParada(id ? { id, origen: "panel" } : null)
                }
              />
            </motion.aside>
          )}
        </AnimatePresence>
      </main>
    </MotionConfig>
  );
}
