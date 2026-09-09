"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { FieldLayer } from "./FieldLayer";
import { CATEGORIA } from "@/lib/categorias";
import { leerMateriales, type Material, type Materiales } from "@/lib/paleta";
import type { Category, Day, TravelSourceKind } from "@/lib/types";

/**
 * OpenStreetMap en sus colores, sin filtros.
 *
 * Hubo una version oscurecida por CSS y otra con las teselas de CARTO. Las dos
 * peleaban con el mapa en vez de dejarlo hablar: el filtro sacaba parques verde
 * oliva y carreteras salmon, y CARTO pasó a exigir llave.
 *
 * El mapa natural ya distingue bosque de ciudad, río de carretera y montaña de
 * llano. Eso es informacion que costaria mucho reconstruir, y taparla para que
 * combine con una paleta es cambiar dato por decoracion. El color propio del
 * proyecto va en los pines, el trazo y el panel.
 *
 * Por lo mismo el mapa no sigue al tema: no hay tesela oscura que conserve esa
 * informacion. El cromo que flota encima si lo sigue.
 */
export type Fondo = "mapa" | "satelite";

/**
 * La parada elegida y de donde salio la eleccion.
 *
 * El origen decide si el mapa vuela: desde el panel hay que ir a buscarla,
 * desde un pin ya esta en pantalla y volar seria moverle el mapa a alguien que
 * acaba de apuntar con el dedo.
 */
export interface ParadaElegida {
  id: string;
  origen: "panel" | "mapa";
}

const TESELAS: Record<Fondo, { url: string; credito: string; maxZoom: number }> = {
  mapa: {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    credito:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18,
  },
  /*
    El satelite es una capa opcional, nunca la de partida.

    Sirve para algo que el mapa dibujado no puede decir: si un mirador esta de
    verdad sobre una cresta, o si un "parque" es bosque o potrero. Pero encima
    de una foto aerea el trazo anil se pierde y los nombres de los pueblos
    desaparecen, asi que como fondo por defecto seria un retroceso.

    Esri World Imagery responde sin llave, que es la razon por la que esta esta
    y no Mapbox o Stadia: el proyecto ya rechazo las teselas con llave, y en un
    mapa de cliente la llave viaja en el HTML y cualquiera puede gastarte el
    cupo. La atribucion la exige su licencia.
  */
  satelite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    credito:
      'Imágenes &copy; <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics',
    maxZoom: 19,
  },
};

/** El Salvador entero, que es el encuadre de arranque. */
const PAIS = L.latLngBounds([13.1, -90.15], [14.45, -87.65]);

/**
 * Encuadra el pais llenando el contenedor, no cabiendo dentro de el.
 *
 * El Salvador mide 2.5 grados de ancho por 1.35 de alto, o sea que es casi el
 * doble de ancho que de alto. `fitBounds` garantiza que el rectangulo entre
 * completo, asi que en una pantalla vertical de telefono resolvia la diferencia
 * mostrando latitud de sobra: el pais quedaba como una franja en medio y arriba
 * se veia Belice. El estado vacio existe para mostrar donde esta el material, y
 * ahi mostraba el pais equivocado.
 *
 * `getBoundsZoom(bounds, true)` da el zoom al que el rectangulo *cubre* el
 * contenedor. El pais llena la pantalla y lo que sobra se recorta por el lado
 * largo, que es lo contrario de lo que hacia y lo que uno espera de un mapa a
 * pantalla completa.
 */
function zoomDelPais(map: L.Map): number {
  return map.getBoundsZoom(PAIS, true);
}

/*
  El guion del trazo estimado. Vive aca y no suelto en la llamada porque
  globals.css lo selecciona por su valor exacto para no animarlo: ahi el
  dasharray es el dato, y animarlo lo borraria. Si cambia, cambia en los dos
  lados —el selector esta comentado en globals.css.
*/
const GUION_ESTIMADO = "2 9";

