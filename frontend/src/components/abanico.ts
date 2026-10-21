/**
 * Separar los pines que caen en el mismo punto de la pantalla.
 *
 * El problema, medido sobre los 60 dias del banco proyectados como los
 * proyecta Leaflet: **33 dias (55%) tienen al menos un par de pines
 * superpuestos**, 69 pares en total. Los peores estan literalmente en el mismo
 * pixel —"Ruinas de la Iglesia Vieja" y "Vieja Parroquia de Santa Maria"—. En
 * Suchitoto las paradas 4, 6 y 7 son el casco urbano y se apilan: en un
 * telefono se ve la 4 y dos circulos asomando detras. El numero del pin es el
 * orden del recorrido, y un orden tapado no se lee ni se puede tocar.
 *
 * Con el abanico: **7 dias (12%), 13 pares**.
 *
 * **Queda un residuo y se deja a proposito.** Los 13 pares que sobreviven son
 * cruzados: un pin que se abrio termina cerca de otro grupo que estaba justo
 * fuera del umbral. La salida obvia es repetir la pasada hasta que no quede
 * ninguno, y medida no sirve: con dos, tres y cuatro pasadas el resultado es
 * el mismo —7 dias, 13 pares— porque los grupos se rehacen y oscilan, y el
 * corrimiento maximo sube de 35 a 42 px. Mas pasadas mienten mas sobre donde
 * estan las paradas y no destapan ni un pin.
 *
 * **Se separan en pixeles y no en coordenadas.** Dos paradas a 80 metros se
 * tapan a zoom 12 y se ven perfectamente a zoom 16, asi que lo que decide no
 * es la distancia real sino cuanta pantalla hay entre ellas. Por eso esto se
 * recalcula en cada zoom, y por eso el abanico **desaparece solo** en cuanto
 * hay separacion de verdad: el desplazamiento existe mientras hace falta y no
 * un pixel mas.
 *
 * **El abanico se centra en el punto compartido.** El centro visual del grupo
 * sigue siendo donde estan las paradas; lo que se mueve es cada pin respecto
 * de ese centro, lo minimo para no tocarse. Un pin desplazado miente un poco
 * sobre donde esta su lugar, y el precio de no hacerlo es que tres paradas se
 * vean como una.
 *
 * Es el mismo criterio que group_same_places usa en el backend para agrupar
 * lugares: transitivo. Si A tapa a B y B tapa a C, los tres van al mismo
 * abanico aunque A y C no se toquen entre si.
 */

export interface Punto {
  x: number;
  y: number;
}

/** El ancho del pin en pantalla. Dos pines mas juntos que esto se tocan. */
export const DIAMETRO_PIN = 26;

/**
 * Cuanto hay que correr cada punto para que ninguno tape a otro.
 *
 * Devuelve un desplazamiento por punto, en el mismo orden que entraron. Los
 * que no se tapan con nadie reciben (0, 0), que es lo que deja el pin en su
 * sitio exacto.
 */
export function separar(puntos: Punto[], diametro: number = DIAMETRO_PIN): Punto[] {
  const grupos = agrupar(puntos, diametro);
  const corrimientos: Punto[] = puntos.map(() => ({ x: 0, y: 0 }));

  for (const grupo of grupos) {
    if (grupo.length < 2) continue;

    const centro = {
      x: grupo.reduce((suma, i) => suma + puntos[i].x, 0) / grupo.length,
      y: grupo.reduce((suma, i) => suma + puntos[i].y, 0) / grupo.length,
    };

    // El radio minimo para que dos vecinos del anillo queden justo a un
    // diametro: la cuerda entre dos puntos separados por 2π/n en un circulo de
    // radio r mide 2·r·sin(π/n). Despejando r se obtiene esto. Con dos pines da
    // medio diametro cada uno, o sea que se mueven lo justo para despegarse.
    const radio = diametro / (2 * Math.sin(Math.PI / grupo.length));

    grupo.forEach((indice, orden) => {
      // Se arranca arriba y se gira en el sentido del reloj, que es como se
      // lee un orden. El grupo ya viene ordenado por indice, asi que los
      // numeros del recorrido quedan en secuencia alrededor del circulo.
      const angulo = -Math.PI / 2 + (2 * Math.PI * orden) / grupo.length;
      corrimientos[indice] = {
        x: centro.x + radio * Math.cos(angulo) - puntos[indice].x,
        y: centro.y + radio * Math.sin(angulo) - puntos[indice].y,
      };
    });
  }

  return corrimientos;
}

/**
 * Los indices agrupados por contacto, de forma transitiva.
 *
 * Conjuntos disjuntos sin la estructura: con las paradas de un dia —rara vez
 * mas de diez— el bucle directo es mas corto de leer y no se nota.
 */
function agrupar(puntos: Punto[], diametro: number): number[][] {
  const duenio = puntos.map((_, i) => i);

  const raiz = (i: number): number => {
    while (duenio[i] !== i) i = duenio[i];
    return i;
  };

  for (let i = 0; i < puntos.length; i++) {
    for (let j = i + 1; j < puntos.length; j++) {
      const dx = puntos[i].x - puntos[j].x;
      const dy = puntos[i].y - puntos[j].y;
      if (Math.hypot(dx, dy) < diametro) duenio[raiz(j)] = raiz(i);
    }
  }

  const porRaiz = new Map<number, number[]>();
  for (let i = 0; i < puntos.length; i++) {
    const r = raiz(i);
    const grupo = porRaiz.get(r);
    if (grupo) grupo.push(i);
    else porRaiz.set(r, [i]);
  }

  return [...porRaiz.values()];
}
