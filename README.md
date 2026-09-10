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

Para publicarlo, ver `DEPLOY.md`.

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

### Repetir categoría cuesta kilómetros

Un día de cuatro cerros seguidos no es un día que alguien quiera. La causa no
era el azar: `build_days` sembraba el día con el mejor lugar sin usar y lo
llenaba con **los más cercanos a la semilla**, sin mirar qué había ya en el día.
Y como los lugares de una misma categoría están agrupados en el terreno —los
cerros comparten cresta, las iglesias comparten centro— un día sembrado con un
cerro se llenaba de cerros.

Medido sobre los 26 casos de evaluación, antes del cambio: el 75% de los días
tenían una categoría en la mitad o más de sus paradas, y el 45% tenían tres o
más seguidas iguales.

La corrección es un término en el orden de llenado: la segunda parada de una
categoría que ya está en el día tiene que estar `REPEAT_PENALTY_KM` kilómetros
más cerca que una de categoría nueva para ganarle el sitio. Va en kilómetros
para que sea comparable con lo único que el llenado medía hasta ahora.

**Es un desempate, no un filtro.** Donde el catálogo solo tiene una clase de
lugar —Perquín, Costa del Sol— el día sigue saliendo de esa clase, porque no
hay otra cosa. Filtrar por categoría repetida dejaría esos días a medio llenar,
que es peor que un día monotemático. Hay un test para cada mitad de esa frase.

El valor sale de barrer de 0 a 40 sobre los 26 casos:

| penalización | cumple | km/día | cats/día | una cat ≥50% | racha 3+ |
|---|---|---|---|---|---|
| 0 (antes) | 25/26 | 10,4 | 2,63 | 75% | 47% |
| 6 | 25/26 | 13,1 | 3,23 | 53% | 28% |
| **12** | **25/26** | **14,3** | **3,28** | **44%** | **21%** |
| 20 | 25/26 | 15,2 | 3,30 | 39% | 19% |
| 40 | 25/26 | 15,1 | 3,32 | 39% | 16% |

A partir de 20 la variedad se satura —lo que queda es catálogo que de verdad
solo tiene una clase de lugar— y se empiezan a perder paradas: 281 contra las
284 de 12, porque algún día ya no encuentra con qué llenarse.

En 12 se recoge casi toda la mejora disponible y no se paga por ningún lado que
importe: el cumplimiento de límites duros no se mueve (25/26 en todo el
barrido), ningún día se pasa de su presupuesto de traslado —el peor sigue en el
99%, igual que antes—, y el atractivo medio de las paradas elegidas no baja:
0,699 contra 0,694. Los 4 km/día de más salen de un presupuesto que casi nunca
estaba ajustado.

La métrica vive en `scripts/evaluate.py` y no en un cuaderno: la penalización es
una constante del motor, y una constante sin métrica que la vigile es una
constante que alguien baja sin darse cuenta.

### El largo del día lo decide la hora que pediste, no un contador

`max_stops_per_day` traía un 5 por defecto, y ese 5 decidía cuándo terminaba el
día. Con una petición de 10 de la mañana a 11 de la noche, el itinerario
cerraba a las 15:52 con siete horas sin usar: `latest_end` solo servía de techo
para recortar, nunca de objetivo para llenar. La hora de la cena, que empieza a
las 18:00, era inalcanzable por construcción — se pidiera o no.

Ahora el tope solo es un límite si se pidió: sin número, mandan el reloj y los
kilómetros, que son los límites que sí vienen del usuario, con una barrera
interna de 12 paradas para que "sin número" no signifique "sin límite".

Llenar por reloj destapó dos cosas que había que medir. La primera, que el día
se gastaba el presupuesto entero en destinos y luego el restaurante no cabía:
los días con "llevá comida" pasaron del 31% al 68%. La reserva de kilómetros
para la comida tuvo tres versiones, las tres medidas:

| Cómo se reserva | Paradas | Llevá comida |
|---|---|---|
| Fracción fija del presupuesto (0,09) | 299 | 22/62 |
| Distancia al comedor más cercano × 2 | 297 | 24/62 |
| **Coste real de meter la comida** | **300** | **21/62** |
| Lo mismo, sobre la ruta ya ordenada | 298 | 23/62 |

La segunda versión parecía la más principiada y era la peor, y el diagnóstico
dice por qué: un día se quedaba sin almuerzo **con el restaurante a 230
metros**, porque meterlo costaba 3,2 km igual. El coste no lo manda la cercanía
sino la hora — el comedor tiene que ir donde el reloj lo permite, no donde
queda cerca — y eso solo lo sabe la inserción.

La segunda cosa que destapó fue la variedad. `REPEAT_PENALTY_KM` estaba medido
para días de cinco paradas, donde casi no cabe una racha de tres; con días de
ocho, las rachas subieron del 21% al 38% de los días. Vuelto a barrer, la
rodilla está en 24:

| Penalización | Paradas | Rachas de 3+ |
|---|---|---|
| 12 | 317 | 38% |
| 18 | 309 | 33% |
| **24** | **306** | **31%** |
| 30 | 305 | 31% |
| 40 | 305 | 31% |

**El costo honesto de todo esto está en una fila que empeora.** "Días con una
racha de 3+" crece solo con el largo del día, así que la medida buena es la
repetición normalizada: qué proporción de pasos consecutivos repiten categoría.
Es 29% con días llenos contra 24% con días de cinco paradas. No es solo un
artefacto del largo: cuando se acaba la variedad cercana, el día sigue metiendo
lo que queda, que suele ser la categoría dominante de la zona.

### Los centros comerciales: uno por viaje, y de ahí se sale

"Partir desde Metrocentro Santa Ana" fallaba con "no encontré ese lugar", y la
causa era simple: la consulta de Overpass pedía turismo, comida, naturaleza,
histórico, cultura y edificios de hotel, y **nada de comercio**. No había ni un
centro comercial en el catálogo. En OSM sí los hay: 172 con `shop=mall` en el
país. Ahora son 132 activos después del filtro.

Dos decisiones sobre qué hacer con ellos, y la segunda vino del uso:

**De un centro comercial se sale, no se visita.** El punto de partida ocupaba el
tiempo de visita de su categoría, y con un hotel no se notaba porque
alojamiento ya duraba 0 minutos. Con un centro comercial saltó a la vista:
Metrocentro se llevaba hora y media antes de que el día arrancara. Ahora el
punto de partida dura 0 pase lo que pase, salvo que sea la comida del día.

**Uno por itinerario.** Aceptarlos como destino llevó el 15% de las paradas del
arnés a centros comerciales: 46 de 310, con "Las Pulgas" y "Metrocentro" siete
veces cada uno. La penalización por subcategoría los dispersa dentro de un día
pero no impide cinco en tres días, y el problema no es la variedad — es que
nadie quiere ir a dos centros comerciales en el mismo viaje. Con el tope: 13
apariciones, y el arnés mejora en todo frente a no aceptarlos (300 paradas
contra 297, variedad 3,40 contra 3,11, 29% de días con "llevá comida" contra
32%).

El tope **no alcanza a lo que el usuario nombra**: quien pide ir a Metrocentro
y a Metrosur quiere los dos, y un límite del motor no puede contradecir un
pedido explícito.

Y ahí apareció un bug propio, del cambio de la sesión anterior: la regla de "un
nombre por itinerario" reservaba los nombres de los lugares pedidos **al
empezar**, y el filtro del llenado excluye lo que está en esa lista — incluidos
los pedidos mismos. Solo entraban los que caían de semilla, y el segundo se
reportaba como restricción incumplida. El test que debía cubrirlo usaba dos
días, así que cada pedido caía de semilla en el suyo y pasaba sin probar nada.

### Si dijiste dónde empezás, todos los días empiezan ahí

El ancla valía para todos los días solo cuando se pedía volver a dormir ahí; en
otro caso, solo el primero. El razonamiento era bueno —"tres días por el
occidente saliendo de San Salvador" no vuelve a San Salvador cada noche— pero
dejaba fuera el caso más común, y el resultado no era practicable: "dos días en
Santa Ana partiendo de Metrocentro Santa Ana" armaba un segundo día **a pie**
que arrancaba en el Volcán de Santa Ana, a veinte kilómetros. Un día caminando
al que no se puede llegar caminando.

Lo que distingue los dos casos no es una palabra del prompt, es la geometría:
**si el punto de partida cae dentro de la zona, ahí te alojás**. Si cae fuera,
estás saliendo hacia otro lado. La distancia decide.

