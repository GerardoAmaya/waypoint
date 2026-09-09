import type { Metadata, Viewport } from "next";
import { config } from "@fortawesome/fontawesome-svg-core";
import "@fortawesome/fontawesome-svg-core/styles.css";

import { SCRIPT_TEMA } from "@/lib/tema";
import "./globals.css";

/*
  Font Awesome inyecta su hoja desde JavaScript al montar el primer icono, y en
  el App Router eso llega despues de la primera pintura: los iconos aparecen a
  tamano completo y se encogen. Se importa la hoja aca y se le apaga la
  inyeccion.
*/
config.autoAddCss = false;

export const metadata: Metadata = {
  title: "Waypoint — itinerarios por El Salvador",
  description:
    "Escribí el viaje que querés hacer y el plan sale sobre lugares que existen, con distancias medidas.",
};

/*
  Un themeColor por esquema. Con uno solo, la barra del navegador se queda con
  el basalto tambien en tema claro y el borde superior de la pagina queda
  partido en dos.
*/
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#131a20" },
    { media: "(prefers-color-scheme: light)", color: "#f4f2ed" },
  ],
};

/*
  Las familias se piden con <link> en el head.

  La primera version las traia con @import dentro de globals.css y no llegaban:
  Tailwind 4 procesa la hoja con Lightning CSS y el @import remoto se pierde por
  el camino, asi que la pagina salia con la fuente del sistema.

  next/font seria mejor —autohospeda y evita el salto de maquetacion— pero las
  descarga al compilar, y eso ata el build a que fonts.googleapis.com este
  alcanzable. Con <link> el build no depende de la red y la fuente entra en la
  primera pintura util gracias a display=swap.
*/
const FUENTES =
  "https://fonts.googleapis.com/css2" +
  "?family=Bricolage+Grotesque:opsz,wght@12..96,200..800" +
  "&family=DM+Mono:wght@400;500" +
  "&display=swap";

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    /*
      suppressHydrationWarning solo cubre este nodo, no el arbol: el script de
      abajo escribe data-theme en <html> antes de que React vea el documento, y
      sin esto React reporta que el atributo no coincide con el del servidor.
    */
    <html lang="es" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href={FUENTES} />
        {/* Antes de la primera pintura; ver el comentario en lib/tema.ts. */}
        <script dangerouslySetInnerHTML={{ __html: SCRIPT_TEMA }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
