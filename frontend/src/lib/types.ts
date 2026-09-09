/**
 * Espejo de los schemas del backend. Se escriben a mano y no se generan porque
 * son pocos y estables, y porque el generador traeria toda la maquinaria de
 * OpenAPI para veinte lineas de tipos.
 */

export type Category =
  | "food"
  | "nature"
  | "culture"
  | "viewpoint"
  | "attraction"
  | "lodging";

export type Mode = "driving" | "walking";

/** De donde salieron las distancias de un itinerario. */
export type TravelSourceKind = "estimated" | "mixed" | "real";

export interface Place {
  id: string;
  name: string;
  category: Category;
  subcategory: string | null;
  lat: number;
  lon: number;
  quality_score: number;
  distance_m: number | null;
}

export interface Stop {
  place: Place;
  arrival: string;
  departure: string;
  travel_minutes_from_previous: number;
  travel_km_from_previous: number;
  meal: "lunch" | "dinner" | null;
}

export interface Day {
  number: number;
  stops: Stop[];
  travel_km: number;
  start: string | null;
  end: string | null;
}

/** Un limite que el usuario puso y el itinerario no pudo respetar. */
export interface Violation {
  constraint: string;
  day: number | null;
  detail: string;
}

/**
 * Algo que el viajero deberia saber y no es un limite incumplido. Que el
 * comedor mas cercano quede fuera del presupuesto de traslado no es romper una
 * regla, y la solucion del mundo real es llevar comida.
 */
export interface Advice {
  kind: string;
  day: number | null;
  detail: string;
}

export interface TravelSource {
  source: TravelSourceKind;
  cached: number;
  fetched: number;
  estimated: number;
  real_ratio: number;
  requests: number;
  quota_remaining: number | null;
}

export interface Itinerary {
  days: Day[];
  violations: Violation[];
  advice: Advice[];
  satisfies_all_constraints: boolean;
  total_stops: number;
  unused_candidates: number;
  travel: TravelSource;
}

export interface Constraints {
  days: number;
  center_lat: number;
  center_lon: number;
  radius_m: number;
  earliest_start: string;
  latest_end: string;
  max_travel_km_per_day: number;
  mode: Mode;
  preferred_categories: Category[];
  avoided_categories: Category[];
  include_meals: boolean;
  max_stops_per_day: number;
  min_quality: number;
  real_routes: boolean;
}

export interface Area {
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
  source: "zone" | "catalog";
}

export interface Interpretation {
  area: Area | null;
  constraints: Constraints | null;
  /** Lo que el modelo entendio y el schema no puede representar. */
  unmapped: string[];
  /** Ajustes que hubo que aplicar: recortes de rango, categorias ignoradas. */
  notes: string[];
}

export interface CandidatePoint {
  id: string;
  name: string;
  lat: number;
  lon: number;
  category: Category;
}

export interface Candidates {
  destinations: CandidatePoint[];
  meals: number;
}

export interface Revision {
  itinerary: Itinerary;
  applied: Record<string, string>;
  removed: string[];
  missing: string[];
  unmapped: string[];
  notes: string[];
}

/** Las fases que emite POST /plan, en el orden en que llegan. */
export type PlanEvent =
  | { phase: "interpretation"; data: Interpretation }
  | { phase: "candidates"; data: Candidates }
  | { phase: "draft"; data: Itinerary }
  | { phase: "plan"; data: Itinerary }
  | { phase: "error"; data: { message: string; unmapped?: string[]; notes?: string[] } };

/**
 * Los mismos valores que declara globals.css, pero literales.
 *
 * Leaflet escribe el color como atributo de presentacion del SVG, y ahi var()
 * no resuelve de forma fiable. Duplicarlos es feo; que la ruta salga negra en
 * un navegador es peor. El comentario en globals.css avisa de la pareja.
 */
export const PALETA = {
  basalto: "#131a20",
  niebla: "#f4f2ed",
  anil: "#2b3a67",
  anilClaro: "#4a5d96",
  cafe: "#8c5a35",
  verde: "#3f7a5e",
  ocre: "#b8863f",
  tintaSuave: "#5b6570",
} as const;

export const CATEGORY_COLOR: Record<Category, string> = {
  food: PALETA.cafe,
  nature: PALETA.verde,
  culture: PALETA.ocre,
  viewpoint: PALETA.ocre,
  attraction: PALETA.anilClaro,
  lodging: PALETA.tintaSuave,
};

export const CATEGORY_LABEL: Record<Category, string> = {
  food: "Comida",
  nature: "Naturaleza",
  culture: "Cultura",
  viewpoint: "Mirador",
  attraction: "Atracción",
  lodging: "Alojamiento",
};