**Y eso destapó que anclar un día lo volvía miope.** El día anclado se llenaba
hacia afuera desde el punto de partida por cercanía, así que el mejor lugar de
la zona no entraba nunca: con "dos días en Santa Ana" el Cerro Singuil quedaba
fuera **incluso con noventa kilómetros de presupuesto**, porque siempre había un
museo más cerca, y el día cerraba a las 15:12 con cinco horas sin usar. Ahora el
primer destino de un día anclado se elige por lo que vale —`disponibles` ya
viene ordenado por `score_candidate`, así que el primero que quepa es el mejor
que quepa— y pasa a ser la semilla, de modo que el resto del día se agrupa a su
alrededor y no alrededor del punto de partida.

### La luz se acaba cuando se acaba, no cuando llegás

La regla del anochecer miraba la **llegada**. Un cerro de tres horas que
arrancaba a las 15:37 pasaba el filtro y terminaba a las 18:37: veintidós
minutos después de que oscurece, tres horas de monte que acaban a oscuras.
Ahora, al aire libre, lo que tiene que caber antes del anochecer es la visita
entera.

Bajo techo sigue mandando la llegada, y la asimetría es deliberada: si el museo
cierra a las seis, lo que importa es haber entrado antes, no que te echen a y
media.

Costó dos paradas de 300 y **mejoró las comidas**, de 29% a 24% de días con
"llevá comida": los días dejan de terminar con una caminata larga a última hora
y les queda sitio para comer.

### Reservar lo que no alcanza es perder dos veces

La reserva de kilómetros para la comida tenía un tope del 30% del presupuesto
del día. El tope no recortaba la reserva: **la volvía inútil.** Si el
restaurante más barato cuesta más de lo que queda, guardar kilómetros no lo
hace entrar y sí le quita una parada al día.

Medido con "dos días en Santa Ana": el día del carro guardó 7,5 km, no colocó
ninguna comida y cerró con **una sola parada a las 13:26**, con seis
kilómetros de veinticinco. Ahora el tope decide *si* vale la pena reservar, no
cuánto: por encima de él la comida está fuera de alcance, no se reserva nada, y
el consejo de llevar comida —que ya existe y dice el número— hace su trabajo.

Costó cero y pagó cuatro paradas: 298 → 302, con los días de "llevá comida"
igual en 24%.

**Y dos cosas que probé el mismo día y quité**, porque el arnés no las
justificó: proteger del recorte el lugar de más atractivo del día, y reordenar
el día para darle la mañana a una visita al aire libre que al final terminaría
de noche. Las dos son razonables sobre el papel y ninguna movió una métrica.
El caso que las motivaba resultó no tener solución: ir al Cerro Singuil y
volver cuesta 32 km contra un presupuesto de 25, y dejarlo al final cabe en
19,4 pero termina a las 18:17, de noche. No es un fallo del motor, son dos
límites que no se pueden cumplir a la vez — y con "no me importa manejar hasta
90 km" el cerro entra, medido.

### Decir la causa equivocada, otra vez

Dos números en la misma pantalla que no cuadraban, y una cabecera que
contradecía al mapa. Los dos salieron de mirar una captura de un itinerario de
Santa Ana.

**"2 días · 8 paradas" arriba y 6 + 3 en las pestañas.** Al arreglar la cuenta
total para que no contara el hotel cuatro veces, la de cada día se quedó
contando líneas de la lista. Dos reglas distintas en el mismo panel, y
cualquiera puede sumar. La cuenta por día la manda ahora el backend —`visits`
en `DayOut`— porque el cliente no puede deducir cuál parada es el punto de
partida: quien lo sabe es el motor, que tiene las restricciones a mano.

**Y la peor: la cabecera decía "estas paradas están lejos de toda carretera y
no se pueden medir" mientras el mapa dibujaba siete de nueve tramos por
carretera.** La causa no era el terreno, era el cupo. ORS contesta `403 Quota
exceeded` a la matriz, y la lógica que elige el motivo razonaba así:

```python
elif not stats.requests:   # sin cupo se ve como cero peticiones
    stats.reason = "no_quota"
else:
    stats.reason = "unroutable"
```

Un 403 **sí** cuenta como petición hecha, así que caía en el `else`. Y la
respuesta de un 403 no trae la cabecera `x-ratelimit-remaining`, con lo cual el
cliente tampoco se enteraba de que se había quedado sin nada. Ahora un 403 pone
el cupo de ese endpoint en cero, que es la única noticia fiable que da, y el
motivo sale `no_quota`.

Las dos causas se arreglan distinto y por eso importa distinguirlas: una se
espera a que ruede la ventana de 24 horas, la otra no tiene arreglo. Es el mismo
principio que ya estaba escrito para "no hay donde comer" —decir la causa
equivocada es peor que no decir nada— aplicado donde faltaba.

### El nombre es la única señal que queda, y no se usaba

Los 35 miradores activos del catálogo tienen **todos el mismo
`quality_score`: 0,40**. Ninguno trae horario, web ni teléfono, así que lo
completo del registro no distingue nada, y con el mismo atractivo (0,8) el
motor no puede diferenciar "Mirador de Apaneca" de **"Mirador 3"**. Se colaban:
seis apariciones en 295 paradas entre "Mirador 3" y "Peña 1".

La regla es estrecha a propósito: una palabra genérica y un número al final. Un
número solo aparece cuando alguien numera lo que no sabe nombrar — si hay un
"Mirador 3" es porque hay un 1 y un 2. Atrapa 2 de 5.658 lugares activos y
ningún falso positivo.

**La primera versión también miraba palabras de tamaño y se llevaba ocho "Cerro
Grande"**, que es un topónimo salvadoreño de verdad. Por eso se quedó fuera
"Peña pequeña", que tampoco identifica nada: la regla que la atrapara se
llevaría también los Cerro Grande.

Y hacen falta **dos** penalizaciones, en dos monedas distintas. `score_candidate`
solo elige la **semilla** del día; el resto lo llena `_fill_cost`, que mira
kilómetros y no puntaje. Con la penalización solo en el puntaje, "Mirador 3"
seguía entrando por cercanía exactamente las mismas cuatro veces: medido.

| km | paradas | llevá comida | cats/día | apariciones vagas |
|---|---|---|---|---|
| 0 | 295 | 21 | 3,26 | 6 |
| 5 | 299 | 21 | 3,28 | 3 |
| **10** | **298** | **21** | **3,28** | **2** |
| 20 | 293 | 22 | 3,28 | 2 |

**La penalización sale gratis y hasta paga**: en 10, el día arma tres paradas
*más* que sin ella y con más variedad, porque lo que sacrificaba un "Mirador 3"
cerca era un lugar de verdad un poco más lejos. Las dos apariciones que quedan
son "Peña 1" donde es lo único que hay — penalizar, no descartar: con 35
miradores en el país, tirar dos deja zonas sin ninguno.

Lo que la regla **no** arregla son los mal etiquetados: en ese mismo pozo de 35
miradores hay un taller de artesanía en madera, unos graderíos y dos fincas. Eso
no es un nombre pobre, es una categoría equivocada, y por el nombre no se ve.

### El borrador dice que todavía está midiendo

El itinerario llega en dos tiempos: el borrador se arma sin tocar la red y sale
de inmediato, y dos segundos después llegan las distancias reales y el mapa
cambia las rectas punteadas por el trazo por carretera.

**Esperar sería peor.** Si ORS falla o se acabó el cupo, el borrador *es* la
respuesta final: bloquear convertiría una respuesta rápida y utilizable en la
misma respuesta, más lenta. Y la recta punteada no es un error que se corrige
después: la leyenda ya dice "distancia estimada", así que el cambio es una
mejora de información, no una enmienda.

Lo que faltaba era decirlo. El indicador de progreso vivía en el compositor, y
el compositor se desmonta en cuanto llega el borrador: **desaparecía justo
cuando empieza a hacer falta**. Ahora la cabecera del panel dice "midiendo las
rutas por carretera" mientras eso pasa, y cede el sitio al dato de dónde
salieron las distancias cuando termina.

Medido sobre 11 itinerarios: en **9 solo cambian las líneas**; en 2 cambian
también las paradas, porque las distancias reales no son las estimadas y el día
se rehace. Más razón para no dejar creer que ya está firme.

### Repetir la subcategoría cuesta aparte, y un nombre no se repite

La penalización por categoría no distingue un día de cerro, volcán, cascada y
playa —cuatro cosas distintas— de un día de cinco monumentos, que son cinco
veces la misma parada de veinte minutos. Los dos son la misma categoría
repetida y pagaban lo mismo. Medido: el peor día del arnés llevaba **cinco
monumentos**, y había cuatro días con tres o más miradores seguidos.

La penalización de subcategoría se **suma** a la de categoría en vez de
sustituirla, y eso es deliberado: un segundo monumento es peor que un segundo
lugar de cultura cualquiera, así que paga las dos. El barrido:

