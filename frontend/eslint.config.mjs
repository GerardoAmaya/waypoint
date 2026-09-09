import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

/*
  El script "lint" existia desde el principio y no podia correr: eslint no
  estaba instalado y no habia configuracion. Un lint que falla al invocarse es
  peor que no tenerlo, porque nadie lo vuelve a intentar.

  core-web-vitals trae las reglas de accesibilidad de jsx-a11y ademas de las de
  Next, que son las que importan en un proyecto de una sola pantalla donde el
  piso de calidad es explicito.
*/
const configuracion = [
  { ignores: ["**/.next/**", "next-env.d.ts"] },
  ...nextCoreWebVitals,
  ...nextTypescript,
];

export default configuracion;
