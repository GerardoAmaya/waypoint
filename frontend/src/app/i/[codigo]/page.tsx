/*
  La ruta de un itinerario compartido.

  Renderiza la misma pantalla que la raíz: armar un itinerario y abrir uno
  guardado terminan en la misma vista, y duplicarla sería mantener dos.

  Existe como ruta de verdad y no como parámetro de consulta para que recargar
  la página funcione: con `/?i=codigo` un refresco en Next.js serviría la raíz
  y perdería el itinerario. El código lo lee la pantalla de la URL.
*/
export { default } from "../../page";