| km | paradas | llevá comida | cats/día | racha 3+ | subrachas | peor |
|---|---|---|---|---|---|---|
| 0 | 297 | 21 | 3,26 | 22% | 6/61 | 5 |
| **8** | **295** | **21** | **3,26** | **17%** | **3/61** | **4** |
| 16 | 294 | 23 | 3,22 | 17% | 3/61 | 4 |
| 24 | 293 | 23 | 3,22 | 19% | 3/61 | 4 |

8 domina a todo lo demás: recoge la mejora entera sin tocar las comidas ni las
categorías por día, y por dos paradas de 297. De 16 en adelante la variedad de
subcategoría se empieza a comprar con comidas y con variedad de categoría, que
es justo lo que se venía a mejorar.

**Y un nombre no se repite en el itinerario.** El síntoma era un día con dos
"Cascadas de Huizucar", que se lee como un error de duplicado. Lo era, pero no
del cargador: son dos filas del catálogo a 774 metros y el radio de
deduplicación para exteriores son 500.

Aflojar ese radio habría sido un error, y medirlo lo dijo: de los pares con
nombre **idéntico** a menos de 3 km, los que más aparecen son **Pizza Hut (90
pares), Don Pollo (60), Starbucks (59), Subway (54)** y áreas protegidas
mapeadas varias veces. Dos Pizza Hut a 800 metros son dos restaurantes;
fusionarlos sería falso, y el número de pares *crece* con la distancia, que es
la firma de sitios distintos con nombre genérico.

Así que la regla va en el itinerario y no en el catálogo: **uno de cada
nombre**. No dice que sean el mismo lugar, dice que uno basta — que también es
cierto para las cadenas, porque dos Pizza Hut en el mismo viaje no son variedad.

Resultado de las dos cosas juntas, sobre los 61 días:

| | antes | ahora |
|---|---|---|
| días con racha de 3+ de la misma subcategoría | 7 | **3 (5%)** |
| máximo de monumentos en un día | 5 | **2** |
| máximo de miradores en un día | 4 | **3** |
| pares consecutivos de la misma subcategoría | 18% | **15%** |
| días con 3+ cerros | 1 (2%) | 1 (2%) |

Los cerros, que fueron la queja original —"cuatro cerros seguidos"—, ya estaban
resueltos por la penalización de categoría antes de esto: un día de 61 llega a
tres, y ninguno a cuatro.

### Cuánto dura una visita: seis números no alcanzaban

Las duraciones eran una tabla por categoría, seis números para todo el
catálogo. Y "cultura" son los 33 museos del país **y también** los 86
monumentos: el Museo Nacional de Antropología y una estatua en una rotonda
ocupaban los mismos 75 minutos. Subir la categoría entera para que el museo
durara dos horas se las daba también a la estatua.

La subcategoría ya se usaba para el atractivo, por el mismo motivo — un
redondel no puntúa igual que un volcán — y ahora también para la duración: un
museo son 120 minutos, un monumento 20, un volcán 180, un jardín 120. Lo que no
está en la tabla cae en la de categoría.

Visitas más largas mejoran la variedad y empeoran las comidas, las dos cosas
medidas: las rachas bajan del 31% al 24% de los días y los días de una sola
categoría de 3 a 1, porque el día visita menos sitios y no llega a raspar el
fondo del catálogo; y los "llevá comida" suben del 23% al 34%, porque visita
menos sitios **pero mejores**, y los mejores están más dispersos.

La duración se resuelve en cinco escalones, del más específico al más general:
la etiqueta de comida, los minutos pedidos para ESE lugar, los pedidos para su
categoría, la subcategoría, y la tabla. La etiqueta va primero y no la
categoría del lugar: si mandara la categoría, quien sale de una pupusería y
vuelve a ella cerraría el día con una segunda cena de hora y media.

### Nada fuera de hora: la luz y el cierre

Mientras los días terminaban a las cuatro de la tarde no había forma de llegar
a este problema. Con días que llegan a la noche aparecieron cinco de 130
paradas al aire libre empezando a oscuras — entre ellas un cerro a las 19:22 — y
dos de 121 bajo techo — una iglesia a las 19:56.

Son dos reglas con dos motivos distintos. Al aire libre manda la luz, y eso
puede ser una constante: en El Salvador el sol se pone entre las 17:50 y las
18:30 durante todo el año, porque está a trece grados de latitud. Bajo techo
manda el horario de apertura, que **no existe en el dato**: de los 366 lugares
bajo techo del catálogo, once traen `opening_hours` en OpenStreetMap, un 3%. Con
eso no se decide nada, así que se asume una hora de cierre para todos en vez de
fingir que el dato está. Los comedores no entran en ninguna de las dos: un
restaurante a las ocho de la noche es exactamente lo que uno busca a esa hora.

Mirarlo solo al llenar el día no bastaba — quedaban cuatro de cinco — porque
entre el llenado y el resultado el orden cambia dos veces: `_pinned_order`
optimiza el recorrido y la comida se intercala. Así que también se quitan
cuando el orden ya está decidido, y **por su nombre y no por su costo**: el
recorte de kilómetros elige la parada que más traslado suma, que casi nunca es
la que cae tarde.

### Lo que se pide con nombre se cumple o se explica

`include_meals` es un booleano y significa "meteme comidas donde quepan". No
sirve para "voy a cenar los dos días", y la diferencia no está en lo que el
motor hace sino en lo que dice: un día que no llega a la cena no tiene nada que
explicar con el primero, y con el segundo callarse es dejar a alguien esperando
una cena que nadie planificó. El caso real eran dos días pidiendo cena, con el
segundo a pie terminando a las 15:04 porque se le acababan los ocho kilómetros,
y ni una palabra al respecto.

Lo mismo un paso más allá: se puede pedir un lugar concreto — "quiero ir al
Jardín Botánico y pasar dos horas ahí" — y eso es más fuerte que pedir una
categoría, porque exigir cultura se cumple con cualquier museo y esto se cumple
con uno solo. Pesa el doble que una categoría pendiente al llenar el día, y si
no cabe en ninguno, `validate()` lo reporta: priorizar no es garantizar.

Si el nombre no está en el catálogo **se dice en vez de sustituirlo**, que es la
misma regla del punto de partida. Probado con el Museo del Añil de Suchitoto,
que OpenStreetMap no tiene: la pantalla responde "no supe cómo usar esto" en
lugar de llevar a otro museo parecido.

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
| Lugares inventados | 0 de 302 paradas generadas |
| Factor de desvío medido | 1.45, mediana sobre 812 pares |
| Velocidad efectiva en carro | 35 a 62 km/h según el tramo |
| Pares sin ruta en ORS | 7% (58 de 870) |
| Cupo del endpoint de matriz | 50 peticiones / ventana de 24 h |
| Peticiones por itinerario en zona fría | 1 |
| Lugares en el catálogo | 5.786 activos de 6.449 bajados |
| Descarte del filtro de calidad | 5.9% (370 registros) |
| Duplicados fusionados | 4.4% (274 registros) |
| Días con recomendación de llevar comida | 34% (21 de 62) |
| Repetición de categoría por paso | 26% |
| Repetición de subcategoría por paso | 15% |
| Paradas fuera de hora (luz o cierre) | 0 |
| Tramos con trazo por carretera | 94% (34 de 36, en los días más duros) |
| Cupo del endpoint de direcciones | 200 / día, medido en la cabecera |
| Tests | 578 backend, 28 frontend |

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

### El trazo va por carretera, y lo dice tramo por tramo

El mapa dibujaba líneas rectas entre paradas, y eso no era culpa de
OpenStreetMap: OSM tiene toda la geometría de las carreteras. Las rectas las
dibujaba el propio cliente, porque el endpoint `/v2/matrix` que usa el backend
devuelve **números, no geometría**. Medido en un tramo real de la Ruta de las
Flores, Ataco → Juayúa: 11,3 km en línea recta contra 18,4 km por carretera, un
factor de rodeo de 1,63. Las distancias no estaban mal —`DETOUR_FACTOR` está
calibrado en 1,45 y este par cayó dentro del rango— pero la línea sí.

**Una petición de direcciones por día, no por tramo.** ORS acepta varias
paradas y devuelve una sola geometría que las recorre en orden; después se
parte. Un itinerario de tres días pasa de una petición a cuatro, así que con 45
diarias la caché importa más acá que en la matriz: el trazo entre dos puntos
fijos tampoco cambia, y una zona ya recorrida no gasta nada.

El trazo vive en la misma fila que la distancia del tramo. No hace falta una
tabla aparte: tiene la misma clave —origen, destino y perfil—, sale de la misma
fuente y se invalida en los mismos casos. Es anulable, porque la distancia y la
geometría cuestan peticiones distintas y una arista puede tener la primera y no
la segunda.

