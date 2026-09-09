"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { FieldLayer } from "./FieldLayer";
import { CATEGORY_COLOR, PALETA, type Day, type TravelSourceKind } from "@/lib/types";

/**
 * De donde salen las teselas.
 *
 * Por defecto, OpenStreetMap oscurecido por CSS. CARTO pasó a exigir llave en
 * agosto de 2026 y estampa "API KEY REQUIRED" sobre cada tesela sin ella; la
 * llave es gratis y sin cuenta, pero el PLAN.md eligió el stack sin llaves a
 * propósito, y una que haya que pedir es un paso más para quien clone el repo.
 *
 * Con NEXT_PUBLIC_CARTO_KEY puesta se usa Dark Matter, que se ve mejor que
 * cualquier inversión por filtro. Sin ella el mapa funciona igual.
 */
const LLAVE_CARTO = process.env.NEXT_PUBLIC_CARTO_KEY;

const TESELAS = LLAVE_CARTO
  ? {
      url: `https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=${LLAVE_CARTO}`,
      credito:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      invertir: false,
    }
  : {
      url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      credito:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      invertir: true,
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

    // El filtro que oscurece OpenStreetMap se aplica al panel de teselas y no
    // al mapa entero: invertir el contenedor invertiria tambien los pines y la
    // ruta, y el anil saldria naranja.
    if (TESELAS.invertir) {
      map.getPane("tilePane")?.classList.add("teselas-oscuras");
    }

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
        // Un trazo fino en anil sobre un mapa oscuro y cargado se pierde. Se
        // dibuja dos veces: una linea gruesa oscura por debajo que despeja el
        // fondo, y la de color encima. Es la misma tecnica que usan las cartas
        // nauticas para las derrotas.
        if (activo) {
          L.polyline(coords, {
            color: PALETA.basalto,
            weight: 7,
            opacity: 0.55,
            lineCap: "round",
            interactive: false,
          }).addTo(capa);
        }

        L.polyline(coords, {
          color: activo ? PALETA.niebla : PALETA.anilClaro,
          weight: activo ? 3 : 1.5,
          opacity: activo ? 0.95 : 0.3,
          dashArray: travelSource === "real" ? undefined : "2 8",
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
