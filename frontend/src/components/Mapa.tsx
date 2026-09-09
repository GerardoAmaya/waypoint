"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { FieldLayer } from "./FieldLayer";
import { CATEGORY_COLOR, PALETA, type Day, type TravelSourceKind } from "@/lib/types";

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

    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
        maxZoom: 18,
      },
    ).addTo(map);

    // Las etiquetas van en una capa aparte, por encima de la ruta, para que los
    // nombres de pueblo se lean sin que el trazo los tape.
    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png",
      { maxZoom: 18, pane: "shadowPane" },
    ).addTo(map);

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
        L.polyline(coords, {
          color: PALETA.anilClaro,
          weight: activo ? 2.5 : 1.5,
          opacity: activo ? 0.9 : 0.25,
          dashArray: travelSource === "real" ? undefined : "1 7",
          lineCap: "round",
        }).addTo(capa);
      }

      dia.stops.forEach((parada, indice) => {
        const marcador = L.marker([parada.place.lat, parada.place.lon], {
          icon: pin(indice + 1, parada.place.category, activo, indice),
          keyboard: true,
          title: parada.place.name,
          opacity: activo ? 1 : 0.35,
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
  const retraso = activo ? Math.min(indice * 70, 700) : 0;

  return L.divIcon({
    className: "waypoint-pin-wrap",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    html: `
      <span class="waypoint-pin" style="--pin:${color};--retraso:${retraso}ms">
        <span class="waypoint-pin-num">${numero}</span>
      </span>`,
  });
}