**El troceo no depende de `way_points`.** ORS publica índices de waypoint que
servirían para partir la geometría, pero atarse a un campo más de un formato que
ya cambió una vez es fragilidad gratis: la parada se ancla al vértice más
cercano del trazo, que da lo mismo porque el enrutador engancha cada parada a la
red vial. Validado contra geometría real de tres paradas: los tramos que salen
miden lo mismo que las distancias por tramo que reporta el enrutador, con un
0,2% de diferencia, y comparten el vértice que los une.

El caso que rompe la versión ingenua del troceo es la ida y vuelta por la misma
calle, que en un día de montaña es lo normal: dos vértices casi idénticos, y
buscando el mínimo global la tercera parada se ancla a uno del principio. Los
anclajes se buscan hacia adelante y nunca retroceden. Hay un test.

**El guion dejó de ser una propiedad del itinerario.** Antes el trazo punteado
se decidía con el `travelSource` del plan completo, así que un solo par que ORS
no podía enrutar punteaba todo —incluidos los tramos que sí se habían medido—.
El mapa decía menos de lo que el backend sabía. Ahora cada tramo trae su trazo o
no lo trae, y se dibuja sólido siguiendo la carretera o recto y punteado. La
leyenda lista solo las clases que aparecen.

La geometría se guarda entera y se simplifica al servirla: la petición es lo
caro, así que la caché se queda con la mejor versión y la tolerancia puede
cambiar sin volver a pedir nada. Medido sobre ese tramo de 18 km, 451 vértices:

| tolerancia | vértices | KB | desvío | px a z14 | px a z16 |
|---|---|---|---|---|---|
| 0,00002 | 224 | 5,4 | 2 m | 0,2 | 1,0 |
| **0,00005** | **132** | **3,2** | **6 m** | **0,6** | **2,4** |
| 0,00010 | 88 | 2,1 | 11 m | 1,2 | 4,7 |
| 0,00050 | 39 | 0,9 | 54 m | 5,8 | 23,2 |

El trazo se dibuja con 3,5 px de grosor, así que por debajo de un par de píxeles
de desvío no hay nada que ver. En 0,00005 pesa un tercio y se separa de la
carretera menos de lo que mide su propia línea hasta zoom 16, que es donde el
mapa trabaja.

### La animación de la ruta nunca se había ejecutado

Al reescribir el dibujo salió a la luz: el CSS animaba
`.leaflet-overlay-pane path`, y no había ninguno. El mapa se crea con
`preferCanvas` —lo necesita el campo de 5.652 puntos del catálogo— y eso mandaba
también las polilíneas al canvas. Cero `<path>` en el panel de superposición, y
las dos animaciones de trazado del CSS no corrieron nunca. El `PLAN.md` cuenta
«la ruta se dibuja de parada en parada» entre las cuatro cosas que se pueden
animar y entre las que forman el momento memorable, y no estaba pasando.

El plan usa ahora un renderizador SVG propio. El campo no pierde nada: es una
capa de canvas aparte y no depende de `preferCanvas`.

La longitud del trazo se lee del propio nodo con `getTotalLength` en vez de
fijar un número. Con geometría real un tramo puede medir cinco veces más que
otro —medido en pantalla: 1.335, 1.220, 952 y 258 px en el mismo día— y un
`dasharray` constante dejaría los largos a medio dibujar y los cortos animados
de más. Los tramos punteados aparecen en vez de dibujarse: ahí el guion es el
dato, y animar el trazado tendría que sobrescribir el `dasharray`.

### Una frase puede estar cubierta a medias, y entonces se parte

"quiero comer bien" se iba entera a `unmapped`. Son dos cosas: que le importa
la comida, que sí se puede representar en `preferred_categories`, y que la
quiere buena, que no —el catálogo no tiene valoraciones de nadie—. Mandar la
frase completa a `unmapped` le dice a la persona que ignoraste hasta la parte
que sí aplicaste.

Ahora se parte: `food` a las categorías preferidas y "comer bien" a `unmapped`.

**No se mapeó a `min_quality`, que era la tentación.** `score_quality` dice de
sí mismo que «no mide si el lugar es bueno, mide si el registro sirve para
armar un itinerario»: son las horas publicadas, el sitio web, la dirección. Un
comedor con horarios no es un comedor rico. Usarlo para "comer bien" sería
exactamente la equivalencia forzada que el propio prompt prohíbe.

El efecto medido sobre el itinerario es casi nulo —el atractivo de la
subcategoría pesa el doble y domina el empujón de la preferencia— y eso también
es correcto: `include_meals` ya coloca un almuerzo, así que preferir comida no
tiene que agregar más. Lo que la persona quería era un restaurante *mejor*, y
eso es justo lo que queda visible en `unmapped`.

### El nombre se arregla al mostrarlo, no en el catálogo

OSM es texto libre. En el catálogo cargado hay 55 nombres enteros en mayúsculas,
17 que terminan en puntuación y algunos con espacios dobles. Puestos entre
paradas normales se leen como un grito o como un error: en una captura real
salió «COMIDA A LA VISTA Y PUPUSERIA.».

Se corrige al serializar y no en la tabla. El catálogo guarda lo que dice OSM,
que es la fuente; reescribirlo ahí perdería el original y una recarga
desharía el arreglo.

**Solo se rebaja lo que es seguro**, y las dos reglas salieron de fallar:

- Una palabra sola en mayúsculas puede ser sigla —`ISEADE-FEPADE`, `ANDEN`— y
  «Iseade-Fepade» es peor que dejarla. Se rebaja únicamente con dos palabras o
  más.
- Dentro del nombre, una palabra corta se conserva en mayúsculas solo si no
  tiene vocales: `SV` se queda y `DON` no. La primera versión usaba la longitud
  y dejaba «Cafe de DON Jose».
- El nexo manda sobre la sigla: la `Y` no tiene vocales y la prueba de sigla la
  daba por buena, así que salía «Cafe Y Pan».
- Los nexos van en minúscula en medio del nombre, los artículos no: en el nombre
  de un negocio el artículo es parte del nombre, «Restaurante El Amate».

Lo que **no** se hace es renombrar. «Mirador 3» sigue llamándose así, porque es
el nombre que OSM le da y cambiarlo sería inventar. Que un nombre poco
informativo pierda el sitio frente a otro mejor es una decisión de calidad y
necesita una señal medida, que todavía no hay.

### El nomenclátor: nombres de lugar, aparte de los puntos de interés

"vivo en Mejicanos" no resolvía nada. La causa era concreta y no un fallo de
interpretación: lo único llamado Mejicanos en el catálogo son **cuatro puestos
de comida**, y el motor —con razón— se niega a anclar un viaje en un café.
Mejicanos no es un punto de interés, es un lugar donde la gente vive. Y el
proyecto solo conocía veinte zonas escritas a mano en Python.

Un nombre de lugar y un punto de interés son cosas distintas, así que van en
tablas distintas. De OSM salen 3.122 con nombre:

| qué | cuántos | activos | radio medio | destinos medios |
|---|---|---|---|---|
| barrios | 1.982 | 1.679 | 3,0 km | 38 |
| aldeas | 455 | 338 | 5,0 km | 18 |
| municipios | 263 | 240 | 8,4 km | 32 |
| pueblos | 257 | 238 | 8,0 km | 36 |
| suburbios | 129 | 128 | 5,0 km | 111 |
| ciudades | 15 | 15 | 12,0 km | 95 |
| departamentos | 14 | 14 | 33,6 km | 440 |
| distritos | 7 | 7 | 3,6 km | 115 |

**El radio sale de la geometría del límite, no de una constante.** Un
departamento y un barrio no se recorren igual: medido sobre los límites reales,
la mediana da 37,8 km de radio para un departamento y 7,3 para un municipio. Se
usa la mitad de la diagonal del recuadro, que para decidir dónde buscar
candidatos alcanza —guardar el polígono con sus cientos de vértices sería pagar
mucho por una precisión que nadie usa—. Los lugares que OSM publica como un
punto suelto no traen recuadro y llevan un radio por tipo.

**463 nombres quedan marcados por no tener con qué llenar un día**, con menos de
cuatro destinos en su radio. Se guardan marcados y no se borran, igual que los
descartes del catálogo: borrarlos impediría medir el filtro. El eslabón débil
son las aldeas —26% demasiado pobres—; los barrios en cambio funcionan casi
todos, porque son urbanos y densos.

Las veinte zonas curadas siguen ganando primero. Tienen radios afinados y
alias que OSM no da: "ruta de las flores" resuelve a Ataco y eso no sale de
ningún dato. El nomenclátor cubre la cola larga.

Cuando un nombre existe en varios niveles —"San Salvador" es departamento,
municipio y ciudad— gana el más específico: quien lo nombra piensa en la ciudad
y no en los treinta y cinco kilómetros del departamento.