/*
  El punto del catalogo tiene que contrastar contra las teselas que haya
  puestas: tinta sobre el mapa dibujado, que es claro, y niebla sobre la foto
  de satelite, que es oscura. Con un solo color, la mitad de las veces el campo
  entero desaparece.
*/
const MATERIAL_DEL_CAMPO: Record<Fondo, Material> = {
  mapa: "grafito",
  satelite: "niebla",
};

interface Props {
  fondo: Fondo;
  field: [number, number][];
  days: Day[];
  selectedDay: number | null;
  travelSource: TravelSourceKind | null;
  onSelectDay: (dia: number) => void;
  parada: ParadaElegida | null;
  onSelectStop: (id: string) => void;
}

export default function Mapa({
  fondo,
  field,
  days,
  selectedDay,
  travelSource,
  onSelectDay,
  parada,
  onSelectStop,
}: Props) {
  const contenedor = useRef<HTMLDivElement>(null);
  const mapa = useRef<L.Map | null>(null);
  const campo = useRef<FieldLayer | null>(null);
  const capaPlan = useRef<L.LayerGroup | null>(null);
  const capaFondo = useRef<L.TileLayer | null>(null);
  const lienzoPlan = useRef<L.SVG | null>(null);
  const onSelect = useRef(onSelectDay);
  const onStop = useRef(onSelectStop);

  useEffect(() => {
    onSelect.current = onSelectDay;
    onStop.current = onSelectStop;
  }, [onSelectDay, onSelectStop]);

  useEffect(() => {
    if (!contenedor.current || mapa.current) return;

    const map = L.map(contenedor.current, {
      zoomControl: false,
      attributionControl: true,
      preferCanvas: true,
    });
    map.setView(PAIS.getCenter(), zoomDelPais(map));

    // El fondo inicial lo pone el efecto de abajo, que tambien lo cambia.
    L.control.zoom({ position: "bottomright" }).addTo(map);

    /*
      El plan se dibuja en SVG y no en el canvas del mapa.

      El mapa se crea con preferCanvas porque el campo del catalogo son miles
      de puntos, pero eso hacia que la ruta tambien fuera al canvas: no habia
      ni un <path> en el panel de superposicion, y las animaciones de trazado
      del CSS —que existen desde el principio— nunca se ejecutaron. El PLAN.md
      cuenta "la ruta se dibuja de parada en parada" entre las cuatro cosas que
      se pueden animar, y no estaba pasando.

      El campo no pierde nada: es una capa de canvas propia y no depende de
      preferCanvas. Y la ruta son unas pocas polilineas, que en SVG van bien.
    */
    capaPlan.current = L.layerGroup([], { pane: "overlayPane" }).addTo(map);
    lienzoPlan.current = L.svg({ padding: 0.5 }).addTo(map);
    mapa.current = map;

    return () => {
      map.remove();
      mapa.current = null;
      capaPlan.current = null;
      capaFondo.current = null;
      lienzoPlan.current = null;
      campo.current = null;
    };
  }, []);

  /*
    Cambiar el fondo es quitar una capa y poner otra, no reconstruir el mapa:
    asi el encuadre, el plan y el campo del catalogo se quedan donde estan. La
    atribucion viaja con la capa porque cada proveedor exige la suya, y
    Leaflet la cambia solo al quitar y poner.
  */
  useEffect(() => {
    const map = mapa.current;
    if (!map) return;

    const anterior = capaFondo.current;
    const { url, credito, maxZoom } = TESELAS[fondo];
    const capa = L.tileLayer(url, { attribution: credito, maxZoom });

    // La nueva entra por debajo de todo y la vieja sale despues: al revés se
    // ve un parpadeo del fondo del contenedor mientras cargan las teselas.
    capa.addTo(map);
    capa.getContainer()?.style.setProperty("z-index", "0");
    if (anterior) {
      capa.once("load", () => map.removeLayer(anterior));
      // Si la red no responde, "load" no llega nunca y quedarian las dos.
      window.setTimeout(() => map.removeLayer(anterior), 2500);
    }
    capaFondo.current = capa;
  }, [fondo]);

  // El campo del catalogo entra una sola vez, cuando llegan los puntos.
  useEffect(() => {
    const map = mapa.current;
    if (!map || !field.length || campo.current) return;

    const capa = new FieldLayer(field, leerMateriales()[MATERIAL_DEL_CAMPO[fondo]]);
    capa.addTo(map);
    campo.current = capa;
  }, [field, fondo]);

  useEffect(() => {
    campo.current?.setColor(leerMateriales()[MATERIAL_DEL_CAMPO[fondo]]);
  }, [fondo]);

  const paradaId = parada?.id ?? null;

  useEffect(() => {
    const map = mapa.current;
    const capa = capaPlan.current;
    if (!map || !capa) return;

    capa.clearLayers();

    if (!days.length) {
      campo.current?.setOpacity(1);
      return;
    }

    // Con un plan en pantalla el catalogo se atenua pero no se va: el itinerario
    // se lee mejor sabiendo cuanto habia alrededor para elegir.
    campo.current?.setOpacity(0.3);

    const materiales = leerMateriales();
    const lienzo = lienzoPlan.current ?? undefined;

    for (const dia of days) {
      const activo = !selectedDay || dia.number === selectedDay;
      const coords = dia.stops.map(
        (s) => [s.place.lat, s.place.lon] as L.LatLngExpression,
      );

      /*
        **El trazo dice como se midio, y ahora lo dice tramo por tramo.**

        Antes era una decision del itinerario entero: un solo par que ORS no
        podia enrutar puntEaba el plan completo, incluidos los tramos que si se
        habian medido. El mapa decia menos de lo que el backend sabia.

        Ahora cada tramo trae su propio trazo por carretera o no lo trae. Con
        trazo se dibuja solido siguiendo la carretera; sin trazo, la recta
        punteada entre las dos paradas. El guion es el dato: dice que esa
        distancia salio de la linea recta.

        Sobre un mapa lleno de carreteras, un trazo suelto se confunde con una
        mas. Se dibuja dos veces: una linea clara y gruesa por debajo que
        despeja el fondo, y el anil encima. Es la tecnica de las cartas
        nauticas para las derrotas.
      */
      dia.stops.forEach((visita, indice) => {
        if (indice === 0) return;

        const real = visita.geometry_from_previous;
        const trazo: L.LatLngExpression[] =
          real && real.length > 1
            ? real
            : [coords[indice - 1], coords[indice]];

        if (activo) {
          L.polyline(trazo, {
            color: materiales.niebla,
            weight: 8,
            opacity: 0.85,
            lineCap: "round",
            interactive: false,
            renderer: lienzo,
          }).addTo(capa);
        }

        const linea = L.polyline(trazo, {
          color: materiales.anil,
          weight: activo ? 3.5 : 2,
          opacity: activo ? 1 : 0.35,
          dashArray: real && real.length > 1 ? undefined : GUION_ESTIMADO,
          lineCap: "round",
          renderer: lienzo,
        }).addTo(capa);

        if (activo) animarTramo(linea, indice - 1, Boolean(real && real.length > 1));
      });

      dia.stops.forEach((visita, indice) => {
        const marcador = L.marker([visita.place.lat, visita.place.lon], {
          icon: pin(
            indice + 1,
            visita.place.category,
            activo,
            indice,
            materiales,
            visita.place.id === paradaId,
          ),
          keyboard: true,
          title: `${visita.place.name} — día ${dia.number}`,
          opacity: activo ? 1 : 0.55,
        });
        marcador.on("click", () => {
          // El dia primero: si el pin era de otro dia, el panel tiene que
          // cambiar de pestaña antes de que la parada exista en pantalla.
          if (dia.number !== selectedDay) onSelect.current(dia.number);
          onStop.current(visita.place.id);
        });
        marcador.addTo(capa);
      });
    }

  }, [days, selectedDay, travelSource, paradaId]);

  /*
    Encuadrar es un efecto aparte de dibujar, y la separacion importa.

    Estaban juntos, asi que elegir una parada volvia a encuadrar el dia entero
    —el id de la parada esta entre las dependencias del dibujo, porque hay que
    repintar el pin destacado— y ese reencuadre competia con el vuelo hasta la
    parada: dos animaciones peleando por el mismo mapa. El encuadre solo debe
    responder a que cambie el plan o el dia elegido.
  */
  useEffect(() => {
    const map = mapa.current;
    if (!map) return;

    if (!days.length) {
      map.flyTo(PAIS.getCenter(), zoomDelPais(map), { duration: 0.8 });
      return;
    }

    const puntos = days
      .filter((dia) => !selectedDay || dia.number === selectedDay)
      .flatMap((dia) =>
        dia.stops.map((s) => [s.place.lat, s.place.lon] as L.LatLngExpression),
      );

    if (puntos.length) {
      map.flyToBounds(L.latLngBounds(puntos), {
        padding: [70, 70],
        maxZoom: 14,
        duration: 0.9,
      });
    }
  }, [days, selectedDay]);

  /*
    Ir a la parada elegida desde el panel. Zoom 16 y no el maximo: a 18 se ve
    el techo del sitio y nada de su alrededor, y lo que uno quiere saber al
    apretar una parada es donde queda respecto de las demas.
  */
  useEffect(() => {
    const map = mapa.current;
    if (!map || !parada || parada.origen !== "panel") return;

    for (const dia of days) {
      const visita = dia.stops.find((s) => s.place.id === parada.id);
      if (visita) {
        map.flyTo([visita.place.lat, visita.place.lon], Math.max(map.getZoom(), 16), {
          duration: 0.7,
        });
        return;
      }
    }
  }, [parada, days]);

  return (
    <div
      ref={contenedor}
      className="h-full w-full"
      role="application"
      aria-label="Mapa del itinerario"
    />
  );
}

