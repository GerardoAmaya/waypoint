import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Waypoint — itinerarios por El Salvador",
  description:
    "Escribí el viaje que querés hacer y el plan sale sobre lugares que existen, con distancias medidas.",
};

export const viewport: Viewport = {
  themeColor: "#131a20",
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
    <html lang="es">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href={FUENTES} />
      </head>
      <body>{children}</body>
    </html>
  );
}
