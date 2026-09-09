# Waypoint

Planificador de viajes conversacional por El Salvador. Escribís tus gustos y
restricciones en lenguaje natural y el sistema arma un itinerario de varios días
sobre un mapa, con lugares reales y distancias reales.

**En construcción.** Fases 0 a 5 y 7 cerradas: infraestructura, catálogo desde
OpenStreetMap, consultas espaciales con PostGIS, motor de itinerarios con
restricciones duras, rutas reales de OpenRouteService, capa conversacional con
streaming y edición incremental, y evaluación automática. Falta el frontend y
el despliegue. Ver `PLAN.md` para el alcance completo.

---

## Correr localmente

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api alembic upgrade head
curl http://localhost:8100/health
```

Un itinerario de dos días en la Ruta de las Flores:

```bash
curl -s -X POST localhost:8100/itinerary \
  -H 'Content-Type: application/json' \
  -d '{"center_lat":13.8697,"center_lon":-89.8467,"days":2,"max_travel_km_per_day":40}'
```

Sin llave de OpenRouteService funciona igual, con distancias estimadas. La
respuesta lo dice en el campo `travel.source`.

---

## Cómo está partido el problema

El modelo de lenguaje traduce la frase del usuario a restricciones. El motor las
hace cumplir. Esa división es deliberada y es la respuesta al riesgo principal
del proyecto: si el modelo armara el itinerario directamente, «odio madrugar»
sería una sugerencia que a veces ignora. Acá es una hora mínima de inicio que el
algoritmo no puede violar.

Como consecuencia, el motor es determinista y por lo tanto medible: dado un
conjunto de restricciones se puede comprobar automáticamente si el resultado las
cumple. Lo que no se pudo cumplir viaja en la respuesta como violación, con su
magnitud, en vez de esconderse.

---

## Decisiones medidas

Cada una salió de un número, no de una intuición. Los guiones que las midieron
están en `backend/scripts/` y se pueden volver a correr.

### Una matriz por itinerario, no una ruta por par

El endpoint `/v2/matrix` de OpenRouteService admite 3.500 pares origen × destino
por petición. Un itinerario de siete días con treinta y cinco paradas son 1.225
pares: **una sola llamada**.

Pedir cada par por separado habría sido ruinoso. El 2-opt del motor evalúa
cientos de rutas candidatas por día, y cada evaluación mide todos sus tramos. Con
una llamada HTTP por par, un solo itinerario agotaría el cupo diario.

La abstracción que lo hace posible es `TravelProvider`: el motor pide traslados y
no sabe si el número vino de una carretera o de una estimación. Eso también deja
los tests corriendo sin red.

### El cupo real son 50 peticiones por día, no 2.000

El endpoint de direcciones da 2.000 diarias y es el número que aparece en la
documentación. El de matriz da 50. Se lee en el encabezado `x-ratelimit-limit` de
cualquier respuesta.

A ese cupo, una demo pública que consulte en vivo se queda seca antes del
mediodía. Por eso la cache en `travel_edges` no es una optimización: es lo que
sostiene el proyecto. La distancia entre dos puntos fijos no cambia, así que se
paga una vez por par y no una vez por itinerario.

Dos detalles que cambian el manejo de errores:

- Al agotar el cupo, ORS responde **403, no 429**. Tratarlo como problema de
  credenciales manda a revisar la llave cuando lo único que hay que hacer es
  esperar.
- La ventana se reinicia 24 horas después de la primera petición, no a
  medianoche, así que se va corriendo día a día. Por eso el presupuesto propio
  (`DailyQuota`) cuenta sobre una ventana deslizante y no sobre un contador que
  se pone en cero.

El presupuesto propio vive en memoria y se pierde al reiniciar el proceso, así
que el encabezado `x-ratelimit-remaining` manda sobre nuestra cuenta: es la única
cifra que ve también las peticiones de otra instancia con la misma llave.

### El invariante geométrico: cuando la fuente miente

Un itinerario dentro del Parque El Imposible salió con tres paradas y **cero
kilómetros entre ellas**. Los puntos están separados por 1.89 km.

Los tres están lejos de toda carretera, así que ORS los enganchó al mismo nodo de
la red vial y devolvió `0.0`. No es un nulo —el manejo de nulos por celda ya
estaba— sino una medida válida de un viaje que no existe. La respuesta salió con
`source: "real"` y `real_ratio: 1.0`.

Estar equivocado así es peor que estimar: la estimación al menos avisa.

El arreglo es un invariante que no admite excepciones. **Una ruta por carretera
no puede medir menos que la línea recta.** Las celdas por debajo de ese piso se
descartan por par, para que un enganche malo no cueste las otras medidas del
bloque, y caen a la estimación calibrada.

La migración `0004` limpia las que ya estaban guardadas. El invariante filtra lo
que entra, pero la cache seguía sirviendo los ceros viejos.

### Calibración de la estimación

`DETOUR_FACTOR` y las velocidades se habían elegido a ojo. `calibrate_travel` las
midió contra 812 pares reales del catálogo:

| Tramo | Pares | Desvío | km/h en carro |
|---|---|---|---|
| menos de 2 km | 8 | 1.36 | 34.9 |
| 2 a 10 km | 50 | 1.48 | 41.0 |
| 10 a 50 km | 290 | 1.41 | 55.9 |
| más de 50 km | 464 | 1.51 | 61.6 |

**El desvío aguanta ser una constante, la velocidad no.** El desvío no tiene
tendencia con la distancia: es ruido alrededor de 1.45. La velocidad sube de 35 a
62 km/h, y tiene sentido físico —el salto corto es urbano con semáforos y el
largo es carretera—. Con un solo valor de 40 km/h, los tramos largos salían al
doble de su tiempo real.

Lo más útil de esta medición fue lo que evitó. Una primera prueba con un solo
par, San Salvador a Santa Ana, dio un desvío de 1.26 y sugería **bajar** la
constante. Ese par es la mejor carretera del país. La mediana sobre 812 pares
dice que 1.35 se quedaba corto y hay que subirla a 1.45.

A pie, ORS devolvió 5.0 km/h exactos en los cuatro tramos. Eso no es una medición
del terreno: es la constante de su perfil peatonal, que ignora la pendiente. En
un país de volcanes conviene recordarlo antes de presentar esos tiempos como dato
duro.

### La comida se ubica por costo, no por reloj

Un día en Ataco salía parque → pueblo → parque: tres paradas dentro del Parque El
Imposible, dieciséis kilómetros hasta el único restaurante, y quince de vuelta.
34 km para un recorrido que dentro del parque son cinco.

El 2-opt había ordenado bien. El daño venía después, al intercalar la comida por
hora de llegada eligiendo el restaurante más cercano a la parada anterior: el
costo de volver no entraba en la cuenta nunca.

Ahora cada comida va donde menos kilómetros agregue, entre las posiciones cuya
hora cae dentro de la franja. **El límite de traslado sigue mandando sobre la
comida**: si el único restaurante rompe el presupuesto, no hay almuerzo, y se
reporta como restricción incumplida para que el usuario decida si lleva comida o
levanta el límite. Meterlo rompiendo el límite sería elegir por él.

### Restricciones duras que el motor hace cumplir

Las categorías que el usuario pide evitar se descartan en el motor, no se
penalizan en el ranking. Restarles puntos solo las manda al final de la lista, y
basta con que sobre un cupo para que entren igual. Depender de que la capa de
consulta las haya filtrado antes deja el límite a merced de quién llame.

---

## Métricas

| Qué | Cuánto |
|---|---|
| Cumplimiento de límites duros | 96% (25 de 26 casos) |
| Lugares inventados | 0 de 285 paradas generadas |
| Factor de desvío medido | 1.45, mediana sobre 812 pares |
| Velocidad efectiva en carro | 35 a 62 km/h según el tramo |
| Pares sin ruta en ORS | 7% (58 de 870) |
| Cupo del endpoint de matriz | 50 peticiones / ventana de 24 h |
| Peticiones por itinerario en zona fría | 1 |
| Lugares en el catálogo | 5.652 activos de 6.296 bajados |
| Descarte del filtro de calidad | 5.9% (370 registros) |
| Duplicados fusionados | 4.4% (274 registros) |
| Tests | 315 |

El 7% sin ruta son puntos lejos de toda carretera —cumbres de volcanes,
cascadas— que caen a estimación siempre, haya cupo o no. Ese número es también lo
que valida tratar los nulos por celda: con manejo por respuesta se habrían
perdido bloques enteros por una cascada mal ubicada.

### La forma del catálogo condiciona el producto

Quitando comida y alojamiento quedan 2.427 destinos, y están repartidos así:

| Categoría | Cuántos | Del total de destinos |
|---|---|---|
| nature | 2.024 | 83,4% |
| culture | 286 | 11,8% |
| attraction | 82 | 3,4% |
| viewpoint | 35 | 1,4% |

**Treinta y cinco miradores en todo el país.** OpenStreetMap en El Salvador está
mapeado con mucho detalle para restaurantes y accidentes naturales, y muy poco
para atracciones. Eso tiene tres consecuencias directas:

La puntuación por atractivo (`SUBCATEGORY_APPEAL`) carga con el 83% del catálogo.
En OSM, `leisure=park` incluye cada plaza municipal del país, así que sin esa
distinción un redondel puntúa igual que un volcán. No es un refinamiento: es lo
único que separa los destinos del mobiliario urbano.

Repartir el cupo de búsqueda entre categorías rinde menos de lo que parece. Con
35 miradores nacionales, una zona cualquiera aporta dos o tres, y el itinerario
termina apoyándose en `nature` casi siempre.

Y hay 1,12 restaurantes por cada destino, así que reservar cupo para comer casi
siempre tiene con qué llenarse. La excepción son los parques nacionales, que es
exactamente donde el motor falló primero. Ese fallo no fue mala suerte: es la
consecuencia previsible de la forma del catálogo.

---

## Cómo se mide el cumplimiento

26 peticiones con restricciones conocidas, sobre 11 zonas. **El corpus incluye a
propósito las zonas donde el sistema sufre**: Perquín tiene nueve lugares que no
son destino en quince kilómetros, Costa del Sol tiene diecisiete destinos en
total, y dentro del Parque El Imposible no hay dónde comer. Una muestra que solo
tomara San Salvador y la Ruta de las Flores mediría un sistema más fácil.

**Las comprobaciones no usan `validate()`.** El motor arma el itinerario y
después lo juzga con la misma lógica; medir así mide consistencia consigo mismo.
El evaluador relee la salida y deriva las condiciones de cero, y eso además deja
comprobar cosas que `validate()` ni mira: un lugar repetido entre dos días, una
parada fuera del radio, un horario que retrocede, un identificador ausente del
catálogo.

### Límites duros y recomendaciones son cosas distintas

Al principio las mezclé y el cumplimiento daba 58%. La mitad de los «fallos» eran
días sin almuerzo, y eso no es romper un límite que el usuario puso: es no poder
dar algo que quería. Separadas, el cumplimiento de límites duros es 96%, y el
único fallo es correcto —Alegría no tiene material para siete días y el sistema
lo reporta en vez de inventar contenido—.

Con las dos juntas, el número describía la cobertura de restaurantes de
OpenStreetMap en El Salvador y no la calidad del planificador.

### El almuerzo se aconseja, no se impone

Cuando el restaurante más conveniente no entra en el presupuesto de kilómetros,
el día queda completo y sale un consejo con el número:

> el lugar para comer más conveniente es Comedor Los Tarros, que agrega 14.2 km
> y dejaría el día en 34.5 km, sobre tu límite de 25. Llevá almuerzo, o subí el
> límite de traslado a 35 km

Se intentó lo contrario —achicar el día para hacerle lugar— y estaba mal. Alguien
pide cinco paradas y un almuerzo; devolverle cuatro destinos a cambio de un
comedor es decidir por él. Llevar comida es una solución del mundo real, saltarse
un volcán no lo es.

**El aviso anterior además mentía.** Decía «no hay ningún lugar para comer en la
zona», y sobre 12 días medidos, **los 12** tenían restaurantes al alcance: lo que
no entraba eran los kilómetros. Decir la causa equivocada es peor que no decir
nada.

Eso deja un hallazgo sobre el valor por defecto: `max_travel_km_per_day: 25` es
lo bastante apretado como para dejar al 21% de los días sin almorzar.

---

## Limitaciones conocidas

**La parada marginal resultó no ser un problema.** Quedó abierto si el motor
agrega paradas que cuestan desproporcionadamente: en Ataco, una quinta parada
sumaba 16 km de rebote. Medido sobre 54 días, quitar la parada intermedia más
cara ahorra un 22% mediano, que es aproximadamente lo proporcional. Ataco era un
caso duro, no un patrón, y la conclusión es no agregar ninguna regla.

La primera versión de esa métrica estaba mal diseñada: medía qué fracción del día
aporta el tramo más largo, y eso depende de cuántos tramos haya —con dos, el
mayor pasa del 50% por aritmética—. Una mediana del 45% no distinguía un mal
reparto de un día corto.

**La reserva de cupos para comer se cuenta por itinerario, no por día.**
`build_days` arma todos los grupos antes de que se repartan las comidas, así que
con tres restaurantes para cinco días los últimos reservan sitio que no van a
llenar. Es una imprecisión acotada y en la dirección segura.

**El tramo corto de la calibración se apoya en 8 pares.** Es el menos firme de
los cuatro y probablemente el más frecuente en un itinerario real, porque las
paradas de un mismo día están cerca entre sí.

**El costo por itinerario en tokens no está medido.** Sí lo está el de rutas: una
petición a OpenRouteService por itinerario en zona fría, cero con la caché
caliente.

---

## Stack

| Capa | Elección |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Base de datos | PostgreSQL + PostGIS, migraciones con Alembic |
| Lugares | OpenStreetMap vía Overpass, cargado una vez |
| Rutas | OpenRouteService, endpoint de matriz |
| Modelo | Claude (Haiku para armar, Sonnet para conversar) |
| Tests | pytest, 315 casos |
| CI | GitHub Actions, con migraciones en ambos sentidos |

Sin Celery: la carga del catálogo es un guion que corre una vez y la generación
de itinerarios es petición-respuesta. Sin embeddings: la selección de lugares se
resuelve con filtros espaciales y por categoría.

---

## Guiones

```bash
make ors-check       # verifica la llave y lee el cupo restante
make ors-calibrate   # mide desvío y velocidad contra el catálogo
make ors-warm        # precalienta la cache por zona (no gasta sin --apply)
```

`ors-warm` sin `--apply` solo dice cuánto costaría. Con 50 peticiones diarias, un
guion que consuma cupo por equivocación sale caro.

---

## Lo que falta

Fase 5: capa conversacional, con interpretación de la frase del usuario y edición
incremental. Fase 6: frontend con mapa y línea de tiempo. Fase 7: evaluación
automática del cumplimiento de restricciones. Fase 8: despliegue y límite por IP.
