/**
 * La tarjeta que sale al pegar el enlace de un itinerario en un chat.
 *
 * **La función de compartir vivía a medias.** Todo su propósito es pegar la
 * URL en algún sitio, y hasta ahora salía el título del sitio: el mismo texto
 * para tres días por la Ruta de las Flores que para una tarde en San Salvador.
 *
 * La tarjeta dice el plan, no el producto: la zona, las fechas, y una tira de
 * puntos por día —uno por parada, del color de su categoría— que hace que dos
 * itinerarios distintos se vean distintos antes de abrirlos.
 *
 * Satori solo entiende flexbox y un subconjunto de CSS: nada de `grid`, nada
 * de `var()`, y las fuentes se pasan a mano en `ttf`, `otf` o `woff` —no lee
 * `woff2`, que es lo que la web del sitio usa—. De ahí las dos versiones de
 * cada archivo en `app/fuentes`.
 */

import { ImageResponse } from "next/og";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { fetchCompartido } from "@/lib/api";
import { material } from "@/lib/paleta-servidor";
import { describir, type Tarjeta } from "@/lib/tarjeta";
import type { Category } from "@/lib/types";

export const alt = "Un itinerario de Waypoint por El Salvador";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const fuente = (archivo: string) =>
  readFile(join(process.cwd(), "src/app/fuentes", archivo));

const [titular, cuerpo, mono] = await Promise.all([
  fuente("bricolage-700.ttf"),
  fuente("bricolage-500.ttf"),
  fuente("dm-mono-500.ttf"),
]);

const COLOR: Record<Category, string> = {
  food: material("cafe"),
  nature: material("verde"),
  culture: material("ocre"),
  viewpoint: material("ocre"),
  attraction: material("anil-claro"),
  lodging: material("acero-claro"),
};

const FONDO = material("basalto");
const TINTA = material("niebla");
const TENUE = material("acero");
const BORDE = material("basalto-borde");

/**
 * Cuántas paradas de un día caben en la tira antes de que los puntos se
 * aprieten. Pasado ese número, el resto se dice con un "+n": la tira existe
 * para que se vea la forma del día, y veinte puntos de 14 px no tienen forma.
 */
const PUNTOS_QUE_CABEN = 14;

function Dia({
  etiqueta,
  paradas,
  conEtiqueta,
}: Tarjeta["dias"][number] & { conEtiqueta: boolean }) {
  const visibles = paradas.slice(0, PUNTOS_QUE_CABEN);
  const resto = paradas.length - visibles.length;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      {/*
        Un viaje de un solo día ya lleva la fecha arriba, y repetirla al lado
        de su única tira la convierte en ruido. Sin etiqueta tampoco hace falta
        el canal que la alinea.
      */}
      {conEtiqueta && (
        <div
          style={{
            fontFamily: "Mono",
            fontSize: 26,
            color: TENUE,
            width: 120,
          }}
        >
          {etiqueta}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center" }}>
        {visibles.map((categoria, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center" }}>
            {/* El tramo entre dos paradas, que es lo que hace que se lea como
                un día y no como una fila de fichas. */}
            {i > 0 && <div style={{ width: 16, height: 2, background: BORDE }} />}
            <div
              style={{
                width: 22,
                height: 22,
                borderRadius: 22,
                background: COLOR[categoria] ?? TENUE,
              }}
            />
          </div>
        ))}
        {resto > 0 && (
          <div
            style={{
              fontFamily: "Mono",
              fontSize: 22,
              color: TENUE,
              marginLeft: 16,
            }}
          >
            +{resto}
          </div>
        )}
      </div>
    </div>
  );
}

export default async function Imagen({
  params,
}: {
  params: Promise<{ codigo: string }>;
}) {
  const { codigo } = await params;

  let tarjeta: Tarjeta | null = null;
  try {
    const guardado = await fetchCompartido(codigo);
    tarjeta = describir(guardado.interpretation, guardado.itinerary);
  } catch {
    // Un código que ya no existe, o el backend caído. La tarjeta sale igual,
    // con lo que se sabe sin él: una tarjeta rota en el chat de otra persona
    // es peor que una genérica, y quien la vea va a abrir el enlace de todos
    // modos para encontrarse con el 404 de la aplicación, que sí lo explica.
  }

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
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
          <div
            style={{
              fontFamily: "Titular",
              fontSize: tarjeta && tarjeta.titulo.length > 24 ? 76 : 96,
              lineHeight: 1.05,
            }}
          >
            {tarjeta?.titulo ?? "Un itinerario por El Salvador"}
          </div>
          {tarjeta?.fechas && (
            <div style={{ fontSize: 34, color: TENUE }}>{tarjeta.fechas}</div>
          )}
        </div>

        {/*
          Ocupa el hueco entre la cabecera y el pie y se centra dentro: con
          `space-between` a secas, un viaje de un día dejaba su única tira
          flotando a media altura, más cerca del pie que del título.
        */}
        <div
          style={{
            display: "flex",
            flex: 1,
            flexDirection: "column",
            justifyContent: "center",
            gap: 18,
          }}
        >
          {(tarjeta?.dias ?? []).slice(0, 4).map((dia, i) => (
            <Dia key={i} {...dia} conEtiqueta={(tarjeta?.dias.length ?? 0) > 1} />
          ))}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            borderTop: `2px solid ${BORDE}`,
            paddingTop: 24,
          }}
        >
          {/*
            Sin itinerario no hay resumen que dar, y rellenarlo con una frase
            del producto la partía en dos líneas y empujaba a la de la derecha
            a partirse también.
          */}
          <div style={{ fontFamily: "Mono", fontSize: 30 }}>
            {tarjeta?.resumen ?? ""}
          </div>
          <div style={{ fontSize: 26, color: TENUE }}>
            distancias medidas sobre carretera
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
