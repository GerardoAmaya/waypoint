/**
 * Qué trecho de la línea de tiempo va bajo agua.
 *
 * **Es el mismo problema que [el ocaso](./luz.ts) y se resuelve igual.** El
 * hilo que une dos paradas abarca el rato que va de una a otra; si la lluvia
 * ocupa parte de ese rato, se puede decir *qué* parte, y eso es más que decir
 * que el día viene con agua.
 *
 * Y es un dato que sale: sobre 1.540 días de pronóstico y archivo de las 20
 * zonas del nomenclátor, llueve dentro del horario de paseo en el 66% de los
 * días de septiembre —el 92% de los itinerarios de tres días— y en el 9% de
 * los de marzo. Lo que no pasó ni una vez en esos 1.540 días es que lloviera
 * la jornada entera: la media son 2,5 horas. O sea que esto siempre marca
 * *una parte* del día, nunca el día completo.
 *
 * El backend manda las horas con agua, no los minutos: `rain_hours` son horas
 * de reloj y cada una vale el intervalo entero. Fingir el cuarto de hora sería
 * inventar una precisión que el pronóstico no trae.
 */

/** "18:28:00" o "18:28" a minutos desde medianoche. */
function minutos(hora: string): number {
  const [h, m] = hora.split(":");
  return Number(h) * 60 + Number(m);
}

/**
 * Los trechos de un tramo que caen bajo lluvia, en fracciones de 0 a 1.
 *
 * Devuelve una lista porque la lluvia de un día puede venir partida —llueve a
 * mediodía, escampa, vuelve a las cinco— y un solo rango tendría que juntar
 * las dos con la tarde seca en medio, que es la versión educada de mentir.
 *
 * Lista vacía cuando no llueve en ese tramo, cuando no hay pronóstico, o
 * cuando el tramo no dura nada: en los tres casos no hay nada que pintar.
 */
export function tramosDeLluvia(
  desde: string | null,
  hasta: string | null,
  horasDeLluvia: number[] | null | undefined,
): [number, number][] {
  if (!desde || !hasta || !horasDeLluvia?.length) return [];

  const inicio = minutos(desde);
  const fin = minutos(hasta);
  if (fin <= inicio) return [];

  const largo = fin - inicio;
  const trechos: [number, number][] = [];

  // Las horas se recorren ordenadas y se van pegando las seguidas, para que
  // tres horas de chubasco salgan como un trecho y no como tres rayas.
  for (const hora of [...new Set(horasDeLluvia)].sort((a, b) => a - b)) {
    const arranca = Math.max(hora * 60, inicio);
    const acaba = Math.min(hora * 60 + 60, fin);
    if (acaba <= arranca) continue;

    const trecho: [number, number] = [
      (arranca - inicio) / largo,
      (acaba - inicio) / largo,
    ];
    const ultimo = trechos[trechos.length - 1];
    if (ultimo && trecho[0] <= ultimo[1]) ultimo[1] = trecho[1];
    else trechos.push(trecho);
  }

  return trechos;
}
