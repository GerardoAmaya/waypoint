/**
 * Como se presenta cada categoria: nombre, icono y color.
 *
 * **El icono no es adorno: es el segundo canal.** Antes la categoria de una
 * parada se codificaba solo con el color del punto, y el color por si solo no
 * es informacion accesible —quien no distingue el cafe del verde no tiene de
 * donde sacarla (WCAG 1.4.1). Con icono, el color pasa a reforzar algo que ya
 * se puede leer sin el.
 *
 * El color va como var() y no como literal para que siga al tema: el ocre que
 * funciona sobre el panel oscuro no llega a contraste sobre el claro, y
 * globals.css ya resuelve ese cambio en la capa de roles.
 */

import {
  faBed,
  faBinoculars,
  faLandmark,
  faTicket,
  faTree,
  faUtensils,
  type IconDefinition,
} from "@fortawesome/free-solid-svg-icons";

import type { Category } from "./types";
import type { Material } from "./paleta";

interface Presentacion {
  nombre: string;
  icono: IconDefinition;
  /** Para el panel: sigue al tema. */
  color: string;
  /** Para el mapa: siempre sobre teselas claras, asi que no sigue al tema. */
  material: Material;
}

export const CATEGORIA: Record<Category, Presentacion> = {
  food: {
    nombre: "Comida",
    icono: faUtensils,
    color: "var(--cat-food)",
    material: "cafe",
  },
  nature: {
    nombre: "Naturaleza",
    icono: faTree,
    color: "var(--cat-nature)",
    material: "verde",
  },
  culture: {
    nombre: "Cultura",
    icono: faLandmark,
    color: "var(--cat-culture)",
    material: "ocre",
  },
  viewpoint: {
    nombre: "Mirador",
    icono: faBinoculars,
    color: "var(--cat-culture)",
    material: "ocre",
  },
  attraction: {
    nombre: "Atracción",
    icono: faTicket,
    color: "var(--cat-attraction)",
    material: "anil-claro",
  },
  lodging: {
    nombre: "Alojamiento",
    icono: faBed,
    color: "var(--cat-lodging)",
    material: "acero-claro",
  },
};

/** Orden de la leyenda: las que mas aparecen primero. */
export const ORDEN_LEYENDA: Category[] = [
  "nature",
  "food",
  "culture",
  "viewpoint",
  "attraction",
  "lodging",
];