El umbral de parecido está medido y el margen es corto:

```
"Megicanos" -> "Mejicanos"     0.538   hay que aceptarlo
"volcan"    -> "Volcancillo"   0.462   hay que rechazarlo
"playa"     -> "Playa El Cuco" 0.429   hay que rechazarlo
```

0.50 cae en ese hueco. Son cuatro centésimas de margen contra "volcan", así que
si el nomenclátor crece conviene volver a medir esos tres casos.

### El cupo de OpenRouteService es por endpoint, no uno solo

Se descubrió corriendo, y corrigió un diseño. La matriz respondía
`Quota exceeded` mientras direcciones seguía contestando: son cupos separados.

Eso significa que un itinerario puede tener **distancias estimadas y trazo real
al mismo tiempo**. Con la geometría como columna de `travel_edges` ese caso no
se podía guardar —solo se guardan las aristas medidas, así que no había fila que
actualizar—: el trazo se descartaba y la petición siguiente lo volvía a pedir.
Se quemaba cupo de direcciones en cada consulta para tirar el resultado.

Por eso el trazo vive en `route_legs`, con la misma clave pero su propia fila.
Medido después del cambio: de cinco tramos guardados, **cuatro no tienen
distancia medida** —son exactamente los que antes se perdían— y la segunda
consulta no gasta nada.

**El hallazgo estaba escrito aquí y el cliente no lo implementaba.** `ORSClient`
llevaba un solo `DailyQuota` para los dos endpoints, y como la matriz corre
primero en la misma petición, se llevaba el presupuesto entero: cuando le tocaba
al trazo, el cliente creía que no quedaba nada. La segunda cara era peor —
`sync_with_server` guardaba el `x-ratelimit-remaining` de la última respuesta,
de cualquiera de los dos, en un campo común, así que un "quedan 4" de la matriz
apagaba direcciones con su cupo intacto.

El síntoma era un itinerario con **distancias reales y líneas rectas**, y una
tabla `route_legs` con cero filas después de meses. Con un contador por
endpoint, la primera petición de direcciones devolvió un tramo de 43 vértices y
lo guardó. Y los encabezados de esa respuesta dieron el número que faltaba:

```
X-Ratelimit-Limit: 200        (direcciones, no 50 como la matriz)
X-Ratelimit-Remaining: 176
```

O sea que el cupo del trazo es cuatro veces el de la matriz y estaba
prácticamente sin usar. El presupuesto local de 45 se aplica a los dos por
igual, así que ahora es él —y no ORS— el que limita las direcciones; con una
petición por día de itinerario, 45 alcanza de sobra, pero el número ya no
describe el límite real.

**Y con el cupo desbloqueado apareció el problema de verdad, que era otro.**
Pedir la geometría de un día entero en una petición tiene una consecuencia que
el código no había previsto: si ORS no puede enganchar **una** parada a la red
vial, falla la petición completa y el día se queda sin trazo. El error lo dice
con precisión:

```
HTTP 404 · code 2010
"Could not find routable point within a radius of 350.0 meters
 of specified coordinate 0: -89.2861135 13.7372142."
```

Esa coordenada es el Volcán de San Salvador. Los 350 metros son el valor por
defecto de ORS, y no hay calle a esa distancia de una cumbre. Medido: **34 de
61 días** del arnés llevan al menos una parada así, y arrastraban **127 de 236
tramos** a la línea recta —incluidos los que van entre museos del centro, que
ORS enruta sin pestañear—. El comentario de `load_route_geometry` prometía que
"el degradado es por tramo y no por itinerario"; la implementación degradaba
por día.

La solución es un parámetro que existe para esto y no se estaba mandando:
`radiuses`, cuánto puede alejarse cada parada para engancharse. Con 5 km, el
día del volcán enruta y el trazo arranca a 840 m de la cumbre — que no es un
error de precisión, es el dato correcto: ahí se acaba la carretera y empieza la
caminata.

| | tramos con trazo |
|---|---|
| Antes, sobre los días más duros | 0 de 36 |
| Con `radiuses` | **34 de 36 (94%)** |

Los dos que faltan son honestos: 1,17 km y 755 m entre tres paradas **dentro**
del Parque El Imposible, que se enganchan todas a la misma carretera de acceso
porque no hay ninguna entre ellas. Ahí se camina, y la recta es la respuesta.

El tope de 5 km no es generosidad, es un límite: un punto en medio de un lago
podría engancharse a una carretera de la otra orilla y dibujar un recorrido que
nadie va a hacer. Queda un residual sin observar todavía —una parada a más de 5
km de cualquier calle seguiría tumbando su día— y la salida sería reintentar sin
ese punto, que ORS identifica por índice.

### El día sale de donde el usuario dijo

"Quiero partir desde Pizza Hut La Gran Vía a las 12:00, almorzaré allí, luego
3 paradas que incluya algún museo o parque, y finalizar aprox 10 p.m." Eso es
lo que la gente pide de verdad, y el motor solo sabía armar días alrededor de
una zona.

**El papel importa más que el lugar.** Un Pizza Hut no sirve para *centrar* la
búsqueda —los negocios se llaman como el sitio donde están y ganan la búsqueda
difusa sin merecerlo, que es por lo que `CATEGORIAS_NO_ANCLABLES` existe— pero
es perfectamente válido como *punto de partida*: es donde la persona está. Son
dos papeles del mismo dato y se resuelven con umbrales distintos.

Cuatro decisiones que dan forma a esto:

**El ancla no gasta cupo de paradas.** Quien pide tres paradas habla de lugares
que va a visitar, no del sitio de donde sale. Y si ese sitio es un comedor, ya
es la comida del día: reservarle además un hueco de almuerzo dejaba el día con
un destino menos del pedido.

**El ancla no se recorta.** Cuando el día no entra en el presupuesto se quitan
las paradas que el motor eligió, no el dato que dio el usuario.

**El regreso es una parada visible.** Quien pregunta "y a qué hora llego a
casa" pregunta por esa línea, y un recorrido dibujado que no cierra parece un
recorrido a medias. Se agrega al programar y no al agrupar: mientras el ancla
está dos veces en la lista, todo lo que la recorre se confunde —`remove` saca
la primera aparición, el orden por cercanía la cuenta como dos paradas, y el
recorte puede quitar el regreso sin notarlo—. Los kilómetros de volver sí se
cuentan desde el principio, porque si no el día se llena al tope y la vuelta lo
saca del presupuesto cuando ya no hay nada que recortar.

**Volver cambia a qué días aplica.** Quien vuelve cada noche está diciendo que
ese sitio es su base, y el ancla vale para todos los días. Quien solo parte de
un lugar lo hace una vez, el primer día: arrancar tres días seguidos en la
misma pizzería sería absurdo.

**Y si el nombre no está, se dice.** El caso es real: "Hotel Barceló" no está
en el catálogo, y la búsqueda difusa devuelve "Hotel La Parcela", otro sitio a
veinte kilómetros. Por eso el punto de partida pide más parecido que el área
(0.60 contra 0.45) y falla en voz alta. Equivocar el área da un itinerario en
otra ciudad y se nota enseguida; equivocar el punto de partida da un día que
empieza donde el usuario no está, y eso se descubre estando ahí.

Cuando lo único que se dice es de dónde se sale, el punto de partida también
dice dónde buscar: doce kilómetros de radio, que es lo que se recorre saliendo
de un punto y volviendo.

### El hotel que estaba en OSM pero no en el catálogo

"Partir desde el Hotel Barceló" fallaba, y la primera hipótesis era el nombre
—se llama "Barceló San Salvador"—. No era eso: **no había nada con "Barcel" que
fuera un hotel**, ni activo ni descartado. Buscando en OSM directamente
apareció la causa real: el Hotel Barceló existe, etiquetado
`building=hotel` y **sin ninguna etiqueta `tourism`**. La consulta del cargador
pide `["tourism"]`, así que nunca se descargaba.

`building=hotel` describe el **edificio**, no el negocio, y eso lo vuelve una
etiqueta de poca precisión. Medido sobre El Salvador: 17 objetos con
`building=hotel`, nombre y sin `tourism`, de los cuales solo 8 son hoteles. Los
otros son partes del mismo complejo —"Torre 3", "Torre4", "Lobby Principal",
"Lobby 2", "Centro de Convenciones"— y algunos simplemente mal etiquetados:
"Discoteca Ixchel" y una "Emergencia Unidad Médica de Apopa".

**El filtro de nombres genéricos no los agarra, y no es un descuido.** No son
nombres genéricos: "Lobby 2" y "Discoteca Ixchel" identifican perfectamente un
lugar, solo que no un alojamiento. Se comprobó pasándolos por `evaluate()`: los
aceptaba todos.

