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

  /*
    Los cuatro datos de OSM que existen en cantidad suficiente para valer la
    pena, medidos sobre el catalogo: alguno de ellos aparece en el 45% de los
    comedores, el 31% de los alojamientos y el 24% de los lugares naturales.
    En miradores y cultura no hay casi nada, asi que la interfaz tiene que
    verse bien sin ninguno.
  */
  cuisine: string | null;
  elevation_m: number | null;
  phone: string | null;
  website: string | null;
}

export interface Stop {
  place: Place;
  arrival: string;
  departure: string;
  travel_minutes_from_previous: number;
  travel_km_from_previous: number;
  meal: "lunch" | "dinner" | null;

  /**
   * El trazo por carretera del tramo que llega a esta parada, en [lat, lon].
   *
   * Nulo cuando ese tramo no se pudo enrutar, y eso es informacion: el mapa
   * dibuja la recta punteada y con eso dice que la distancia es estimada. La
   * primera parada de cada dia nunca lo tiene, porque no llega de ningun lado.
   */
  geometry_from_previous: [number, number][] | null;
}

export interface Day {
  number: number;
  stops: Stop[];
  travel_km: number;
  start: string | null;
  end: string | null;

  /**
   * El modo de ESTE dia, que puede no ser el del itinerario.
   *
   * Va por dia porque el icono del traslado dice como se va, y en un viaje
   * mixto —"el primer dia en coche y el segundo a pie"— poner el coche en el
   * dia que se camina es decir algo falso.
   */
  mode: Mode;
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
  reason: "no_key" | "no_quota" | "unroutable" | null;
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

/**
 * Una foto libre de la zona, con su credito.
 *
 * El autor y la licencia no son opcionales: las imagenes son de Wikimedia
 * Commons y sus licencias exigen atribucion. El backend las declara
 * obligatorias en el schema por lo mismo.
 */
export interface AreaPhoto {
  /** Nombre del archivo en Commons; la URL se arma con Special:FilePath. */
  file: string;
  author: string;
  license: string;
  page: string;
}

export interface Area {
  name: string;
  lat: number;
  lon: number;
  radius_m: number;
  source: "zone" | "catalog";
  /** Solo las zonas del nomenclator, y dos de ellas tampoco tienen. */
  photo: AreaPhoto | null;
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
