/*
  La ruta de un itinerario compartido.

  Renderiza la misma pantalla que la raíz: armar un itinerario y abrir uno
  guardado terminan en la misma vista, y duplicarla sería mantener dos.

  Existe como ruta de verdad y no como parámetro de consulta para que recargar
  la página funcione: con `/?i=codigo` un refresco en Next.js serviría la raíz
  y perdería el itinerario. El código lo lee la pantalla de la URL.

  **Aquí hay un componente de servidor envolviendo al de cliente**, y antes era
  un `export { default }` a secas. La diferencia es `generateMetadata`: lo que
  se ve de este enlace antes de abrirlo —en un chat, en una vista previa— se
  decide en el servidor, y la pantalla es `"use client"`.
*/

import type { Metadata } from "next";

import { fetchCompartido } from "@/lib/api";
import { describir } from "@/lib/tarjeta";
import Pantalla from "../../page";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ codigo: string }>;
}): Promise<Metadata> {
  const { codigo } = await params;

  try {
    const guardado = await fetchCompartido(codigo);
    const { titulo, fechas, resumen } = describir(
      guardado.interpretation,
      guardado.itinerary,
    );

    // "Ruta de las Flores · 14 nov – 16 nov" y debajo "3 días · 18 paradas ·
    // 124 km": el título dice dónde y cuándo, la descripción dice cuánto.
    const encabezado = fechas ? `${titulo} · ${fechas}` : titulo;

    return {
      title: encabezado,
      description: `${resumen}. Distancias medidas sobre carretera.`,
      openGraph: {
        title: encabezado,
        description: `${resumen}. Distancias medidas sobre carretera.`,
        type: "article",
      },
    };
  } catch {
    // Un código que ya no existe o el backend caído. El enlace se previsualiza
    // con lo genérico y la aplicación explica el resto al abrirlo; fallar aquí
    // dejaría la página entera sin servir por una vista previa.
    return {
      title: "Un itinerario por El Salvador",
      description: "Itinerarios sobre lugares que existen, con distancias medidas.",
    };
  }
}

export default function Compartido() {
  return <Pantalla />;
}
