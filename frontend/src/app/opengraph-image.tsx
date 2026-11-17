/**
 * La tarjeta de la portada.
 *
 * La de un itinerario dice ese plan; esta dice qué es esto, porque el enlace a
 * la raíz se pega igual de a menudo y no hay ningún itinerario del que hablar.
 *
 * Comparte fuentes y colores con la de `/i/[codigo]` —mismo Satori, mismas
 * reglas: flexbox, literales, `ttf`— y deliberadamente no comparte plantilla:
 * son dos composiciones distintas y factorizarlas dejaría un componente con un
 * parámetro por diferencia.
 */

import { ImageResponse } from "next/og";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { material } from "@/lib/paleta-servidor";

export const alt = "Waypoint — itinerarios por El Salvador";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const fuente = (archivo: string) =>
  readFile(join(process.cwd(), "src/app/fuentes", archivo));

const [titular, cuerpo, mono] = await Promise.all([
  fuente("bricolage-700.ttf"),
  fuente("bricolage-500.ttf"),
  fuente("dm-mono-500.ttf"),
]);

const FONDO = material("basalto");
const TINTA = material("niebla");
const TENUE = material("acero");
const BORDE = material("basalto-borde");

/* Los colores de las categorías, que son la firma visual del producto. */
const MUESTRAS = ["verde", "cafe", "ocre", "anil-claro", "acero-claro"].map(material);

export default function Imagen() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: FONDO,
          color: TINTA,
          padding: "64px 72px",
          fontFamily: "Cuerpo",
        }}
      >
        <div
          style={{
            fontFamily: "Mono",
            fontSize: 24,
            letterSpacing: 4,
            color: TENUE,
          }}
        >
          WAYPOINT
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          <div style={{ fontFamily: "Titular", fontSize: 92, lineHeight: 1.05 }}>
            Itinerarios por El Salvador
          </div>
          <div style={{ fontSize: 38, color: TENUE, lineHeight: 1.35 }}>
            Escribí el viaje que querés hacer. El plan sale sobre lugares que
            existen, con distancias medidas sobre carretera.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            borderTop: `2px solid ${BORDE}`,
            paddingTop: 24,
          }}
        >
          <div style={{ display: "flex", alignItems: "center" }}>
            {MUESTRAS.map((color, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center" }}>
                {i > 0 && <div style={{ width: 16, height: 2, background: BORDE }} />}
                <div
                  style={{ width: 22, height: 22, borderRadius: 22, background: color }}
                />
              </div>
            ))}
          </div>
          <div style={{ fontFamily: "Mono", fontSize: 26, color: TENUE }}>
            el modelo traduce · el motor decide
          </div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Titular", data: titular, style: "normal", weight: 700 },
        { name: "Cuerpo", data: cuerpo, style: "normal", weight: 500 },
        { name: "Mono", data: mono, style: "normal", weight: 500 },
      ],
    },
  );
}
