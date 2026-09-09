/**
 * El rotulo del pais, arriba del titular.
 *
 * Lo que le faltaba a la pantalla de inicio: el pais solo se deducia del mapa,
 * y quien llega sin conocer el proyecto no tiene por que saber que el catalogo
 * es de un pais y no del mundo. Enterarse escribiendo "tres dias en Antigua" y
 * recibir un "no conozco esa zona" es enterarse tarde.
 *
 * **Las tres franjas y no la bandera, ni el emoji.** El emoji 🇸🇻 se dibuja
 * como las letras "SV" en Windows, que no tiene glifos de banderas: en un sitio
 * publico eso le pasaria a una parte de las visitas. Y Font Awesome libre no
 * trae banderas de paises.
 *
 * Dibujarla entera pediria el escudo, que a doce pixeles es una mancha. Las
 * tres franjas se leen, funcionan en cualquier navegador y no caen en lo obvio.
 *
 * El azul es literal y no un token de la paleta a proposito: es el color de la
 * bandera, no una decision de diseno de este proyecto, y meterlo en el sistema
 * de temas invitaria a "ajustarlo" para que combine.
 *
 * El contorno SI es un token, y hace falta: sin el, en tema claro la franja
 * blanca del medio se pierde contra el panel y la marca se lee como dos barras
 * azules sueltas en vez de como una bandera. El relleno es del pais, el
 * contorno es de la interfaz.
 */
export default function Pais() {
  return (
    <p className="flex items-center gap-2 text-menudo tracking-[0.14em] text-tinta-tenue uppercase">
      <svg
        width="18"
        height="12"
        viewBox="0 0 18 12"
        aria-hidden
        className="shrink-0 rounded-[2px]"
      >
        <rect width="18" height="12" fill="#fff" />
        <rect width="18" height="4" fill="#0F47AF" />
        <rect y="8" width="18" height="4" fill="#0F47AF" />
        <rect
          x="0.5"
          y="0.5"
          width="17"
          height="11"
          rx="1.5"
          fill="none"
          stroke="var(--borde-fuerte)"
        />
      </svg>
      El Salvador
    </p>
  );
}
