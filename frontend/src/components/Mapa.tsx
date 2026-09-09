"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { FieldLayer } from "./FieldLayer";
import { CATEGORY_COLOR, PALETA, type Day, type TravelSourceKind } from "@/lib/types";

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
 */
const TESELAS = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  credito:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
};

/** El Salvador entero, que es el encuadre de arranque. */
const PAIS: L.LatLngBoundsExpression = [
  [13.1, -90.15],
  [14.45, -87.65],
];

interface Props {
  field: [number, number][];
  days: Day[];
  selectedDay: number | null;
  travelSource: TravelSourceKind | null;
  onSelectDay: (dia: number) => void;
}

export default function Mapa({
  field,
  days,
  selectedDay,
  travelSource,
  onSelectDay,
}: Props) {
  const contenedor = useRef<HTMLDivElement>(null);
  const mapa = useRef<L.Map | null>(null);
  const campo = useRef<FieldLayer | null>(null);
  const capaPlan = useRef<L.LayerGroup | null>(null);
  const onSelect = useRef(onSelectDay);

  useEffect(() => {
    onSelect.current = onSelectDay;
  }, [onSelectDay]);

  useEffect(() => {
    if (!contenedor.current || mapa.current) return;

    const map = L.map(contenedor.current, {
      zoomControl: false,
      attributionControl: true,
      preferCanvas: true,
    });
    map.fitBounds(PAIS, { padding: [24, 24] });

    L.tileLayer(TESELAS.url, {
      attribution: TESELAS.credito,
      maxZoom: 18,
    }).addTo(map);

    L.control.zoom({ position: "bottomright" }).addTo(map);
    capaPlan.current = L.layerGroup().addTo(map);
    mapa.current = map;

    return () => {
      map.remove();
      mapa.current = null;
      capaPlan.current = null;
      campo.current = null;
    };
  }, []);

  // El campo del catalogo entra una sola vez, cuando llegan los puntos.
  useEffect(() => {
    const map = mapa.current;
    if (!map || !field.length || campo.current) return;

    const capa = new FieldLayer(field);
    capa.addTo(map);
    campo.current = capa;
  }, [field]);

  useEffect(() => {
    const map = mapa.current;
    const capa = capaPlan.current;
    if (!map || !capa) return;

    capa.clearLayers();

    if (!days.length) {
      campo.current?.setOpacity(1);
      map.flyToBounds(PAIS, { padding: [24, 24], duration: 0.8 });
      return;
    }

    // Con un plan en pantalla el catalogo se atenua pero no se va: el itinerario
    // se lee mejor sabiendo cuanto habia alrededor para elegir.
    campo.current?.setOpacity(0.3);

    const visibles = selectedDay ? days.filter((d) => d.number === selectedDay) : days;
    const puntos: L.LatLngExpression[] = [];

    for (const dia of days) {
      const activo = !selectedDay || dia.number === selectedDay;
      const coords = dia.stops.map(
        (s) => [s.place.lat, s.place.lon] as L.LatLngExpression,
      );
      if (activo) puntos.push(...coords);

      if (coords.length > 1) {
        // **El trazo dice como se midio.** Punteado es estimado, solido es
        // medido sobre carretera. No es adorno: es la unica forma de ver, sin
        // leer un numero, que las distancias de este dia son aproximadas.
        // Sobre un mapa lleno de carreteras, un trazo suelto se confunde con
        // una mas. Se dibuja dos veces: una linea clara y gruesa por debajo que
        // despeja el fondo, y el anil encima. Es la tecnica de las cartas
        // nauticas para las derrotas.
        if (activo) {
          L.polyline(coords, {
            color: PALETA.niebla,
            weight: 8,
            opacity: 0.85,
            lineCap: "round",
            interactive: false,
          }).addTo(capa);
        }

        L.polyline(coords, {
          color: PALETA.anil,
          weight: activo ? 3.5 : 2,
          opacity: activo ? 1 : 0.35,
          dashArray: travelSource === "real" ? undefined : "2 9",
          lineCap: "round",
        }).addTo(capa);
      }

      dia.stops.forEach((parada, indice) => {
        const marcador = L.marker([parada.place.lat, parada.place.lon], {
          icon: pin(indice + 1, parada.place.category, activo, indice),
          keyboard: true,
          title: `${parada.place.name} — día ${dia.number}`,
          opacity: activo ? 1 : 0.55,
        });
        marcador.on("click", () => onSelect.current(dia.number));
        marcador.addTo(capa);
      });
    }

    if (puntos.length) {
      map.flyToBounds(L.latLngBounds(puntos), {
        padding: [70, 70],
        maxZoom: 14,
        duration: 0.9,
      });
    }
  }, [days, selectedDay, travelSource]);

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
 * El pin cae escalonado, no todos juntos.
 *
 * El retraso va en el estilo del icono y no en una libreria de animacion:
 * Leaflet posiciona sus marcadores con transform, y cualquier cosa que anime
 * transform desde afuera pelea con el mapa cada vez que uno hace zoom.
 */
function pin(numero: number, categoria: string, activo: boolean, indice: number) {
  const color = CATEGORY_COLOR[categoria as keyof typeof CATEGORY_COLOR];

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
      <span class="waypoint-pin" style="--pin:${color};--retraso:${Math.min(indice * 70, 700)}ms">
        <span class="waypoint-pin-num">${numero}</span>
      </span>`,
  });
}
