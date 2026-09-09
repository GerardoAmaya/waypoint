"use client";

import { motion, type PanInfo } from "motion/react";

interface Props {
  expandido: boolean;
  onToggle: () => void;
}

/**
 * El asa que arrastra el panel, solo en pantalla angosta.
 *
 * **Por qué hace falta.** Medido en una pantalla de 780 px: el mapa se lleva
 * 351, la cabecera 164, las pestañas 57 y el pie 102. Al itinerario le quedan
 * 104 px y cada parada mide 65, así que se veía **una de seis**. El cromo se
 * comía el 75% del panel y el itinerario, que es el producto, quedaba en una
 * rendija.
 *
 * El mapa y la lista compiten por la misma pantalla y uno mira una cosa a la
 * vez, así que la respuesta no es repartir mejor sino dejar elegir. Es el
 * patrón de las aplicaciones de mapas, y por eso no hay que explicarlo.
 *
 * **Se toca y también se arrastra.** El arrastre es lo que la mano espera, pero
 * un panel que solo responde a un gesto no se puede usar con teclado ni con
 * lector de pantalla. Debajo es un botón de verdad con `aria-expanded`.
 */
export default function Asa({ expandido, onToggle }: Props) {
  const alSoltar = (_: unknown, info: PanInfo) => {
    // Cuarenta píxeles de umbral: menos que eso es un toque tembloroso y no
    // un arrastre, y tratarlo como arrastre haría que tocar fallara la mitad
    // de las veces.
    if (info.offset.y < -40 && !expandido) onToggle();
    if (info.offset.y > 40 && expandido) onToggle();
  };

  return (
    <motion.button
      onClick={onToggle}
      onPanEnd={alSoltar}
      aria-expanded={expandido}
      aria-label={expandido ? "Encoger el itinerario" : "Ver el itinerario completo"}
      className="flex w-full shrink-0 touch-none items-center justify-center py-2.5 lg:hidden"
    >
      <span
        aria-hidden
        className="h-1 w-10 rounded-full bg-tinta-tenue transition-colors"
      />
    </motion.button>
  );
}