Así que la etiqueta de edificio vale solo si el **nombre confirma** que es
alojamiento —hotel, hostal, posada, motel, suites, resort, cabañas—, y la regla
va al final para que una `tourism` explícita siempre gane: quien la puso sabía
más. Resultado: 7 aceptados, todos hoteles reales; 10 fuera, todos
correctamente.

**El canje se paga a sabiendas**: se pierde "Courtyard by Marriott", que es un
hotel de verdad y cuyo nombre no lleva ninguna de esas palabras. A cambio, no
entran una discoteca y una sala de emergencias a la lista de alojamientos. Hay
un test que fija ese caso, para que la pérdida sea una decisión y no un olvido.

El catálogo pasó de 5.652 a 5.658 lugares y el alojamiento de 509 a 515. Seis y
no siete porque la deduplicación absorbió a "Hotel Faro" como duplicado de uno
que ya estaba con su etiqueta canónica, que es exactamente lo que tiene que
hacer.

### Exigir no es preferir

"Quiero visitar mínimo un museo" iba entero a `unmapped`, y era la decisión
correcta con los campos que había: `preferred_categories` es un empujón de 0,6
en el puntaje, así que mapearlo ahí habría afirmado una garantía que no existe.
En un itinerario de prueba salieron museos los dos días —pero por suerte, no
por garantía.

Un requisito se cumple o se incumple, y eso lo vuelve exactamente la clase de
restricción que este proyecto sabe hacer cumplir. `must_include_categories` es
una lista de categorías que el itinerario tiene que incluir **al menos una
vez**, contada sobre el itinerario entero y no sobre cada día: quien pide un
museo en dos días quiere un museo, no dos.

El motor lo prioriza al armar y lo comprueba al terminar, y las dos cosas hacen
falta. Priorizar se hace en dos sitios —la semilla del día, que es la forma más
barata porque el resto se llena alrededor de ella, y el orden de llenado, con un
descuento en kilómetros para que el requisito compita en la misma unidad que la
cercanía y la variedad—. Comprobar existe porque priorizar no es garantizar: en
Perquín, que no tiene ni un mirador, exigir uno reporta la violación en vez de
dejar que el usuario lo descubra leyendo la lista.

Medido sobre San Salvador: sin exigir nada el día sale `nature, viewpoint,
food`; exigiendo cultura sale `culture, viewpoint, food`. La garantía funciona y
no cuesta paradas.

Exigir y evitar la misma categoría se rechaza al construir la petición: no se
puede cumplir de ninguna forma, y dejar que el motor elija cuál incumplir sería
peor que fallar. Y una categoría exigida se quita de las preferidas: exigirla ya
es lo más fuerte que se puede pedir, y reportar las dos cosas del mismo pedido
confunde.

### Llegar cuesta más que moverse

El modelo no tenía ningún tiempo muerto por parada, y se veía en pantalla:
0,7 km en coche daban «1 min», o sea salir del hotel y estar dentro del museo
sesenta segundos después. Falta estacionar, caminar del carro a la puerta y
entrar. En un día urbano de saltos cortos el horario iba optimista por parada.

No está calibrado contra datos, porque no hay datos que medir: es una estimación
de sentido común, igual que `DEFAULT_DURATIONS`. Ocho minutos en coche y dos a
pie —a pie no hay dónde estacionar, solo encontrar la entrada.

**Lo que sí está medido es su costo**, que es lo que decide el número. Barriendo
de 0 a 20 minutos sobre los 26 casos:

| coche | a pie | cumple | paradas | fin medio |
|---|---|---|---|---|
| 0 | 0 | 25/26 | 284 | 15:09 |
| **8** | **2** | **25/26** | **285** | **15:40** |
| 20 | 5 | 25/26 | 285 | 16:23 |

Es casi gratis, y la razón es interesante: **el límite que ataba era la
distancia, no el reloj.** Los días terminaban a las 15:09 con `latest_end` en
20:00, así que la fricción llena margen que ya estaba ahí. Las paradas ni bajan
—suben de 284 a 285.

Se suma al usar el dato y no al guardarlo. La caché de `travel_edges` guarda el
tiempo de conducción que midió OpenRouteService; meterle la fricción ahí dejaría
un número que no es ni una cosa ni la otra y que ya no se podría comparar con la
fuente. Hay tres tests que fijan esa separación.

### Un día en coche y otro a pie

"El primer día andaré coche, en el segundo viajaré a pie" iba entero a
`unmapped`, y era la respuesta correcta: `mode` era **un solo valor para todo
el itinerario**. Ahora va por día.

**Lo que no se puede no hacer es que el presupuesto siga al modo.** Veinticinco
kilómetros son un día normal en coche y cinco horas caminando: dejar el límite
del itinerario en un día a pie no sería una imprecisión, sería un día
imposible. Solo se sustituye cuando el día va en otro modo que el itinerario —
si todo el viaje es a pie, el número que puso el usuario ya es el de a pie y
manda sobre el valor por defecto.

**Una matriz de OpenRouteService por modo distinto, no una por itinerario.** A
pie y en carro no son la misma red: un sendero que el peatón cruza no existe
para el carro. Cuesta una petición más, y solo cuando el viaje mezcla modos —un
itinerario entero en coche sigue costando una.

La alternativa era estimar los días a pie, y se descartó por una razón medida:
`DETOUR_FACTOR` sale de 812 pares de ORS **en carro**, así que para caminar está
doblemente mal —el factor de rodeo es otro y la red también. Un día a pie medido
con la calibración del coche sería un número inventado con aspecto de dato.

Lo mismo vale para el trazo: la geometría se pide con el perfil del día y se
guarda en su propia fila, porque el camino a pie entre dos plazas no es el del
carro y dibujar uno por el otro sería mentir sobre el recorrido.

Y el icono del traslado sale del modo del día, no del itinerario: en un viaje
mixto, poner el coche en el día que se camina es decir algo falso. Por eso
`DayOut` lleva su propio `mode`.

**El error que casi se cuela.** `assemble` resolvía el medidor una vez y lo
pasaba hacia abajo. Cada función recibía entonces un proveedor concreto, y
`_travel_or_estimate` lo devolvía tal cual: el día a pie se medía con la red del
coche sin que nada lo delatara. Ahora se pasa `travel` —que puede ser un
diccionario de modo a proveedor— y cada día resuelve el suyo.

### En un teléfono el itinerario cabía en una rendija

Medido sobre una pantalla de 780 px de alto, antes de tocar nada:

| bloque | alto |
|---|---|
| mapa | 351 (45%) |
| cabecera | 164 |
| pestañas | 57 |
| **itinerario** | **104** |
| pie de revisión | 102 |

El cromo se llevaba el 75% del panel y al itinerario —que es el producto— le
quedaban 104 px, con paradas de 65. **Se veía una de seis.** Y las paradas
pesaban más de lo que parecía: `[65, 131, 152, 110, 110, 86]`, 654 px en total,
porque en 360 px de ancho los nombres largos y la frase «desde la parada
anterior» envolvían a dos y tres líneas.

Tres cambios, y el orden importa porque el segundo es el que más rinde:

**El panel se arrastra.** El mapa y la lista compiten por la misma pantalla y
uno mira una cosa a la vez, así que la respuesta no es repartir mejor sino
dejar elegir. Es el patrón de las aplicaciones de mapas y por eso no hay que
explicarlo. Se toca y también se arrastra, pero debajo es un botón de verdad
con `aria-expanded`: un panel que solo responde a un gesto no se puede usar con
teclado ni con lector de pantalla. El umbral del arrastre son 40 px, porque
menos que eso es un toque tembloroso y tratarlo como arrastre haría que tocar
fallara la mitad de las veces.

**Las paradas se compactan.** «desde la parada anterior» se va en pantalla
angosta: la posición en la lista ya dice de dónde viene el traslado, y esa
frase costaba una segunda línea por parada. Con eso y menos aire entre paradas,
las seis pasaron de 654 a 481 px.

**El cromo suelta lo que ya se leyó.** Expandido, la cabecera se queda con lo
que identifica al panel y esconde el resto —son noventa píxeles, dos paradas
más—; el pie de revisión empieza cerrado, porque se llevaba 102 px permanentes
por un campo que se usa de vez en cuando; y los controles del mapa desaparecen,
porque en una franja de noventa píxeles no se pueden tocar y solo se apilaban
encima del cromo de la aplicación.

El resultado, medido igual que el problema:

| | antes | colapsado | expandido |
|---|---|---|---|
| itinerario | 104 px | 167 px | **424 px** |
| paradas visibles | 1 de 6 | 2 de 6 | **6 de 6** |
| pie | 102 px | 44 px | 44 px |

En escritorio no cambia nada: el asa es `lg:hidden`, el pie nunca está cerrado
y la guarda de los controles del mapa vive en una media query, no en la clase,
para que redimensionar la ventana no deje el mapa sin controles.

