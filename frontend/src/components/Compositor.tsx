"use client";

import { useEffect, useRef } from "react";
import { motion } from "motion/react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faArrowTurnUp,
  faRoute,
  faTriangleExclamation,
} from "@fortawesome/free-solid-svg-icons";

import Pais from "./Pais";

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
/*
  La caja arranca con una peticion escrita y no vacia.

  Un area de texto en blanco con una sugerencia gris pide que uno redacte
  desde cero, y quien llega no sabe todavia cuanto entiende esto: si escribe
  "dos dias" se lleva lo que da un prompt de dos palabras y concluye que no da
  para mas. Con la peticion puesta, el primer resultado que ve es el del
  planificador trabajando con todo lo que sabe leer —alojamiento de partida,
  hora de inicio, modo por dia, comidas, hora de regreso—, y el boton se puede
  pulsar sin escribir nada.

  El precio es que para escribir lo propio hay que borrar esto primero. Se
  paga una vez y a cambio la pantalla ensena su techo en vez de su suelo.
*/
/*
  La petición que ya viene escrita al abrir el compositor.

  **Es la que más trabaja de toda la interfaz**, porque nadie lee una lista de
  capacidades: se ve un ejemplo y se entiende de qué es capaz esto. Por eso
  lleva siete cosas a la vez —fecha, punto de partida, dos días, hora de
  inicio, un modo distinto por día, cena nombrada y hora de regreso— y no una
  frase bonita y vacía.

  Bajó de 46 palabras a 32 sin perder ninguna de las siete: la versión larga
  decía "me estoy hospedando en", "quiero un itinerario de", "realizaré cena en
  los 2 viajes", y ninguna de esas vueltas agregaba un rasgo. Lo que sí ganó
  fue la fecha, que antes no estaba y ahora arrastra el clima y los horarios de
  apertura.

  **No se puede recortar "y vuelvo antes de las 11", aunque lo parezca.** Esa
  cláusula lleva dos cosas: que el día cierre en el hotel y que el tope sean
  las 23:00. Sin ella el segundo día termina a las 15:11 y se queda sin la cena
  que la misma frase pide, así que el ejemplo se contradice solo.
*/
export const PETICION_INICIAL =
  "Dos días desde el Hotel Barceló a partir del sábado a las 10, el primero en carro y el segundo a pie, ceno los dos días y vuelvo antes de las 11";

/*
  Los tres tocan cosas distintas a propósito: hablar en vago —"odio
  madrugar"—, nombrar un lugar concreto y una fecha, y decir de dónde se sale.
  Tres variantes de lo mismo no enseñarían nada.
*/
const EJEMPLOS = [
  "Tres días por la Ruta de las Flores, odio madrugar",
  "El sábado en Santa Ana, quiero subir al volcán",
  "Dos días saliendo desde Santa Tecla, en carro",
];

interface Props {
  fase: Fase;
  error: string | null;
  onSubmit: (mensaje: string) => void;
  /*
    El texto vive en la pagina y no aca.

    Esta caja se desmonta en cuanto llega el plan —la pantalla pasa a ser del
    itinerario— y al volver con "Empezar de nuevo" se montaba otra nueva, con
    la peticion de ejemplo puesta donde estaba la tuya. Volver atras es casi
    siempre para retocar lo que pediste, no para escribirlo de cero.

    Sobrevive al viaje de ida y vuelta al itinerario, y no a un recargado de
    pagina, que es exactamente donde no queremos que sobreviva: encontrarse la
    peticion de la semana pasada esperando seria mas raro que util.
  */
  texto: string;
  onTextoChange: (texto: string) => void;
}