/**
 * El tramo se dibuja de principio a fin, escalonado con los demas.
 *
 * La longitud del trazo se lee del propio SVG en vez de fijar un numero: con
 * geometria real un tramo puede medir cuarenta veces mas que otro, y un
 * dasharray constante dejaria los largos a medio dibujar y los cortos animados
 * de mas. `getTotalLength` da la longitud exacta en unidades de usuario.
 *
 * Los tramos punteados no se dibujan, aparecen. Ahi el guion es el dato —dice
 * que la distancia salio de la linea recta— y animar el trazado tendria que
 * sobrescribir el dasharray, que es justamente borrar la informacion.
 */
function animarTramo(linea: L.Polyline, orden: number, solido: boolean): void {
  const nodo = linea.getElement() as SVGPathElement | null;
  if (!nodo) return;

  const retraso = Math.min(orden * 160, 900);
  nodo.style.setProperty("--retraso", `${retraso}ms`);

  if (!solido) {
    nodo.classList.add("waypoint-tramo-aparece");
    return;
  }

  nodo.style.setProperty("--largo", String(nodo.getTotalLength()));
  nodo.classList.add("waypoint-tramo-traza");
}


/**
 * El pin cae escalonado, no todos juntos.
 *
 * El retraso va en el estilo del icono y no en una libreria de animacion:
 * Leaflet posiciona sus marcadores con transform, y cualquier cosa que anime
 * transform desde afuera pelea con el mapa cada vez que uno hace zoom.
 */
function pin(
  numero: number,
  categoria: Category,
  activo: boolean,
  indice: number,
  materiales: Materiales,
  elegida: boolean,
) {
  const color = materiales[CATEGORIA[categoria].material];

  // **Los otros dias son puntos, no numeros.** Con tres dias en pantalla habia
  // tres juegos de "1, 2, 3, 4" encimados y ninguno se entendia. El numero es
  // el orden del recorrido, y un orden solo se lee si es el unico en pantalla.
  if (!activo) {
    return L.divIcon({
      className: "waypoint-pin-wrap",
      iconSize: [10, 10],
      iconAnchor: [5, 5],
      html: `<span class="waypoint-punto" style="--pin:${color}"></span>`,
    });
  }

  return L.divIcon({
    className: "waypoint-pin-wrap",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    html: `
      <span class="waypoint-pin${elegida ? " waypoint-pin-elegido" : ""}" style="--pin:${color};--retraso:${Math.min(indice * 70, 700)}ms">
        <span class="waypoint-pin-num">${numero}</span>
      </span>`,
  });
}