---

## Frontend

### El tema no es un interruptor de luminosidad

La pantalla es un panel oscuro contra el mapa en sus colores reales, y ese
contraste es lo que separa el territorio del plan. Hacer un tema claro
invirtiendo el panel reintroduce el problema que esa decisión resolvió: panel
claro sobre mapa claro no se separa de nada, porque el color de fondo de las
teselas de OSM (`#f2efe9`) y la superficie del panel (`#f4f2ed`) son
prácticamente el mismo.

Así que en tema claro la separación no viene de la luminosidad sino de la
costura: `--borde-lienzo` es un divisor tenue en oscuro, donde el salto de
luminosidad ya hace el trabajo, y una línea a 3:1 en claro, donde es lo único
que separa. La elevación del compositor cambia en la misma dirección.

**El mapa no sigue al tema.** No hay tesela oscura que conserve la información
que el mapa natural ya da —bosque contra ciudad, río contra carretera—. Se
probaron las dos alternativas: el filtro de invertir y rotar el matiz devolvía
parques verde oliva y carreteras salmón, y las teselas de CARTO pasaron a
exigir llave. Lo que sí sigue al tema es el cromo que flota encima.

### Los tokens van por rol y no por material

Los colores salen del sujeto —roca volcánica, añil, arena negra— y esos nombres
son los buenos para hablar de la paleta. Pero `bg-basalto` repartido por 63
sitios no deja dónde enganchar un tema: hay que tocar los 63 igual.

El CSS va en tres capas. Los materiales son literales fijos; los roles dicen
qué material cumple qué función en cada tema; `@theme inline` publica los roles
como utilidades de Tailwind. El `inline` es lo que hace posible el tema: sin él
Tailwind congela el valor al compilar y redefinir la variable en tiempo de
ejecución no cambia nada.

Los materiales se declaran una sola vez. El mapa los lee del CSS con
`getComputedStyle` en vez de mantener una copia en TypeScript: Leaflet escribe
el color como atributo de presentación del SVG y ahí `var()` no resuelve, así
que necesita el literal —pero la copia paralela ya se había desincronizado, con
`tinta-suave` en dos valores distintos.

### El icono es el segundo canal, no un adorno

La categoría de una parada se codificaba solo con el color del punto. El color
por sí solo no es información accesible: quien no distingue el café del verde no
tiene de dónde sacar si la parada es un comedor o un cerro. Con icono el color
pasa a reforzar algo que ya se puede leer sin él.

Por lo mismo el mapa tiene leyenda. Venía codificando dos cosas sin decirlo en
ninguna parte: el color del pin era la categoría y el guion del trazo era «esta
distancia es estimada». Un código sin leyenda es decoración. La leyenda lista
solo las categorías que aparecen en el plan, y no se muestra en móvil, donde el
panel queda pegado debajo del mapa y cada parada ya trae su icono al lado del
nombre de su categoría.

### El territorio entra en foco cuando el plan aterriza

Antes de que haya plan el mapa está en foco suave y el compositor es lo nítido.
Cuando los pines caen, el desenfoque se retira. Responde a una acción y muestra
algo que acaba de cambiar, así que entra en lo que el `PLAN.md` permite animar —
y de paso es parte del momento memorable en vez de un efecto suelto.

**El desenfoque es graduado, no uniforme.** El estado vacío existe para mostrar
que hay material y dónde está: los 5.652 puntos del catálogo. Un desenfoque
plano los borra a todos y deja la misma pantalla genérica que el velo oscuro que
ya se había descartado. Con una máscara radial el foco se pierde detrás del
compositor, que es donde no hay nada que leer, y se conserva en la periferia,
que es donde están los puntos. El desenfoque incluso ayuda ahí: agrupa las motas
y se lee la densidad mejor que con el detalle.

Se atenúa con `opacity` y no bajando el radio. Un elemento con `backdrop-filter`
y `opacity < 1` compone el fondo desenfocado sobre el nítido, así que la opacidad
funciona como mando del desenfoque —y `opacity` se anima en todas partes,
mientras que `backdrop-filter` no—. El filtro se apaga del todo al terminar la
transición para no dejar una capa compuesta por gusto.

El velo va en `z-index` 750: encima de todos los paneles de Leaflet, que llegan
a 700, y debajo de sus controles, que van a 800 y 1000. El mapa se desenfoca y
los botones de zoom y la atribución siguen nítidos, que es un requisito y no una
preferencia: la atribución es la licencia de las teselas.

Los prefijos los pone Lightning CSS según los objetivos de Next. Escribirlos a
mano fue un error: colapsaba las dos declaraciones y emitía solo la versión
`-webkit-`.

### El mapa llena la pantalla, no cabe dentro de ella

El Salvador mide 2.5 grados de ancho por 1.35 de alto, casi el doble de ancho
que de alto. `fitBounds` garantiza que el rectángulo entre completo, así que en
una pantalla vertical de teléfono resolvía la diferencia mostrando latitud de
sobra: el país quedaba como una franja en medio y arriba se veía Belice. El
estado vacío existe para mostrar dónde está el material, y mostraba el país
equivocado.

`getBoundsZoom(bounds, true)` da el zoom al que el rectángulo cubre el
contenedor. El país llena la pantalla y lo que sobra se recorta por el lado
largo. En escritorio también mejora: antes se veían Ciudad de Guatemala y
Tegucigalpa con El Salvador como una banda al medio.

### Fotos: de la zona sí, de cada parada no

Se midió antes de decidir, sobre el catálogo cargado. El loader guarda las
etiquetas completas de OSM en JSONB justamente para esto, así que la cobertura
es una consulta y no una estimación.

| Categoría | Activos | Con etiqueta de imagen | % |
|---|---|---|---|
| culture | 286 | 18 | 6,3 |
| lodging | 509 | 17 | 3,3 |
| attraction | 80 | 2 | 2,5 |
| nature | 2.024 | 32 | 1,6 |
| food | 2.718 | 2 | 0,1 |
| viewpoint | 35 | 0 | 0 |
| **total** | **5.652** | **71** | **1,3** |

Filtrar por calidad no ayuda: en el decil más alto es 6,2% y del tercero hacia
abajo es cero. Una foto por parada dejaría el hueco vacío diecinueve de cada
veinte veces, y eso parece una aplicación rota, no un catálogo incompleto. Cada
almuerzo y cada cena salen de las 2.718 entradas de comida, donde hay dos fotos.

Las zonas sí son entidades con nombre propio: **18 de las 20 tienen foto libre**
en Wikimedia Commons. Van en la cabecera del panel, una por itinerario.

Se resolvieron una vez y quedan fijas en el código. No se consultan en tiempo de
ejecución a propósito: son veinte valores que no cambian, y una petición por
itinerario a un tercero solo agrega una forma nueva de fallar. Se usa `P18` de
Wikidata y no la imagen destacada del artículo, porque esa sale del infobox y a
veces es el mapa de situación del país —Juayúa caía justo en ese caso.

El autor y la licencia son obligatorios en el schema y hay un test que lo
comprueba. La atribución la exige la licencia de Commons, así que no es un
detalle de estilo: una foto sin crédito es un incumplimiento. Por eso el crédito
va visible sobre la imagen y no en un `title` que en un teléfono no existe.

En móvil la foto no aparece. Entre ella, el título a dos líneas y la explicación
de las distancias, la primera parada quedaba abajo del borde del panel: había
que desplazarse para ver el itinerario, que es el producto. Ahí el presupuesto
vertical es del itinerario, y el mapa está pegado arriba mostrando el territorio
de verdad.

### Satélite como capa opcional, y sin llave

Sirve para algo que el mapa dibujado no puede decir: si un mirador está de
verdad sobre una cresta, o si un «parque» es bosque o potrero. Como fondo por
defecto sería un retroceso —encima de una foto aérea el trazo añil se pierde y
los nombres de los pueblos desaparecen—, así que es un interruptor y el mapa
dibujado sigue siendo el de partida.

**Esri World Imagery, que responde sin llave.** No Mapbox ni Stadia, que la
piden. El problema de una llave en un mapa de cliente no es el cupo: es que las
teselas las pide el navegador, así que la llave viaja en el HTML y cualquiera
que lea el código puede gastar el cupo. Un cupo público es un cupo agotable por
un tercero. La llave de OpenRouteService no tiene ese problema porque la usa el
backend y nunca sale de ahí.

Y las teselas de Google Satellite no son una opción, ni gratis ni pagando: sus
términos prohíben usarlas fuera de sus propios SDK, así que no se pueden pintar
en Leaflet.

Cambiar el fondo quita una capa y pone otra en vez de reconstruir el mapa, así
que el encuadre, el plan y el campo del catálogo se quedan donde están. La
atribución viaja con la capa porque cada proveedor exige la suya.

