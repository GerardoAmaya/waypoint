import L from "leaflet";

/**
 * Dibuja los 5.652 lugares del catalogo como puntos tenues.
 *
 * Es el estado vacio del mapa: antes de escribir nada se ve el material
 * disponible, con los datos reales del proyecto. Un mapa vacio con una caja de
 * texto encima es la respuesta generica.
 *
 * **Un canvas y no marcadores.** Cinco mil seiscientos circleMarker son cinco
 * mil seiscientos objetos de Leaflet con sus eventos y su nodo; aqui es un solo
 * lienzo que se repinta cuando el mapa se mueve. La diferencia se nota al hacer
 * zoom en un telefono.
 */
export class FieldLayer extends L.Layer {
  private canvas: HTMLCanvasElement | null = null;
  private puntos: [number, number][];
  private color: string;
  private _opacidad = 1;

  /**
   * El color llega de afuera y no sale de un literal: lo resuelve Mapa desde
   * el CSS, que es la fuente unica de los materiales del proyecto.
   */
  constructor(puntos: [number, number][], color: string) {
    super();
    this.puntos = puntos;
    this.color = color;
  }

  onAdd(map: L.Map): this {
    const canvas = L.DomUtil.create("canvas", "waypoint-field") as HTMLCanvasElement;
    canvas.style.position = "absolute";
    canvas.style.pointerEvents = "none";
    canvas.style.transition = "opacity 700ms cubic-bezier(0.22, 1, 0.36, 1)";
    this.canvas = canvas;

    const panel = map.getPanes().overlayPane;
    panel.appendChild(canvas);

    map.on("moveend zoomend resize", this.redibujar, this);
    this.redibujar();
    return this;
  }

  onRemove(map: L.Map): this {
    map.off("moveend zoomend resize", this.redibujar, this);
    this.canvas?.remove();
    this.canvas = null;
    return this;
  }

  /**
   * Cambia el color de los puntos.
   *
   * Lo pide el cambio de fondo: sobre el mapa dibujado, que es claro, el punto
   * tiene que ser tinta; sobre la foto de satelite, que es oscura, la tinta
   * desaparece y hace falta un punto claro. No es el tema quien decide esto
   * —el mapa no sigue al tema— sino la capa de teselas que este puesta.
   */
  setColor(color: string): void {
    this.color = color;
    this.redibujar();
  }

  /**
   * Atenua el campo sin quitarlo. Cuando llega un itinerario, los lugares que
   * no entraron siguen ahi de fondo: el plan se lee mejor sabiendo cuanto habia
   * alrededor para elegir.
   */
  setOpacity(valor: number): void {
    this._opacidad = valor;
    if (this.canvas) this.canvas.style.opacity = String(valor);
  }

  private redibujar = (): void => {
    const map = this._map;
    const canvas = this.canvas;
    if (!map || !canvas) return;

    const tamano = map.getSize();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const esquina = map.containerPointToLayerPoint([0, 0]);

    L.DomUtil.setPosition(canvas, esquina);
    canvas.width = tamano.x * dpr;
    canvas.height = tamano.y * dpr;
    canvas.style.width = `${tamano.x}px`;
    canvas.style.height = `${tamano.y}px`;
    canvas.style.opacity = String(this._opacidad);

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, tamano.x, tamano.y);

    // El punto crece con el zoom, pero despacio: a escala de pais son motas y
    // a escala de pueblo tienen que seguir siendo fondo, no competencia.
    const zoom = map.getZoom();
    const radio = Math.max(0.6, Math.min(2.2, (zoom - 6) * 0.32));
    // El color lo pone quien crea la capa y lo cambia setColor: depende del
    // fondo que este puesto, no del tema.
    ctx.globalAlpha = 0.34;
    ctx.fillStyle = this.color;

    const margen = 8;
    for (const [lat, lon] of this.puntos) {
      const p = map.latLngToContainerPoint([lat, lon]);
      if (
        p.x < -margen ||
        p.y < -margen ||
        p.x > tamano.x + margen ||
        p.y > tamano.y + margen
      ) {
        continue;
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, radio, 0, Math.PI * 2);
      ctx.fill();
    }
  };
}
