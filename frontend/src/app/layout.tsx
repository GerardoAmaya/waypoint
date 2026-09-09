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

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