**El color de los puntos del catálogo sigue al fondo, no al tema.** Son tinta
sobre el mapa dibujado, que es claro, y niebla sobre la foto de satélite, que es
oscura. Con un solo color el campo entero desaparecía la mitad de las veces: fue
lo primero que se vio al encender el satélite.

### Al elegir una parada: ir, no mirar

La pregunta natural es si al hacer clic se puede ver una foto del sitio. No: ya
está medido arriba —1,3% del catálogo, 0,1% de los comedores. Lo que sí se puede
ofrecer siempre es la acción de ir, porque no depende de que OSM tenga el dato,
solo de las coordenadas. Un enlace de indicaciones, no una integración:
enlazar a un mapa está permitido, incrustar sus teselas no.

Los cuatro datos derivados de las etiquetas sí aparecen lo suficiente para valer
la pena. Medido sobre el catálogo cargado, con al menos uno presente:

| Categoría | Activos | Con algún dato | % |
|---|---|---|---|
| food | 2.718 | 1.211 | 45 |
| lodging | 509 | 156 | 31 |
| nature | 2.024 | 482 | 24 |
| attraction | 80 | 2 | 2 |
| culture | 286 | 4 | 1 |
| viewpoint | 35 | 0 | 0 |
| **total** | **5.652** | **1.855** | **33** |

Un tercio, contra el 1,3% de las fotos: por eso esto se muestra y las fotos no.
En miradores no hay ninguno, así que la interfaz tiene que verse bien sin
ninguno —y por eso la acción de ir es lo único que no es condicional.

Se derivan en el backend en vez de mandar las etiquetas crudas: el cliente no
tiene por qué saber cómo OSM escribe `contact:phone`, y el resto de las
etiquetas no le sirve de nada. La cocina se traduce y solo si se conoce el
valor: una etiqueta que diga `steak_house` delata la fuente y no ayuda a elegir
dónde almorzar. Entre `regional;pupusa` gana lo concreto, porque «pupusas»
ayuda y «comida típica» no.

OSM es texto libre y eso se nota en los tres derivadores: la altitud llega como
`1965` y como `2381 m`, y alguna vez como algo que no es un número; los
teléfonos vienen separados por punto y coma y también por coma —`2121-2828,
2312-7228` es un caso real del catálogo—, pero en una dirección web la coma no
se parte porque es un carácter válido y rompería el enlace. Hay tests para cada
una de esas formas.

### El panel y el mapa se señalan entre sí

Elegir una parada en el panel lleva el mapa hasta ella; elegir un pin la abre en
el panel. La elección lleva de dónde salió, y no es un detalle: si vino del
panel el mapa vuela, y si vino de un pin ya está a la vista y volar sería
moverle el mapa a alguien que acaba de apuntar con el dedo.

El vuelo va a zoom 16 y no al máximo: a 18 se ve el techo del sitio y nada de su
alrededor, y lo que uno quiere saber al apretar una parada es dónde queda
respecto de las demás.

El anillo del pin elegido es niebla y no el acento, porque el pin vive sobre el
mapa y el mapa no sigue al tema: un anillo añil sobre bosque oscuro no se ve, y
sobre satélite menos.

### Contraste medido, no estimado

Los valores de la paleta se eligieron resolviendo el contraste requerido contra
el fondo más exigente de cada rol, no a ojo. Tres fallaban:

| Par | Antes | Ahora | Mínimo |
|---|---|---|---|
| Anillo de foco sobre el panel | 2.76:1 | 3.02:1 | 3:1 (SC 1.4.11) |
| Borde del campo de texto | 1.40:1 | 3.01:1 | 3:1 (SC 1.4.11) |
| Texto tenue sobre superficie elevada | 4.07:1 | 4.54:1 | 4.5:1 (SC 1.4.3) |

El anillo de foco era el que más pesaba: el piso de calidad del `PLAN.md` pide
foco de teclado visible, y estaba declarado sin cumplirse.

`prefers-reduced-motion` tenía el mismo problema. La regla de CSS anulaba las
animaciones declaradas en la hoja, pero no las de Motion, que escribe sus
valores en el estilo del elemento desde JavaScript. Lo resuelve
`<MotionConfig reducedMotion="user">`.

Y el estado vacío no cabía en un teléfono. El titular a 4.2rem fijos ocupaba
cinco líneas en 390px y la tarjeta salía más alta que la pantalla; el contenedor
recorta arriba y abajo, así que se perdían la primera línea del título y los
ejemplos. Los dos tamaños grandes son ahora fluidos con `clamp()`: el máximo es
el tamaño de diseño y el mínimo el que cabe.

---

## Stack

| Capa | Elección |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Base de datos | PostgreSQL + PostGIS, migraciones con Alembic |
| Lugares | OpenStreetMap vía Overpass, cargado una vez |
| Nombres de lugar | Nomenclátor de OSM: 3.122 departamentos, municipios, pueblos y barrios |
| Rutas | OpenRouteService: matriz para distancias, direcciones para el trazo |
| Modelo | Claude (Haiku para armar, Sonnet para conversar) |
| Frontend | Next.js (App Router) + React + Tailwind 4 |
| Mapa | Leaflet directo, sin react-leaflet |
| Animación | Motion |
| Iconos | Font Awesome, paquetes SVG con tree-shaking |
| Satélite | Esri World Imagery, sin llave |
| Fotos de zona | Wikimedia Commons, resueltas una vez |
| Tests | pytest en el backend (578), Vitest y Testing Library en el frontend (28) |
| CI | GitHub Actions: migraciones en ambos sentidos, y tipado, lint, tests y build del frontend |

Sin Celery: la carga del catálogo es un guion que corre una vez y la generación
de itinerarios es petición-respuesta. Sin embeddings: la selección de lugares se
resuelve con filtros espaciales y por categoría.

Sin kit de componentes, que impondría su propio aspecto. De Font Awesome se usan
los paquetes SVG de React y no el kit de CSS: el kit trae la hoja y la fuente
enteras, y así entran solo los iconos que se importan. Leaflet se maneja directo
porque `react-leaflet` no se llegó a usar en ninguna parte —el mapa es
imperativo— y quedó como dependencia muerta.

---

## Guiones

```bash
make test            # los 578 del backend
npm test             # los 28 del frontend, desde frontend/
make ors-check       # verifica la llave y lee el cupo restante
make ors-calibrate   # mide desvío y velocidad contra el catálogo
make ors-warm        # precalienta la cache por zona (no gasta sin --apply)
```

`ors-warm` sin `--apply` solo dice cuánto costaría. Con 50 peticiones diarias, un
guion que consuma cupo por equivocación sale caro.

---

## Lo que falta

**Las fuentes vienen de un tercero en el camino crítico.** Las familias
tipográficas se piden con `<link>` a Google Fonts, así que la primera pintura
depende de un dominio ajeno. `next/font` lo arreglaría autohospedándolas, pero
las descarga al compilar y eso ata el build a que `fonts.googleapis.com` esté
alcanzable. La salida es versionar los `.woff2` en el repo.

**El botón atrás del navegador no vuelve del itinerario.** La aplicación no
toca la URL, así que atrás saca del sitio. Que devuelva al estado vacío es
meter una entrada en el historial al enviar y escuchar `popstate`; arregla algo
que la gente ya trae aprendido del móvil. La petición escrita sí sobrevive a
"Empezar de nuevo", que era el caso más molesto.

**El volcado del catálogo es aditivo, no sincroniza.** `make dump` genera
`INSERT ... ON CONFLICT DO NOTHING`, así que `make restore` se puede correr
encima de producción y agrega lo que falta. Lo que no hace es actualizar lo que
ya está: un lugar que cambió de `is_active` o de calidad conserva en el destino
el valor viejo. Para igualar de verdad hay que vaciar las cuatro tablas antes.

**El itinerario no se puede compartir por enlace.** Se copia como texto y nada
más. Sin cuentas, la URL tendría que llevar el estado, y el estado son
identificadores del catálogo: se puede, pero hay que decidir qué pasa cuando un
lugar desaparece del catálogo entre que se comparte y se abre.

**El costo por itinerario en tokens no está medido.** Sí lo está el de rutas.

**La cobertura de horarios de apertura hace imposible el dato fino.** Once de
366 lugares bajo techo traen `opening_hours`. Mientras siga así, la hora de
cierre es una suposición uniforme y un museo que cierra a la una queda igual
que uno que cierra a las cinco.

**Los tests de frontend cubren cuatro componentes, no el mapa.** Leaflet toca
`window` al importarse y mide elementos que en jsdom no tienen tamaño; probarlo
ahí sería probar un doble. El mapa se verifica en un navegador de verdad, a
mano.
