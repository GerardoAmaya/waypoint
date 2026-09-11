/**
 * Configuracion de los tests del frontend.
 *
 * Vitest y no Jest porque el proyecto ya compila con esbuild por debajo y no
 * hay que enseñarle a leer TypeScript ni JSX otra vez. El entorno es jsdom
 * porque lo que se prueba son componentes: que el texto sobreviva a un
 * desmontaje, que un boton este deshabilitado, que el tema escriba el valor
 * que el CSS espera.
 *
 * **Lo que NO se prueba aca es el mapa.** Leaflet toca window al importarse y
 * mide elementos que en jsdom no tienen tamaño; probarlo aqui seria probar un
 * doble. El mapa se verifica en un navegador de verdad.
 */
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    /*
      La zona se fija a la de El Salvador, que es donde se usa el sitio.
      Hace falta para que valgan los tests de fechas: una fecha ISO parseada
      como UTC se corre un dia hacia atras solo al oeste de Greenwich, asi
      que en CI —que va en UTC— el fallo no aparece y el test pasaria
      igual con el codigo roto.
    */
    env: { TZ: "America/El_Salvador" },
    setupFiles: ["./src/pruebas/preparacion.ts"],
    include: ["src/**/*.prueba.tsx", "src/**/*.prueba.ts"],
    globals: true,
    restoreMocks: true,
  },
});