export default function Compositor({
  fase,
  error,
  onSubmit,
  texto,
  onTextoChange,
}: Props) {
  const caja = useRef<HTMLTextAreaElement>(null);
  const trabajando = fase !== "quieto" && fase !== "listo";

  /*
    La caja crece con lo que tiene dentro.

    Con tres filas fijas, la peticion inicial entraba en 5 lineas en escritorio
    y en 10 en un telefono de 360 px: mas de la mitad quedaba detras de un
    desplazamiento interno, en una caja sin asa de redimensionar. Un texto
    puesto de antemano que no se ve entero no ensena nada.

    Donde hay field-sizing lo hace el CSS, que acierta ya en el primer cuadro y
    no da salto. Donde no lo hay —Firefox al escribir esto— queda este efecto,
    que es lo mismo medido a mano. El alto vuelve a "auto" antes de leer
    scrollHeight porque si no, al borrar texto la caja no sabe encogerse.
  */
  useEffect(() => {
    const el = caja.current;
    if (!el || CSS.supports("field-sizing", "content")) return;

    const ajustar = () => {
      el.style.height = "auto";
      // scrollHeight no cuenta los bordes y la caja mide en border-box: sin
      // sumarlos quedan 2 px de menos y con ellos una barra de un pelo.
      const estilo = getComputedStyle(el);
      const bordes =
        parseFloat(estilo.borderTopWidth) + parseFloat(estilo.borderBottomWidth);
      el.style.height = `${el.scrollHeight + bordes}px`;
    };
    ajustar();
    // El ancho de la columna cambia con la ventana, y con el ancho cambia
    // donde parte cada linea.
    window.addEventListener("resize", ajustar);
    return () => window.removeEventListener("resize", ajustar);
  }, [texto]);

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

      Alto maximo y desplazamiento propio porque el contenido crece y la ventana
      no: en un telefono de 568 px de alto la tarjeta pedia 618 px y el titulo
      salia por arriba del viewport, sin barra que avisara. Acotarla a la altura
      disponible hace que sobre ella misma se desplace lo que no entra, en vez
      de recortarse. Es el mismo desborde que ya arreglo el clamp del titular,
      que volvio cuando el texto se alargo.
    */
    <div className="max-h-[calc(100dvh-3rem)] w-full max-w-2xl overflow-y-auto rounded-xl border border-borde-fuerte bg-superficie/94 px-6 py-7 shadow-panel backdrop-blur-sm sm:px-8 sm:py-9">
      <Pais />

      {/*
        Interlineado 1.02 y no 0.92: el 0.92 venia de un titular de dos lineas
        cortas, donde apretarlas las agrupaba. Sobre una frase que envuelve, un
        interlineado menor que el cuerpo de la letra deja los ascendentes de la
        segunda linea tocando la primera.
      */}
      <h1 className="mt-3 text-obra leading-[1.02] font-light tracking-tight text-balance text-tinta">
        Explorá El Salvador
      </h1>
      {/*
        Sin medida propia: la entradilla ocupa la columna entera.

        Con max-w-md se acotaba a 448 px dentro de una columna de 608, y la
        tarjeta terminaba con tres bordes derechos distintos —el area de texto
        en 606, el titular en 474, la entradilla en 437—: un escalon que se lee
        como un hueco y no como una sangria. A la anchura de la columna son 28
        em, unos 56 caracteres por linea, que sigue estando dentro de la medida
        comoda de lectura, y el borde derecho vuelve a ser uno.

        text-pretty en la entradilla y text-balance en el titular por lo mismo
        desde el otro lado: el reparto lo decide el navegador y no el azar del
        largo del texto, que aqui cambia.

        Tamano de cuerpo en el telefono y de entradilla desde sm: a 17.6 px en
        una columna de 264 px esto se convierte en un bloque de lineas cortas y
        deja de leerse como una entrada. En pantalla ancha hay sitio y la
        jerarquia se sostiene, asi que ahi se queda grande.
      */}
      <p className="mt-4 text-cuerpo leading-relaxed font-light text-pretty text-tinta-suave sm:mt-5 sm:text-guia sm:leading-snug">
          Descubrí los mejores lugares según tus preferencias y te armamos el recorrido ideal. Decinos cuántos días tenés, dónde comenzás, cómo te transportás y si querés incluir comidas. ¡Nosotros nos encargamos del resto!
      </p>

      <div className="mt-6 sm:mt-8">
        <textarea
          ref={caja}
          aria-label="Contá el viaje que querés hacer"
          value={texto}
          onChange={(e) => onTextoChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              enviar();
            }
          }}
          disabled={trabajando}
          rows={3}
          placeholder="dos días por el occidente, sin madrugar"
          className="max-h-[50dvh] w-full resize-none rounded-lg border border-borde-fuerte bg-superficie-alta px-4 py-3.5 text-cuerpo leading-relaxed text-tinta transition-colors field-sizing-content placeholder:text-tinta-tenue focus:border-acento disabled:opacity-60"
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
                      onClick={() => onTextoChange(ejemplo)}
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

            </div>
          )
        )}
      </div>
    </div>
  );
}
