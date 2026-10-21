import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
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
  Las fuentes viven en el repo, en src/app/fuentes.

  Antes se pedian a fonts.googleapis.com con un <link>. Eso costaba dos saltos
  antes de ver texto con la fuente buena —resolver fonts.googleapis.com, leer la
  hoja, y recien ahi ir a fonts.gstatic.com por el archivo— y ademas contaba a
  cada visitante ante un tercero.

  La alternativa de manual, next/font/google, autohospeda igual pero descarga al
  compilar, y eso ata el build a que Google este alcanzable. Con los archivos
  versionados no depende de la red nadie: ni el build ni el navegador.

  Se baja solo el subconjunto latino. Cubre el español entero —acentos, eñe,
  dieresis, los signos de apertura— y el salvadoreño de los nombres del
  catalogo; lo que caiga fuera lo dibuja la fuente del sistema, igual que
  cualquier glifo que falte. Son 94 kB en vez de los ~300 de todos los
  subconjuntos.

  display: "swap" mantiene lo que ya hacia el <link>: el texto se ve desde la
  primera pintura con la fuente del sistema y cambia al cargar la propia. El
  salto que eso provoca lo absorbe next/font, que mide la fuente y ajusta la
  de reserva.
*/
const sans = localFont({
  src: "./fuentes/bricolage-grotesque-200-800.woff2",
  // Es variable: un archivo cubre el rango entero de pesos.
  weight: "200 800",
  display: "swap",
  variable: "--fuente-sans",
  // El orden importa: la primera que exista es la que mide next/font para
  // ajustar las metricas y que el swap no mueva la maqueta.
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

const mono = localFont({
  src: [
    { path: "./fuentes/dm-mono-400.woff2", weight: "400", style: "normal" },
    { path: "./fuentes/dm-mono-500.woff2", weight: "500", style: "normal" },
  ],
  display: "swap",
  variable: "--fuente-mono",
  fallback: ["ui-monospace", "SF Mono", "monospace"],
});

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    /*
      suppressHydrationWarning solo cubre este nodo, no el arbol: el script de
      abajo escribe data-theme en <html> antes de que React vea el documento, y
      sin esto React reporta que el atributo no coincide con el del servidor.
    */
    <html
      lang="es"
      className={`${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Antes de la primera pintura; ver el comentario en lib/tema.ts. */}
        <script dangerouslySetInnerHTML={{ __html: SCRIPT_TEMA }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
