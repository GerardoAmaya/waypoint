# Decisiones medidas

Este documento es el registro de ingeniería de [Waypoint](README.md): cada
decisión del motor y de la interfaz, con el fallo concreto que la provocó y el
número que la respalda.

**Está escrito así a propósito.** Un planificador de viajes es fácil de
demostrar y difícil de verificar: cualquier lista de lugares parece un
itinerario. Lo que separa uno bueno de uno plausible es si cumple lo que se le
pidió, y eso se mide. Casi todo lo que sigue nació de un itinerario concreto que
salió mal.

Cada una salió de un número, no de una intuición. Los guiones que las midieron
están en `backend/scripts/` y se pueden volver a correr.

Cuando una idea no sobrevivió a la medición, también está escrito — hay cuatro
piezas borradas por no ganarse su sitio, y el motivo de cada una.

## Índice

**[Cómo se arma un día](#como-se-arma-un-dia)**

- [El largo del día lo decide la hora que pediste, no un contador](#el-largo-del-dia-lo-decide-la-hora-que-pediste-no-un-contador)
- [Cuánto dura una visita: seis números no alcanzaban](#cuanto-dura-una-visita-seis-numeros-no-alcanzaban)
- [Reservar lo que no alcanza es perder dos veces](#reservar-lo-que-no-alcanza-es-perder-dos-veces)
- [La comida se ubica por costo, no por reloj](#la-comida-se-ubica-por-costo-no-por-reloj)
- [La espera antes de comer es rato en el lugar, no en el estacionamiento](#la-espera-antes-de-comer-es-rato-en-el-lugar-no-en-el-estacionamiento)
- [El techo de kilómetros que nadie pidió](#el-techo-de-kilometros-que-nadie-pidio)
- [Un día en coche y otro a pie](#un-dia-en-coche-y-otro-a-pie)
- [Llegar cuesta más que moverse](#llegar-cuesta-mas-que-moverse)
- [Restricciones duras que el motor hace cumplir](#restricciones-duras-que-el-motor-hace-cumplir)

**[Variedad y calidad de las paradas](#variedad-y-calidad-de-las-paradas)**

- [Repetir categoría cuesta kilómetros](#repetir-categoria-cuesta-kilometros)
- [Repetir la subcategoría cuesta aparte, y un nombre no se repite](#repetir-la-subcategoria-cuesta-aparte-y-un-nombre-no-se-repite)
- [Los centros comerciales: uno por viaje, y de ahí se sale](#los-centros-comerciales-uno-por-viaje-y-de-ahi-se-sale)
- [El nombre es la única señal que queda, y no se usaba](#el-nombre-es-la-unica-senal-que-queda-y-no-se-usaba)
- [Exigir no es preferir](#exigir-no-es-preferir)
- [Lo que se pide con nombre se cumple o se explica](#lo-que-se-pide-con-nombre-se-cumple-o-se-explica)

**[El tiempo: fecha, luz, cierre y clima](#el-tiempo-fecha-luz-cierre-y-clima)**

- [La luz se acaba cuando se acaba, no cuando llegás](#la-luz-se-acaba-cuando-se-acaba-no-cuando-llegas)
- [Nada fuera de hora: la luz y el cierre](#nada-fuera-de-hora-la-luz-y-el-cierre)
- [El anochecer era una constante, y la constante estaba mal](#el-anochecer-era-una-constante-y-la-constante-estaba-mal)
- [La lluvia es la misma regla que la luz, con otro insumo](#la-lluvia-es-la-misma-regla-que-la-luz-con-otro-insumo)
- [El horario de apertura: inviable para los destinos, viable para la comida](#el-horario-de-apertura-inviable-para-los-destinos-viable-para-la-comida)

**[De dónde sale el día, y cómo se nombran los lugares](#de-donde-sale-el-dia-y-como-se-nombran-los-lugares)**

- [Si dijiste dónde empezás, todos los días empiezan ahí](#si-dijiste-donde-empezas-todos-los-dias-empiezan-ahi)
- [El día sale de donde el usuario dijo](#el-dia-sale-de-donde-el-usuario-dijo)
- [El mismo parque dos veces en un día](#el-mismo-parque-dos-veces-en-un-dia)
- [El nombre con el que la gente llama a un lugar](#el-nombre-con-el-que-la-gente-llama-a-un-lugar)
- [Una ciudad nombrada como punto de partida es una zona](#una-ciudad-nombrada-como-punto-de-partida-es-una-zona)
- [El nomenclátor: nombres de lugar, aparte de los puntos de interés](#el-nomenclator-nombres-de-lugar-aparte-de-los-puntos-de-interes)
- [El hotel que estaba en OSM pero no en el catálogo](#el-hotel-que-estaba-en-osm-pero-no-en-el-catalogo)
- [El nombre se arregla al mostrarlo, no en el catálogo](#el-nombre-se-arregla-al-mostrarlo-no-en-el-catalogo)
- [La forma del catálogo condiciona el producto](#la-forma-del-catalogo-condiciona-el-producto)

**[Distancias, rutas y cupos](#distancias-rutas-y-cupos)**

- [Una matriz por itinerario, no una ruta por par](#una-matriz-por-itinerario-no-una-ruta-por-par)
- [Calibración de la estimación](#calibracion-de-la-estimacion)
- [El invariante geométrico: cuando la fuente miente](#el-invariante-geometrico-cuando-la-fuente-miente)
- [El trazo va por carretera, y lo dice tramo por tramo](#el-trazo-va-por-carretera-y-lo-dice-tramo-por-tramo)
- [El cupo real es el que dice la cabecera, no el que dice la tabla](#el-cupo-real-es-el-que-dice-la-cabecera-no-el-que-dice-la-tabla)
- [El cupo de OpenRouteService es por endpoint, no uno solo](#el-cupo-de-openrouteservice-es-por-endpoint-no-uno-solo)

**[Lo que se le dice al usuario](#lo-que-se-le-dice-al-usuario)**

- [Decir la causa equivocada, otra vez](#decir-la-causa-equivocada-otra-vez)
- [Límites duros y recomendaciones son cosas distintas](#limites-duros-y-recomendaciones-son-cosas-distintas)
- [El almuerzo se aconseja, no se impone](#el-almuerzo-se-aconseja-no-se-impone)
- [Una frase puede estar cubierta a medias, y entonces se parte](#una-frase-puede-estar-cubierta-a-medias-y-entonces-se-parte)
- [El borrador dice que todavía está midiendo](#el-borrador-dice-que-todavia-esta-midiendo)

**[Frontend y diseño](#frontend-y-diseno)**

- [El tema no es un interruptor de luminosidad](#el-tema-no-es-un-interruptor-de-luminosidad)
- [Los tokens van por rol y no por material](#los-tokens-van-por-rol-y-no-por-material)
- [El icono es el segundo canal, no un adorno](#el-icono-es-el-segundo-canal-no-un-adorno)
- [Contraste medido, no estimado](#contraste-medido-no-estimado)
- [El territorio entra en foco cuando el plan aterriza](#el-territorio-entra-en-foco-cuando-el-plan-aterriza)
- [El mapa llena la pantalla, no cabe dentro de ella](#el-mapa-llena-la-pantalla-no-cabe-dentro-de-ella)
- [Fotos: de la zona sí, de cada parada no](#fotos-de-la-zona-si-de-cada-parada-no)
- [Satélite como capa opcional, y sin llave](#satelite-como-capa-opcional-y-sin-llave)
- [Al elegir una parada: ir, no mirar](#al-elegir-una-parada-ir-no-mirar)
- [El panel y el mapa se señalan entre sí](#el-panel-y-el-mapa-se-senalan-entre-si)
- [La animación de la ruta nunca se había ejecutado](#la-animacion-de-la-ruta-nunca-se-habia-ejecutado)
- [En un teléfono el itinerario cabía en una rendija](#en-un-telefono-el-itinerario-cabia-en-una-rendija)

**[Cómo se mide el cumplimiento](#como-se-mide-el-cumplimiento)**

**[Limitaciones conocidas](#limitaciones-conocidas)**

**[Lo que falta, en detalle](#lo-que-falta-en-detalle)**

---

## Cómo se arma un día

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

### La espera antes de comer es rato en el lugar, no en el estacionamiento

Una comida no puede empezar antes de su franja, así que un día que terminaba
sus visitas a las 17:21 con la cena pedida a las 18:00 tenía **treinta y nueve
minutos muertos**. Y como la tolerancia para llegar temprano eran treinta, la
cena se rechazaba por nueve minutos y la persona leía *"llevá cena"* con el
restaurante ahí.

La primera salida fue ensanchar la tolerancia, y **la medición la descartó**:
de 30 a 45 minutos ganaba una cena sobre dieciséis días y a cambio duplicaba la
espera total, de 159 a 319 minutos. Con más holgura la inserción elige
posiciones más baratas en kilómetros y paga la diferencia en tiempo muerto, o
sea que empeoraba las cenas que ya salían bien para rescatar una. Quedó como
**rescate**: se prueba con la tolerancia normal y solo se reintenta con 45
cuando no salió nada y la comida se pidió por su nombre. Quince cenas, un aviso
menos, y 211 minutos de espera en vez de 319.

**Pero la espera en sí no tenía por qué existir.** La idea la puso el usuario:
si faltan treinta y nueve minutos para la cena, se pueden pasar en el mirador en
vez de en el estacionamiento. Los mismos minutos, y uno es tiempo de viaje.

Se reparte hacia atrás, de la parada pegada a la comida hacia las primeras, y
cada una toma lo que puede sin pasarse de su propio límite: la luz si es al aire
libre, la hora de cierre si es bajo techo. Ir hacia atrás importa, porque
estirar una parada empuja a todas las siguientes: hacerlo en la más cercana a la
comida mueve lo menos posible.

Medido sobre dieciséis días de ocho zonas: **346 minutos muertos en once casos,
y quedan cero**. Repartir hacia atrás alcanza más de lo que parecía —estirando
solo la parada anterior se absorbía el 62%— porque las paradas tempranas están
más lejos del anochecer.

### El techo de kilómetros que nadie pidió

El reporte que lo destapó: *"me estoy hospedando en Hotel Barceló, quiero un
itinerario de 2 días a partir de las 10 am, el primer día en coche y el segundo
caminando, realizaré cena en los 2 viajes y quiero estar de vuelta en el hotel
antes de las 11 p.m"*. El día 1 cerraba a las 14:38, sin la cena pedida, con seis
horas sin usar. Y el aviso decía **"subí el límite de traslado"** — un límite que
quien preguntaba nunca había puesto.

El traductor entendió todo bien: 10:00, 23:00, coche y a pie, cena, vuelta al
hotel. Lo único que nadie dijo era `max_travel_km_per_day`, y ahí el traductor
rellenaba 25. Es el mismo error que ya se había corregido en
`max_stops_per_day`, cuyo propio comentario lo enuncia: *"None es 'no lo dijo',
no 'cinco': sin número pedido, el largo del día lo deciden el horario y los
kilómetros, que son límites que sí vienen de la persona"*. Los kilómetros, en
este caso, no venían de la persona.

**El techo no es permiso para conducir más: es aire para las reservas.** Lo que
lo vuelve contraintuitivo es que el día del reporte usaba 23,0 km de 25 y aun
así rechazaba candidatos. Instrumentando los dos filtros del llenado salieron
42 rechazos, **todos por kilómetros y ninguno por reloj**: al llenar un día hay
que reservar de antemano el desvío al comedor y el cierre del recorrido, y con
25 esa reserva se comía el presupuesto entero. Los kilómetros que faltaban
estaban reservados, no recorridos.

Barrido sobre los 62 días del banco, moviendo solo los casos que estaban en el
valor por defecto:

| techo | paradas | mediana sin usar | días que acaban 3h+ antes | **km reales/día** |
|---|---|---|---|---|
| 25 km | 302 | 160 min | 28 de 62 | 14,8 |
| 40 km | 313 | 121 min | 23 de 62 | 20,0 |
| **60 km** | **321** | **88 min** | **22 de 62** | **24,3** |
| 80 km | 324 | 77 min | 21 de 62 | 24,6 |
| 120 km | 326 | 57 min | 21 de 62 | 27,4 |

Sesenta es la rodilla, y la columna que lo justifica es la última: con el techo
en 60 los días siguen recorriendo 24 km de media, o sea que no se vuelven
rallies — el reloj los sigue limitando. De 60 a 120 se ganan cinco paradas y se
pagan tres kilómetros.

**A pie hubo que medirlo aparte, y estaba igual de estrangulado.** El banco solo
tiene dos días caminando y los dos llevan su número escrito, así que no lo
detectaba. El síntoma apareció en un aviso: *"Celeste Imperio agrega 0,6 km y
dejaría el día en 8,4 km, y eso es mucho para un día a pie"* — rechazando un
comedor por un desvío de **seiscientos metros**. Sobre 16 días a pie de ocho
zonas:

| techo | paradas | comidas puestas | mediana sin usar | km reales/día |
|---|---|---|---|---|
| 8 km | 48 | **5** | **302 min** | 4,4 |
| 12 km | 58 | 11 | 231 min | 7,4 |
| 15 km | 62 | 13 | 213 min | 9,5 |
| **20 km** | **69** | **16** | **90 min** | **13,0** |
| 30 km | 68 | 19 | 90 min | 12,7 |

Con ocho, un día a pie desperdiciaba cinco horas de reloj y en dieciséis días se
colocaban cinco comidas. Con veinte, el día resultante camina 13 km de verdad:
unas tres horas repartidas en toda la jornada, no una maratón.

`BUDGET_BY_MODE` se queda en ocho a propósito, y son cosas distintas: ese se usa
cuando la persona **sí** dio un número pero para otro modo, así que ahí hay que
convertir una intención suya; esto es no tener ninguna señal. Probablemente ocho
también sea corto allá, pero no está medido y no se toca sin medirlo.

El efecto de lado fue el mejor: los días con "llevá comida" cayeron del 24% al
15%, porque un día con aire alcanza un restaurante.

**Dos cosas más que el fallo dejó al descubierto.**

El aviso no puede llamar "tu límite" a un número que la persona no puso, ni
aconsejarle subirlo. Y la primera reescritura tampoco servía: decía *"pedime un
día de hasta 27 km"*, y medidos sobre seis zonas, **los siete días que llegaban
a ese aviso eran a pie** — o sea que le proponía a alguien caminando cinco o
seis horas de caminata. Ahora la salida que se ofrece depende de qué la
destraba:

| situación | qué se ofrece |
|---|---|
| puso un límite | *"sobre tu límite de 25, subí el límite de traslado a 32 km"* |
| a pie, sin límite puesto | *"probá ese día en coche, que llega bastante más lejos"* |
| en coche, sin límite puesto | *"decime que no te importa moverte más y te lo acomodo"* |

El número deja de ser una tarea y pasa a ser una referencia entre paréntesis:
nadie tiene que calcular kilómetros para pedir lo que quiere.

**Y el otro aviso de comida, el del día que no llega a la franja, habla de horas
y no de kilómetros.** Es el único de los dos donde alargar el día sirve: ahí el
freno es el reloj, mientras que en el del presupuesto más horas no agregarían ni
un metro. Dice *"decime hasta qué hora podés y lo acomodo"*. Ofrecer flexibilidad
horaria contra un problema de kilómetros habría sido la misma falta que el
proyecto ya corrigió dos veces: dar la causa equivocada.

Y el banco dejó de comprobar el presupuesto cuando nadie lo pidió. Medir al
motor contra su propia constante no dice si cumplió lo que le pidieron: dice
que sabe sumar. Los casos que de verdad prueban el presupuesto llevan su número
escrito.

**Lo que este caso enseñó de paso, y no se arregló**: un día no puede llegar a
las 23:00 con destinos, pase lo que pase. `INDOOR_CLOSES` cierra lo de bajo
techo a las 18:00 y `DUSK` lo de afuera a las 18:15, así que lo único que
estira un día más allá de las siete de la tarde es la cena, que está exenta con
razón. Los dos días del reporte terminan ahora a las 20:05 y las 19:34, con
cena, y eso es lo más lejos que el catálogo permite llegar.

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

### Restricciones duras que el motor hace cumplir

Las categorías que el usuario pide evitar se descartan en el motor, no se
penalizan en el ranking. Restarles puntos solo las manda al final de la lista, y
basta con que sobre un cupo para que entren igual. Depender de que la capa de
consulta las haya filtrado antes deja el límite a merced de quién llame.

---

## Variedad y calidad de las paradas

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

## El tiempo: fecha, luz, cierre y clima

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

### Nada fuera de hora: la luz y el cierre

Mientras los días terminaban a las cuatro de la tarde no había forma de llegar
a este problema. Con días que llegan a la noche aparecieron cinco de 130
paradas al aire libre empezando a oscuras — entre ellas un cerro a las 19:22 — y
dos de 121 bajo techo — una iglesia a las 19:56.

Son dos reglas con dos motivos distintos. Al aire libre manda la luz; bajo
techo manda el horario de apertura, que **no existe en el dato**: de los 366 lugares
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

### El anochecer era una constante, y la constante estaba mal

La regla de la luz usaba `DUSK = 18:15` fijas, con este argumento escrito: *"en
El Salvador el sol se pone entre las 17:50 y las 18:30 durante todo el año,
porque está a trece grados de latitud"*. Suena razonable y es falso. Medido
contra el archivo histórico de 2025 para San Salvador:

| mes | puesta real | la constante |
|---|---|---|
| junio–julio | 18:21–18:28 | **13 min corta** |
| septiembre | 17:46–18:07 | ~14 min larga |
| octubre | 17:29–17:46 | 29–46 min larga |
| **noviembre** | **17:25–17:29** | **50 min larga** |
| diciembre | 17:27–17:40 | 35–48 min larga |

El rango anual es de **17:25 a 18:28** — una hora — y la constante se equivocaba
en los dos sentidos: en noviembre mandaba gente al cerro casi una hora después
de que oscureció, y en junio le cortaba el día teniendo luz.

**Se calcula, no se consulta.** La primera idea fue pedírsela a Open-Meteo, que
la devuelve junto al clima. Calcularla sale mejor por tres razones: no depende
de que el clima esté encendido ni de que el servicio conteste, funciona más allá
de los dieciséis días que llega el pronóstico, y **llega a tiempo** — el borrador
del itinerario se arma antes de pedir el clima justamente para aparecer de
inmediato, así que una puesta de sol que viniera por red no estaría disponible
cuando se decide dónde cabe cada parada. La puesta de sol es astronomía: sale de
la latitud y la fecha.

**Validado contra una implementación independiente.** Sobre 365 días y cuatro
puntos del país, la diferencia con Open-Meteo es de 2 minutos de media y 4 como
máximo, siempre en el mismo sentido. Se documenta y **no se corrige**: ninguno de
los dos es la verdad —los dos son cálculos— y calibrar uno contra otro sería
fingir una exactitud que no hay. Cuatro minutos son ruido al lado de los
cincuenta que erraba la constante.

Lo que cambia, medido sobre seis zonas y cuatro fechas de invierno:

| | paradas al aire libre que terminan después del anochecer real |
|---|---|
| con `DUSK = 18:15` | **23** |
| con la puesta de sol | **4** |

Y las cuatro que quedan se pasan por dos a cuatro minutos, que es exactamente la
precisión del método.

Sin fecha se sigue usando la constante, que es para lo que estaba: el motor no le
pregunta la hora a nadie.

### La lluvia es la misma regla que la luz, con otro insumo

El motor ya sabía que un cerro a las 19:22 no se ve y que una iglesia a las
19:56 está cerrada. "Este mirador es al aire libre y va a estar lloviendo" no es
una idea nueva: es `_outdoor_after_dusk` con otro dato de entrada. En El
Salvador tampoco es un lujo — de mayo a octubre llueve casi todas las tardes.

El clima sale de **Open-Meteo**, que es lo contrario de OpenRouteService en
justo lo que más cuesta de OpenRouteService: no pide llave, no hay nada que
configurar en producción, y el techo de uso no comercial es de 10.000 peticiones
diarias contra las 500 de la matriz. Licencia CC-BY 4.0, así que hay que atribuir.

El crédito va pegado a la línea que ya dice de dónde salieron las distancias —
*"Distancias estimadas en línea recta · clima de Open-Meteo"* — y no en un
renglón propio: la licencia obliga a atribuir, no a gastar una línea, y
gastándola metía una tercera franja gris bajo el título. El nombre enlaza al
aviso de licencia, que es lo que la atribución tiene que dejar alcanzable, y el
crédito completo con la licencia escrita va en el texto que se copia, donde no
le quita sitio a nada.

**Primero hubo que saber cuándo es el viaje.** El itinerario no tenía fecha: un
plan de tres días eran "tres días", no "del 22 al 24". La fecha la resuelve el
modelo, porque es quien lee "el sábado", y para eso se le manda el día de hoy en
el prompt — un modelo no sabe en qué día vive, y sin decírselo resuelve los días
de la semana contra un año cualquiera y devuelve algo plausible y equivocado.
Pero **no se le cree**: se valida contra hoy, porque las dos formas en que se
equivoca son medibles — una fecha que ya pasó y una que cae a años de distancia —
y las dos acaban planificando para hoy con un aviso. Y la fecha entendida se
escribe en la cabecera del día, que es la única manera de que alguien note que
se resolvió mal.

**El umbral que puse primero estaba mal, y la medición lo dijo.** La idea
original era exigir dos condiciones: probabilidad de lluvia ≥60% y ≥1 mm en la
hora. Parecía prudente. Sobre 640 horas de pronóstico de cuatro zonas del país:

| | horas |
|---|---|
| con ≥1 mm de lluvia | 61 |
| de esas, con probabilidad declarada <60% | **28** |
| con probabilidad ≥60% pero <1 mm (trazas de 0.0 a 0.9) | 79 |
| con ≥1 mm, poca probabilidad y cielo sin lluvia — el falso positivo que justificaba el umbral | **0** |

O sea que el umbral de probabilidad tiraba el 46% de la lluvia real y atajaba un
caso que no ocurre; el de milímetros filtraba 79 horas de gotas. El caso concreto
que lo destapó: Santa Ana, 21 de septiembre a las 13:00, código WMO 95 —
tormenta — con 1.8 mm y un 33% declarado, que la regla de dos condiciones
llamaba "sin lluvia". La razón de fondo es que cuanto más lejos está el día, más
reparte el conjunto de modelos la probabilidad, así que exigirla alta apagaba la
función **justo en los días que alguien planifica con tiempo**. Quedó un solo
umbral, el milímetro. La probabilidad se sigue guardando y mostrando: informa,
pero no decide.

**Avisa de lo accionable y calla el resto.** Que llueva mientras se está en un
museo no es un problema que la persona tenga que resolver, y que llueva a las
21:00 de un día que terminó a las 18:00 tampoco. Eso va en la ficha del clima
del día, que es un dato. El consejo está reservado a la lluvia que le cae encima
a una parada al aire libre, con los nombres y la franja: *"Se espera lluvia de
13:00 a 15:59, y Cerro Guazapa y El Talpetatón están al aire libre a esa hora"*.
Las franjas se agrupan por horas seguidas para no decir "de 14:00 a 20:00"
cuando lo que hay son dos chubascos con una tarde seca en medio.

**El pronóstico llega a dieciséis días y no se disimula.** Quien planifica para
diciembre recibe "todavía no hay pronóstico para esas fechas", no una predicción
inventada. Un viaje que empieza dentro del horizonte y termina fuera se pide
hasta donde llega: cinco días con clima y dos sin él es mejor respuesta que
ninguno con clima. Y como las distancias, el campo dice siempre de dónde salió
el dato y, cuando falta, por qué: callarse deja sin saber si no va a llover o si
nadie miró.

Dos detalles que se documentan en vez de disimularse. Open-Meteo etiqueta
`precipitation` como la suma de la hora **anterior** a la marca, así que la
franja puede estar corrida hasta sesenta minutos; sobre visitas que duran entre
una y tres horas eso no cambia ninguna decisión, y fingir precisión de cuarto de
hora sería peor. Y el pronóstico se pide **después** del borrador, no antes: el
borrador existe para llegar de inmediato, y ponerle delante una llamada HTTP de
hasta cuatro segundos sería gastar lo único que esa fase tiene de bueno.

De paso apareció un fallo que no tenía que ver con el clima: `revise_day`
recalculaba `violations` y dejaba `advice` en la lista vacía con que nace
`Itinerary`. Revisar un día borraba **todos** los consejos del itinerario,
incluidos los de días que nadie pidió tocar, y desde el cliente eso no se ve
como un campo que falta — se ve como si el problema se hubiera resuelto solo.

### El horario de apertura: inviable para los destinos, viable para la comida

El README decía que `opening_hours` no da para nada, y era verdad a medias.
Nadie había mirado la comida por separado:

| categoría | activos | con horario | |
|---|---|---|---|
| **food** | 2.717 | **419** | **15,4%** |
| nature | 2.024 | 55 | 2,7% |
| lodging | 515 | 25 | 4,9% |
| culture | 286 | 9 | 3,1% |
| attraction | 209 | 8 | 3,8% |
| viewpoint | 35 | 0 | 0% |

Para los destinos sigue siendo inviable y `INDOOR_CLOSES` sigue siendo una
constante. Para los comedores no: **el motor te podía sentar en uno cerrado**,
porque elegía solo por distancia. Y el prerrequisito era la fecha, porque
`opening_hours` habla de días de la semana.

**El lector va contra los datos, no contra la especificación.** La gramática de
`opening_hours` es enorme y casi nada de ella aparece en El Salvador. Lo que sí
aparece son varias reglas por `;`, listas de días, dos turnos separados por
coma, `off`, cruces de medianoche, días sin horas, horas sin días y un guion
Unicode U+2011. Lee **381 de los 419 valores reales (90,9%)**; los 38 que no son
prosa libre de verdad —`sunrise-sunset`, `Lun-dom 8 a. m.-8:30 p. m.`, `Todos
los dias 10am a 8:30pm`— y quedan como no entendidos, sin adivinar.

**Tres estados y no dos, que es la decisión que da forma a todo.** El 86% de la
comida no dice nada. Con dos estados hay que elegir entre dos errores grandes:
dar por cerrado lo desconocido vacía los itinerarios por un hueco de
OpenStreetMap, y darlo por abierto es lo que el motor hacía. Así que ABIERTO,
CERRADO y DESCONOCIDO, y la diferencia se usa: **nunca se coloca uno que se sabe
cerrado, y se prefiere el que se sabe abierto sobre el que no se sabe.**

Se exige la visita completa y no solo la llegada. Un comedor que cierra a las
14:00 no sirve para sentarse a las 13:42 si el almuerzo dura noventa minutos:
entrar y que te levanten no es comer.

**Lo medido.** El banco de 26 casos no puede medir esto, porque sus casos no
llevan fecha. Así que se armaron 42 itinerarios con fecha —seis zonas por los
siete días de la semana, 70 comidas colocadas— con `scripts/medir_horarios.py`:

| | comidas | se sabe abierto | se sabe cerrado | km |
|---|---|---|---|---|
| antes | 70 | 35 (50%) | **2** | 1.222,4 |
| solo la regla dura | 70 | 35 | **0** | 1.222,4 |
| con la preferencia | 70 | **62 (89%)** | 0 | 1.230,8 |

La regla dura quita dos respuestas lisa y llanamente incorrectas sin perder
ninguna comida: sustituye. La preferencia sube la certeza del 50% al 89% por 8,4
km repartidos en 42 días —doscientos metros por día—. `OPEN_HOURS_BONUS_KM` es
1,5 porque es el valor más chico que consigue todo el efecto: de ahí para arriba
el barrido no cambia nada, y las ocho comidas que quedan son franjas donde no
hay ningún sitio con horario conocido.

**Tres cosas que la medición corrigió, y las tres importan más que la función.**

El bono va en el puntaje y nunca en el costo. `costo` son kilómetros de verdad
—el aviso los escribe, "agrega 20,3 km"— así que mezclarle una preferencia lo
volvería un número falso. Mezclado, además, perdía catorce de las setenta
comidas en cuanto el bono pasaba de tres kilómetros; separado no pierde ninguna
ni con el bono en cuatro. La primera prueba que escribí para esto no detectaba
la contaminación, porque comparaba contra un umbral y restar 1,5 km a un desvío
de cuarenta seguía pasando; ahora compara el mismo comedor con horario y sin él,
que es el invariante.

Una regla ilegible se salta, no vuelve desconocido el horario entero. Se
consideró lo contrario, porque saltarla puede dar un cierre falso. Pero los dos
fallos no pesan igual: un cierre falso descarta un comedor que abría y pierde
una opción; una apertura falsa sienta a alguien en uno cerrado, y **eso se
descubre frente a la puerta**. Es la misma regla que el resto del proyecto, se
dice y no se sustituye. El caso que puso la política a prueba resultó ser un
hueco del lector —días separados por espacio, `Fr Sa 09:00-21:00`, un solo caso
en el catálogo— y se arregló ahí, que era donde correspondía.

Y se escribió un aviso para "están todos cerrados" que se quitó por no ocurrir
nunca. La idea era buena: "no cae en la franja" y "ese día no abre" son causas
distintas con salidas distintas, y las dos usan la palabra *horario*. Pero
medido sobre 126 combinaciones de zona y día, más 20 comedores aislados por
siete días y dos radios, disparó cero veces. El motivo es estructural: con 2.717
lugares de comida, si el mejor está cerrado el motor elige otro, y para que ese
aviso hablara tendrían que estar bloqueados por horario **todos** los candidatos
de la franja teniendo el 86% sin horario. Es la tercera pieza que este proyecto
borra por no ganarse su sitio.

## De dónde sale el día, y cómo se nombran los lugares

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

### El mismo parque dos veces en un día

El reporte: *"Tres días por la Ruta de las Flores"* devolvía un primer día así.

```
10:00  Parque Nacional El Imposible
12:57  Piccolo Giardino              ← 17,7 km   almuerzo
14:53  Parque El Imposible           ← 16,4 km
```

Se iba 18 km a comer y volvía 16 al **mismo parque**: 34 de los 47 km del día
en un rebote. Son dos filas de OpenStreetMap del mismo sitio —la reserva y su
entrada— a **1.173 metros**, con nombres y categorías distintas.

**Tres hipótesis descartadas, cada una por medición.**

*Subir el radio de deduplicación* (500 m → 1,2 km). Medido sobre el catálogo,
la banda de 500 a 1.200 metros está llena de cadenas con nombre idéntico:
Subway, Don Pollo, Pool House Hostel. Dos Subway a 924 metros son dos
restaurantes de verdad, y subir el radio los borraría.

*Parecido de nombre por trigramas.* No separa. El caso bueno saca **0,69** y
los falsos positivos sacan más: `Bahía Dorada` contra `Bahía Del Sol` da 0,77 y
`Estructura 6` contra `Estructura 2` da 0,73. Un umbral lo bastante estricto
para excluirlos excluye también el caso que se quiere atrapar.

*Contención de palabras a secas.* Mejor, pero `Hostel` está contenido en `Casa
Frolaz Hostel` y `La Pizzeria` en `Pizzeria Da Mario`. Cuando el nombre corto
es genérico, la contención no significa nada.

**Lo que sí funciona son las dos juntas: contención más una palabra rara.** Lo
que delata al parque no es que un nombre contenga al otro, sino que comparten
una palabra que casi no existe en el catálogo:

| palabra | lugares donde aparece |
|---|---|
| `imposible` | **2** |
| `caulotal` | **2** |
| `hostel` | 19 |
| `comercial` | 52 |
| `cerro` | 766 |

El umbral es una **fracción del catálogo** (0,1%, con un mínimo de 3) y no un
número fijo, para que escale si el catálogo crece. Con 5.786 lugares da 6, y
ahí la separación es limpia.

Resultado: **51 grupos, 108 filas**. Leyéndolos son casi todos ciertos —`Volcán
de Izalco` / `Ruta Volcan Izalco`, `El Cafetalón` / `Parque El Cafetalon` a 0
metros, `Mercado Municipal de Mejicanos` / `…No.2`— y los dudosos son baratos:
si la regla se equivoca, se pierde un candidato entre miles, no se da una
respuesta incorrecta.

**Se resuelve al cargar el catálogo, no al armar el itinerario.** Que dos filas
sean el mismo parque no depende del viaje: es un hecho del catálogo, y
calcularlo en cada petición sería recalcular en caliente algo que no cambia. La
columna `same_place_as` apunta al representante del grupo, y el motor solo lee
la respuesta: `_name_key` devuelve el grupo en vez del nombre.

**Y no borra nada**, que es la diferencia con `duplicate_of`. Las dos filas
siguen activas: cada una sirve para buscar por nombre y el mapa puede
mostrarlas. Lo único que se evita es visitarlas las dos en el mismo viaje. Por
eso el radio puede ser el triple del de deduplicación: agrupar de más cuesta un
candidato, borrar de más cuesta un lugar.

**Dos errores propios que el trabajo destapó.**

El representante se dejó en `NULL`, imitando a `duplicate_of`. Eso rompía la
regla entera: el miembro daba `grupo:<id>` y el representante daba su nombre,
así que **no coincidían nunca** y el día seguía visitando los dos. El
representante se apunta a sí mismo, y `NULL` queda reservado para "sin grupo".

Y la columna se creó con una clave foránea a su propia tabla, que volvía
circular el volcado del catálogo: `pg_dump` avisa, y el motivo es real —los
datos van en lotes de 500 INSERT y una fila cuyo grupo apunta a otra posterior
viola la restricción al insertarse—. `duplicate_of` ya era un UUID sin clave
foránea por exactamente eso, y estaba delante todo el tiempo.

El efecto en el banco: dos paradas menos —eran duplicados contados dos veces— y
mejor variedad, de 3,33 a **3,57** categorías distintas por día, con los días de
tres paradas seguidas iguales bajando del 20% al 17%.

### El nombre con el que la gente llama a un lugar

El reporte: *"Multiplaza San Salvador no existe en nuestro banco de datos?"*.
Sí existía —`Centro Comercial Multiplaza`, activo, el mismo sitio— y la
respuesta había sido *"probá con el nombre como aparece en el mapa"*, que desde
fuera es imposible de adivinar.

La causa es que `similarity` de pg_trgm compara **cadenas enteras**. Contra
`Centro Comercial Multiplaza`, la palabra `Multiplaza` ocupa un tercio del
texto y el resto cuenta como diferencia: 0,41 contra un umbral de 0,60. No era
un hueco del catálogo, era la métrica equivocada. Y no era un caso aislado:

| lo que uno escribe | antes |
|---|---|
| `Multiplaza` | no encontrado |
| `Metrocentro San Salvador` | no encontrado |
| `Galerías` | no encontrado |

`word_similarity` busca el mejor tramo de palabras **dentro** del nombre, que es
justo lo que alguien quiere decir al escribir el nombre corto de un centro
comercial. Se traen candidatos por las dos medidas y decide una regla de tres
pasos, donde cada paso nació de un fallo concreto:

1. **Un nombre prácticamente igual gana y no se discute.** Es lo que deja pasar
   los errores de escritura: `Volcan de Sant Ana` contra `Volcán de Santa Ana`
   son 0,86, y ninguna regla de contención debería poder tumbar eso.
2. **Si no, manda el encaje y no el parecido.** El fallo: `Las Cascadas`
   devolvía `7 cascadas`, una catarata, porque de cadena entera se parecen 0,64
   mientras `Centro Comercial Las Cascadas` se queda en 0,44 **por ser más
   largo**. Por encaje es al revés: 1,00 contra 0,75.
3. **Y el primero tiene que despegarse del segundo.** `Museo` encaja perfecto en
   veinte museos y `Galerías` en el centro comercial y en `Go Green Galerias`,
   un local que está adentro. Elegir uno sería la sustitución silenciosa que el
   resto del módulo evita.

**El parecido no desempata, y se probó que no debía.** Usarlo de segundo criterio
elegía sistemáticamente el nombre más corto —de dos que encajan igual gana el
que tiene menos texto alrededor— y con eso `Galerías` se iba al local de comida
rápida. Un empate de encaje es un empate de verdad.

Hay además un encaje mínimo que ataja al mal candidato solitario, que el margen
no ve: `Hotel California de Santa Ana` no existe, al recortarle la zona queda
`hotel california de`, y eso pesca `Parque Central de California` por una sola
palabra **sin que nadie le dispute el puesto**. La señal está medida: los
aciertos encajan enteros con 1,00 y los fallos se quedan en 0,70 o 0,75.

**Las tildes se quitan con `translate` y no con la extensión `unaccent`, y el
motivo es de despliegue.** Las migraciones corren al arrancar el contenedor —ver
`backend/start.sh`, que explica por qué no van en el `preDeployCommand` de
Railway— así que un `CREATE EXTENSION` sin permisos en el Postgres administrado
no sería un fallo de búsqueda: sería un contenedor que no levanta. `translate`
mapea carácter a carácter y no necesita nada instalado; comparado con la
extensión sobre los 5.786 lugares activos coinciden 5.785, y el único que
difiere es `¡Hey Cipote!`. Entra también la comilla tipográfica, que paga sola:
el catálogo trae `Oma’s Coffee Shop` con la comilla curva de OSM y nadie la
teclea.

**Y quitar la zona tiene que ser el último paso, no el primero.** Medido:
`Metrocentro Santa Ana` existe tal cual y recortarlo lo volvería ambiguo entre
tres Metrocentros; `Volcán de Santa Ana` recortado queda en `volcán de`, que se
parece igual al Volcán de Izalco. Solo se prueba cuando la frase entera ya no
encontró nada.

**Sugerir no es sustituir.** El día sigue sin empezar en un lugar que nadie
nombró; lo que cambia es que ahora se dice cuál podría ser:

> no encontré 'Galerias' tal cual, y no quiero empezar el día en otro lugar
> parecido sin preguntarte. ¿Era Centro Comercial Galerías o Go Green Galerias?
> Escribilo así y lo armo.

Las sugerencias llevan su propio umbral, más bajo que el de decidir pero no
tanto como el de buscar: con el umbral de búsqueda, a quien escribía `Hotel
California de Santa Ana` se le proponía el parque que acabábamos de rechazar por
malo. Una sugerencia equivocada es peor que ninguna, porque manda a la persona a
escribir un nombre que no quería.

| lo que uno escribe | antes | ahora |
|---|---|---|
| `Multiplaza San Salvador` | no encontrado | Centro Comercial Multiplaza |
| `Metrocentro San Salvador` | no encontrado | Metrocentro |
| `Las Cascadas` | **7 cascadas** (una catarata) | Centro Comercial Las Cascadas |
| `Museo` | **Museo Ajá**, a dedo | sugiere los tres |
| `Galerías` | no encontrado | sugiere los dos |

### Una ciudad nombrada como punto de partida es una zona

*"Dos días saliendo desde Santa Tecla, en carro"* —uno de los ejemplos del
compositor— fallaba. Santa Tecla es un municipio y está en el nomenclátor, pero
`start_place` se busca en el catálogo de lugares, donde lo que hay son
restaurantes que se llaman como ella.

Lo que devolvía antes era peor que el error: `Carymar Santa Tecla`, o sea que el
día arrancaba en un comedor que nadie había mencionado **y no lo decía**. Con la
búsqueda que no sustituye pasó a ser un error honesto —*"¿Era Carymar Santa
Tecla, Don Pollo Santa Tecla o Pizza Hut Santa Tecla?"*— que seguía sin servir.

Nombrar una ciudad como punto de partida no es nombrar una puerta: es decir
dónde ocurre el viaje. Así que cuando la búsqueda de lugares falla se consulta
el nomenclátor, y si el texto es una ciudad se usa como zona y el día no lleva
punto de partida. Se consulta **después** y no antes, para que un hotel que se
llame como un pueblo siga ganando como punto de partida.

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

## Distancias, rutas y cupos

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

### El cupo real es el que dice la cabecera, no el que dice la tabla

La tabla de planes de ORS publica esto para el plan Standard:

| endpoint | por día | por minuto |
|---|---|---|
| Directions V2 | 2.000 | 40 |
| Matrix V2 | 500 | 40 |

Y el encabezado `x-ratelimit-limit` de las respuestas de esta llave dice **50**
para matriz y **200** para direcciones: **una décima parte en los dos casos**.

Manda la cabecera, porque es la que coincide con lo que pasa: la matriz empezó
a responder `403 Quota exceeded` después de unas cuarenta llamadas en el día, no
de quinientas. Por eso el código trata `x-ratelimit-remaining` como la cifra
buena y el techo propio como un respaldo —`min(nuestro, el de ORS)`—, y no al
revés.

Queda sin explicar de dónde sale el factor diez. Las dos hipótesis razonables
son que la llave esté en un escalón anterior al que la página anuncia, o que la
tabla describa el plan al que se puede optar y no el que se otorga. Sin poder
distinguirlas desde fuera, el proyecto se comporta según lo que mide.

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

**Y esa cabecera no dice lo que parece.** Se leyó como "el trazo tiene 200 al
día y están casi sin usar", y horas después ORS contestaba `Quota exceeded` a
las direcciones **con `Remaining: 176` en esa misma cabecera**. Así que
`X-Ratelimit-Limit` describe otra cosa, no el cupo del día.

**La fuente estaba a un clic y nadie la había mirado.** La tabla de planes de
ORS publica los dos cupos del plan Standard:

| endpoint | por día | por minuto |
|---|---|---|
| Directions V2 | 2.000 | 40 |
| Matrix V2 | 500 | 40 |

Los techos que el proyecto se ponía a sí mismo —45 y 180— eran **diez veces más
bajos de lo necesario**, deducidos a golpes contra un límite que resultó ser
otro. Ahora son 450 y 1.800: el 90% de lo real, con margen para que una
petición hecha desde otro sitio con la misma llave no nos haga chocar contra el
límite de verdad.

Lo que sí se dedujo bien fue el ritmo: 1,5 s entre llamadas son exactamente las
40 por minuto que ORS permite en los dos endpoints.

Y sigue siendo cierto que **los dos se contabilizan aparte**: uno puede estar
agotado y el otro contestando.

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

### El cupo era el techo del proyecto, no un detalle de configuración

Con ORS, el banco de evaluación medía en línea recta a media corrida. Son 26
casos, cada uno con sus días; a 450 matrices y 1.800 trazos diarios, el cupo se
acababa antes que los casos. **Los presupuestos de kilómetros se afinaron, en
parte, sobre distancias estimadas.** Eso no invalida los números —la estimación
lleva su propio factor de desvío medido, 1.45— pero deja la duda abierta.

Un OSRM propio la cierra. El extracto de El Salvador son 33 MB, el grafo se
construye una vez, y contesta en milisegundos sin cupo, sin llave y sin
espaciado entre llamadas.

La corrida completa del banco contra OSRM, comparada con la última contra
estimaciones:

| | estimado | OSRM |
|---|---|---|
| Límites duros cumplidos | 25/26 | 25/26 |
| Paradas generadas | 319 | 320 |
| Lugares inventados | 0 | 0 |
| Días con "llevá comida" | 15% | 15% |
| Categorías distintas por día | 3,57 | 3,56 |
| Paradas fuera de hora | 0 | 0 |
| Aristas medidas | — | 2.678 |

**Los números aguantan.** Era el resultado que se quería y no el que se daba por
hecho: la alternativa —que la afinación estuviera sostenida por el error de la
estimación— habría aparecido justo acá.

Tres decisiones que vinieron con esto:

- **Son dos contenedores, no uno.** `osrm-routed` sirve un solo perfil: el que
  se preparó al construir el grafo. El perfil que va en la URL lo ignora, así
  que a pie y en carro necesitan cada uno el suyo.
- **La caché acepta cualquier fuente que no sea la estimación.** Filtraba por
  `source = 'ors'`, y eso habría dejado invisibles las 39.000 aristas ya
  medidas el día que alguien levantara su OSRM — justo cuando más duele. Lo que
  se guarda en `source` dice quién midió, para poder mirar atrás; no decide si
  la fila vale.
- **ORS sigue siendo el proveedor por defecto.** OSRM entra solo si está
  configurado. Quien clona el repo no tiene un grafo construido, y arrancar
  apuntando a un puerto vacío daría itinerarios en línea recta sin decir por
  qué.

Lo que se pierde es el detalle del perfil peatonal: el de OSRM es más simple
que el de ORS. En una zona urbana compacta —que es donde se camina— la
diferencia no se notó en el banco.

## Lo que se le dice al usuario

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

## Frontend y diseño

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

### El botón de copiar se salía del panel

Reportado con una captura: con el itinerario del Hotel Real Intercontinental,
el botón «Copiar» quedaba cortado por el borde derecho del panel.

La aritmética lo explica entera:

```
fila disponible: 383 px
título:          240 px  — y su MÍNIMO también 240, porque "Intercontinental"
                           es una sola palabra y no partía
Compartir 100 + Copiar 80 + huecos ≈ 200 px
240 + 200 = 440 en 383  →  Copiar quedaba 34 px fuera
```

El título llevaba `min-width: auto`, el valor por defecto de un elemento flex:
no puede encogerse por debajo de su contenido, y su contenido mínimo era esa
palabra. Los botones tenían `shrink-0`, así que lo que sobraba se salía.

**El primer arreglo fue peor, y lo dijo la medición.** Poner `flex-wrap` para
que los botones bajen de línea funciona con un nombre largo, pero medido con
«Suchitoto» también bajaban, cuando antes cabían perfectamente al lado: la
cabecera pasaba de 169 a 171 px y la acción se despegaba del título en todos
los itinerarios, no solo en los que lo necesitaban.

Lo que hacía falta era un orden: **que el título ceda primero y la palabra se
parta solo cuando ya no queda sitio.** `flex-1 min-w-0` lo deja encogerse por
debajo de su contenido, y `hyphens-auto` corta por sílabas —el documento ya
declara `lang="es"`, así que el navegador sabe dónde—. Sale «Hotel Real
Interconti-nental», que es una partición correcta.

Medido después: con nombre corto la cabecera vuelve a **169 px exactos** y los
botones siguen al lado; con el nombre largo nada se sale y los botones siguen
al lado también.

No se recortaron las etiquetas a solo iconos, que era la otra salida fácil: en
un teléfono no hay hover que las explique, y es el mismo criterio por el que el
crédito de la foto de zona va visible y no en un `title`.

### Un lugar pedido fuera de alcance se quedaba con el día entero

Reportado desde la demo, con el enlace del itinerario. Siete días desde el
Hotel Real Intercontinental, y el **día 1 salía vacío**: el hotel y nada más,
0 paradas, 0,0 km, de 09:00 a 09:00, mientras los otros seis iban llenos.

La petición incluía un lugar por su nombre —«Restaurante Ruta de las Flores»—
que está a **66 km** del hotel, con el radio de búsqueda en 12 km y el tope de
traslado en 60. O sea: inalcanzable, y la aplicación ya lo decía
correctamente —*«pediste ir a Restaurante Ruta de las Flores y no entró en
ningún día»*—. Lo que no decía es que además le había costado un día.

Reproducido con A/B local sobre los mismos datos:

```
con el lugar lejano pedido:  día 1 = 1 elemento (solo el hotel), 0,0 km
sin pedirlo:                 día 1 = 8 elementos, 28,0 km
```

La causa está en el llenado de un día anclado:

```python
if pendientes:
    dia.append(pendientes.pop(0))   # entra pase lo que pase
    semilla = dia[-1]
```

El lugar pedido se mete en el día **sin comprobar si cabe** y pasa a ser la
semilla alrededor de la cual se llena el resto. A 66 km, nada más entra, y el
día termina con el ancla sola.

El arreglo es comprobar antes que el día pueda ir y volver dentro de su tope.
Y no descarta el lugar: lo deja pendiente, porque otro día puede tener otro
modo y otro presupuesto. Si ningún día lo alcanza, termina sin colocar y la
violación lo reporta — que es lo que ya hacía bien.

**La comprobación solo vale para días anclados.** Sin punto de partida fijo, un
lugar lejano es simplemente la semilla de su propio día: «quiero ir a X» arma
el día alrededor de X y eso está bien. El problema aparece cuando además hay
que volver al hotel todas las noches.

El banco no se mueve —25/26, 334 paradas, 15%, variedad 3,64— porque ninguno de
sus casos pide un lugar fuera de alcance. Por eso llegó a producción: era un
hueco del banco, no un descuido del motor.

### El relieve, que es de lo que trata el viaje

De una lista de opciones para hacer el mapa más atractivo —Mapillary,
KartaView, CesiumJS, Mapbox GL, OSM Buildings, Three.js, los 3D Tiles de
Google— sobrevivió una, y no por gusto sino por dos filtros.

**El primero ya estaba escrito en el proyecto.** El comentario de `TESELAS`
dice por qué el satélite es Esri y no Mapbox: *«en un mapa de cliente la llave
viaja en el HTML y cualquiera puede gastarte el cupo»*. Eso descarta de entrada
Mapbox GL, Cesium ion y los 3D Tiles de Google, que además es de pago.

**El segundo fue medir.** KartaView responde sin credencial, así que se pudo
comprobar: tiene foto de calle a menos de 500 m de **2 de 45** paradas reales
—4%, y las dos en San Salvador—, con **cero** en miradores, naturaleza y
atracciones. Peor que las etiquetas de imagen de OSM, que ya estaban
descartadas por el mismo motivo. Mapillary pide credencial y quedó sin medir;
es la única de la lista que merecería el trámite.

De las libres sin llave quedaban OSM Buildings y Three.js, que necesitan
alturas de edificios. Los itinerarios del banco son Juayúa, Perquín, Costa del
Sol: ahí el 3D de edificios no dibuja nada.

Lo que sí entró es un **sombreado del terreno** debajo del mapa dibujado. Esri
`World_Hillshade` responde sin llave, igual que el satélite y por el mismo
motivo, y es una entrada más en la estructura que ya existía: no cambia el
motor del mapa.

**Y dice algo verdadero que el mapa plano no podía.** Este país es volcanes;
los itinerarios suben a miradores y cruzan crestas, y hasta ahora el mapa los
pintaba como manchas verdes planas.

Va **debajo** y no encima, con el mapa en `multiply` sobre él: el blanco de las
teselas de OSM deja pasar la sombra —el terreno aparece— y los nombres y las
carreteras, que son oscuros, se multiplican contra cualquier cosa y quedan
igual de legibles. Encima habría oscurecido las etiquetas.

No acompaña al satélite: ahí el terreno ya se ve, y multiplicar una foto aérea
contra un sombreado solo la ensucia.

### El mapa no mostraba el itinerario, y las fotos no eran la respuesta

La pregunta era de aspecto: ¿se pueden sacar imágenes, pintar algo más atractivo
en el mapa y en la lista? Lo primero fue medir si los datos daban para ello, y
tres ideas se cayeron antes de escribir una línea:

- **Una foto por parada.** De 190 lugares que salen en itinerarios reales, **uno**
  trae imagen directa; 30 tienen `wikidata` y 13 `wikipedia`. Esto ya estaba
  decidido y documentado en `FotoZona.tsx` —1,3% del catálogo, 2 de 2.718 en
  comida— y la medición nueva lo reprodujo. Un hueco de imagen vacío diecinueve
  de cada veinte veces parece una aplicación rota.
- **Una barra con la forma del día** (cuánto se viaja, se come, se visita). Los
  datos están, pero no dicen nada: sobre 60 días, la media es 12% traslado, 25%
  comer, 62% visitar y **0% de espera muerta**, y ningún día pasa del 22% de
  traslado. Un gráfico idéntico en los sesenta días no informa.
- **Un perfil de altitud**, que para un país de volcanes sonaba bien. El 7% de
  los lugares la trae, y **cero de los 25 miradores** — justo donde importaría.

Descartadas las tres, quedaba mirar la pantalla en vez de inventarle cosas. Y
ahí estaba el problema de verdad: **en la demo, el mapa no mostraba el
itinerario**. Tres de las siete paradas quedaban fuera de la ventana, la ruta se
salía por una esquina y media pantalla era territorio vacío.

**Leaflet encuadra contra el tamaño que tiene medido, no contra el que el
contenedor tiene.** Lo mide al crearse; si el plan llega antes de que la maqueta
se asiente, encuadra contra una caja que ya no existe. El diagnóstico fue un
evento de `resize` —que es exactamente lo que hace que Leaflet vuelva a
medirse—:

```
al cargar        4 de 7 paradas dentro de la ventana
tras un resize   7 de 7
```

El mapa siempre supo encuadrar. Lo que no sabía era su propio tamaño.

Se veía en los enlaces compartidos y no al armar un itinerario, y eso también
encaja: compartido, el plan llega de un solo `fetch`; armado, el stream tarda
segundos y para entonces la maqueta lleva rato quieta. Un `invalidateSize()`
antes de encuadrar lo arregla. Verificado con A/B sobre datos locales: un
itinerario pasaba de **5 de 7** a **7 de 7**, y otro de diez paradas no estaba
afectado en ninguna de las dos versiones — que es lo que hace que un fallo así
sobreviva tanto tiempo.

### Lo que cuesta entender una frase, y por qué la caché no sirve aquí

La tabla de métricas medía el coste de rutas —una petición a OpenRouteService
en zona fría, cero con la caché caliente— y del modelo, nada. El hueco estaba
anotado en «lo que falta» desde el principio.

`scripts/medir_tokens.py` lo llena. Envuelve el cliente real y deja que
`interpret` lo use como siempre, así que mide el camino de producción: si el
prompt crece, el número crece con él.

| | tokens | coste |
|---|---|---|
| Armar un itinerario | 3.246 (3.023 entrada + 223 salida) | 0,0041 USD |
| Revisar un día | 761 (631 + 130) | 0,0013 USD |

Unos **242 itinerarios por dólar**. Y uno cuesta **una sola llamada**: el motor
es determinista y no vuelve a consultar al modelo para armarlo — esa es la
tesis del proyecto, y aquí se le puede poner precio.

**El hallazgo es que el gasto casi no depende de lo que se escriba.** Ocho
frases de 19 a 150 caracteres dieron entre **3.222 y 3.300 tokens**: un 2,4% de
diferencia. La entrada es el 93% del gasto, y la entrada es casi toda el prompt
del sistema. Lo que se paga no es la petición, es el prompt.

**Y por eso la optimización obvia no aplica.** El prompt del sistema es idéntico
en todas las peticiones: es el caso de libro para el cacheo de prompts. Pero
`claude-haiku-4-5` exige un prefijo de **4.096 tokens** para activarlo, y el
nuestro ronda los **3.023**. Por debajo del mínimo no cachea **y no avisa**:
devuelve `cache_creation_input_tokens: 0` sin error, así que se habría
«activado» el cacheo, no se habría ahorrado nada, y no habría forma de notarlo
salvo mirando ese campo.

Queda anotado porque cambia con el modelo y no de forma monótona: el mínimo es
de 512 tokens en los modelos más nuevos y de 4.096 en Haiku 4.5. El día que se
cambie `planner_model`, esto puede pasar a ser gratis — o el prompt puede
cruzar los 4.096 por su cuenta y volverse cacheable sin tocar código.

Nota al margen del mismo rato: `chat_model` está en la configuración y **no se
usa en ninguna parte**.

### Una cocina inventada cuesta una comida

Visto en producción al probar lo recién desplegado. «Un día en San Salvador,
desayuno a las 7 y almuerzo hamburguesas» devolvía:

```
cocinas: {'breakfast': 'breakfast', 'lunch': 'burger'}
```

`breakfast` es una clave válida de `cuisine` en OSM —significa «sirve
desayunos»— así que el modelo la tomó por cocina. De ahí salía un aviso
ridículo: **«Pediste desayuno de desayunos y no encontré ninguno cerca»**.

El arreglo obvio era sacar esa clave del vocabulario que se le ofrece al
modelo, y se hizo: sirve para **mostrar** —la ficha sigue diciendo
«desayunos»— pero no para **pedir**, porque duplica lo que ya dice la comida.
Se descarta sin aviso: no es un error de la persona, es el modelo repitiendo
en la cocina lo que acaba de decir en la comida, y avisarlo sería un reproche
por algo que nadie pidió.

**Pero al volver a probar, el modelo había cambiado de invento**: ahora decía
`{'breakfast': 'cafe'}`. Y esa segunda versión era peor, porque no generaba un
aviso tonto sino que **se llevaba el desayuno por delante**:

```
sin cocina para el desayuno   →  breakfast: Viva Espresso ✓
con 'cafe' inventada          →  (sin desayuno)
                                 "El lugar más conveniente es Viva Espresso,
                                  que agrega 10.3 km y dejaría el día en 51.0"
```

El mismo comedor, a diez kilómetros de diferencia: pedir una cocina estrecha la
búsqueda a los sitios que la declaran, y el más cercano de esa cocina estaba
mucho más lejos que el más cercano a secas. La persona pidió desayunar a las
siete y se quedó sin desayuno porque el modelo decidió que quería café.

Así que la regla al modelo pasó de «solo cuando la nombra» a **«no lo deduzcas
nunca»**, con el contraejemplo explícito —«desayuno a las 7» dice CUÁNDO come,
no QUÉ come— y con la consecuencia medida escrita en el propio prompt. Las tres
frases de prueba salen limpias: la cocina solo aparece cuando se nombra un tipo
de comida.

La lección general: en este diseño, una restricción inventada por el modelo no
se queda en ruido. El motor la hace cumplir, y hacer cumplir algo que nadie
pidió cuesta exactamente lo mismo que hacer cumplir algo que sí.

### Revisar un día despintaba el mapa

Reportado desde la demo: al pedir un cambio en el campo conversacional, el día
se rehacía bien pero la ruta volvía dibujada en líneas rectas punteadas, como
si ya no se pidiera la geometría.

Era exactamente eso, y en un sitio tonto. `plan_with_routing` llama a
`load_route_geometry` y la devuelve en `PlanReady`; `revise_with_routing` no la
pedía nunca, y `RevisionResult` ni siquiera tenía campo para ella. El endpoint
pasaba `None` donde va el trazo:

```python
itinerary=_to_out(resultado.itinerary, resultado.stats, None, base, ...)
```

Así que un itinerario revisado volvía sin trazo **aunque la geometría estuviera
guardada en `route_legs` de la vez anterior**: no era un problema de cupo ni de
red, era un argumento en `None`. Medido contra el código de entonces, con el
mismo día de San Salvador: **0 de 4 tramos con trazo después de revisar, contra
4 de 4 antes**. Con el arreglo, 4 de 4 en los dos.

El trazo se pide sobre el orden definitivo y no sobre el del borrador, que es
la misma razón y el mismo orden que en `plan_with_routing`: con distancias
reales el orden del día cambia, y una geometría pedida sobre el borrador
dibujaría un recorrido que el itinerario ya no hace.

**Y volvió a aparecer el doble de sesión demasiado delgado.** El de
`test_revise_api` no implementaba `rowcount` ni `rollback`, y desde que revisar
también guarda el trazo, `persist_geometry` los necesita. Es el segundo doble
de este proyecto que falla por lo mismo: una sesión falsa que no puede deshacer
ni contar filas no es una sesión, y el fallo se lee como si fuera del código.

### Un día que arranca a las seis y come a las once y media

Reportado: «se me hace raro que este prompt no devuelve desayunos». Salir del
hotel a las 6 a.m. y tener la primera comida a las 11:30.

**No era un fallo: era la regla funcionando.** El desayuno es opt-in y el
prompt no lo nombraba. Pero la observación daba en un hueco real, y medirlo lo
confirmó. Sobre días con fecha en seis zonas, según la hora de arranque:

| arranca | ayuno medio | peor | días de 5 h o más |
|---|---|---|---|
| 06:00 | 6,5 h | 7,9 h | **100%** |
| 07:00 | 7,0 h | 11,7 h | **100%** |
| 08:00 | 6,1 h | 10,9 h | 83% |
| 09:00 | 4,3 h | 5,2 h | 33% |
| 10:00 | 3,8 h | 4,2 h | 0% |

Todo día que arranca antes de las ocho pasa cinco horas o más sin comer. No es
un caso raro, es la norma.

**La salida no es poner el desayuno solo.** Quien sale a las diez desayunó
donde durmió y no quiere un comedor a las nueve: esa es exactamente la razón de
que sea opt-in, y sigue siendo buena. Lo que estaba mal era el silencio. Sin
decir nada, la persona no tenía ni cómo enterarse de que podía pedirlo.

Así que se dice y se deja decidir, que es lo que hace el resto de los avisos:

> Este día arranca a las 06:00 y la primera comida es el almuerzo de las 11:30:
> 5 h 30 min sin comer. Si querés desayunar, pedímelo y lo meto

El umbral de cinco horas sale del corte de la tabla, no del gusto de nadie: es
donde se separan limpiamente los días que arrancan temprano —donde el ayuno es
universal— de los que arrancan tarde, donde no ocurre nunca.

Tres casos en los que calla: si ya pidió desayuno, si el día arranca pasada la
franja —no había desayuno posible, y ofrecerlo sería ofrecer algo que no se
puede dar— y si el ayuno no llega al umbral.

De paso resuelve un problema que no era de planificación sino de
descubrimiento: una opción que existe y que nadie encuentra es, en la práctica,
una opción que no existe.

### «Quiero almorzar hamburguesas»: dónde filtrar importaba más que filtrar

La cobertura de `cuisine` en OpenStreetMap resultó ser mucho mejor que la de
los horarios: **41,5% del catálogo** —1.128 de 2.717— contra el 15% de
`opening_hours`. Y con una distribución usable: pizza 151, pollo 116, comida
típica 105, mexicana 79, hamburguesas 51. Hasta las zonas chicas tienen algo:
Suchitoto 9 hamburgueserías, Ruta de las Flores 6.

Media pieza ya estaba construida: `_COCINAS` en `services/places.py` traducía
`burger` → «hamburguesas» desde que la ficha de cada parada muestra la cocina.
Lo que faltaba era usarla para **elegir** y no solo para mostrar.

**El hallazgo fue dónde va el filtro, y se encontró probándolo en el sitio
equivocado primero.** Lo natural parecía filtrar al colocar la comida. Medido
sobre un día en San Salvador —una ciudad con 51 hamburgueserías— ese filtro
imprimía:

```
(almuerzo: 0 de 8 candidatos son hamburgueserías)
```

Cero. El motor recorta a los ocho comedores más cercanos **antes** de colocar
la comida, y entre esos ocho no había ninguna. Filtrar ahí es filtrar una lista
que ya se decidió sin saber lo que se había pedido. El filtro va dentro de
`_meal_candidates`, donde se hace el recorte: los más cercanos de cada cocina
pedida entran **además** de los más cercanos a secas, porque la cocina se pide
para una comida y las demás del día siguen necesitando dónde elegir.

Tres decisiones más:

- **Es por comida, no global.** El primer intento filtraba todo y la cena
  quedaba condicionada por lo que se había pedido para el almuerzo.
- **No inventa, pero tampoco deja sin comer.** Si en esa zona no hay ninguna
  que declare la cocina, se cae a la lista entera y el aviso lo explica. Y lo
  explica con cuidado: el 58,5% del catálogo no trae `cuisine`, así que de su
  silencio no se deduce que no existan. El texto dice «no encontré ninguno
  cerca del recorrido **que lo diga**» y añade «puede haber alguno sin la
  etiqueta puesta».
- **Un valor de OSM puede traer varias cocinas.** `burger;sandwich;coffee_shop`
  es corriente, y ese sitio sirve hamburguesas aunque la ficha lo resuma como
  café. Se busca el término entre las partes, no se compara la cadena entera.

**Y la ficha mentía sin querer.** En San Salvador, «quiero almorzar
hamburguesas» devolvía Casa Xoxoctic —`coffee_shop;pizza;burger;sandwich`—
etiquetada como **café**. El motor había acertado y la pantalla hacía pensar lo
contrario. Ahora, cuando se pidió una cocina y el sitio la sirve, es esa la que
se muestra. Si no la sirve, se muestra la suya: mentir sería peor que no decir.

De paso, medir esto destapó un agujero del diccionario: de los 1.128 comedores
con `cuisine`, **104 (9%) no tenían ninguna etiqueta legible**. Entre los
valores que se caían estaba **«pupusas» en plural** —el diccionario solo tenía
la forma singular, y OSM usa las dos— y «salvadoran». Añadiendo los frecuentes,
los mudos bajaron a **36 (3%)**.

El banco no se mueve: 25/26, 334 paradas, 15% de «llevá comida», variedad 3,64.
Como el desayuno, esto solo actúa cuando se pide.

### El desayuno se pide, y quien odia madrugar no necesita una regla

La pregunta vino de usar la demo: ¿se puede poner desayuno? ¿Y si alguien dice
«odio madrugar», no ponérselo? Y de paso: los turistas cenan a las ocho o las
nueve, ¿no?

**Lo primero que hizo falta fue medir si los datos aguantan cada cosa.** De los
419 comedores del catálogo que publican horario en OpenStreetMap —el 15% de
2.717—, un sábado:

| hora | abiertos |
|---|---|
| 07:00 | 21% |
| 08:00 | 34% |
| 09:00 | 45% |
| 12:00 | 72% |
| 18:00 | 62% |
| 20:00 | **30%** |
| 21:00 | **14%** |

Y por zona, contando los que se sabe abiertos:

| zona | 08:00 | 18:00 | 20:00 |
|---|---|---|---|
| Ruta de las Flores | 7 | 16 | **7** |
| Suchitoto | 4 | 12 | **4** |
| Santa Ana | 11 | 21 | 9 |
| San Salvador | 62 | 122 | 81 |

**Así que la cena tardía se descartó, con el número delante.** La intuición es
correcta para San Salvador y se da vuelta fuera: en la Ruta de las Flores,
mover la cena a las 20:00 deja menos de la mitad de los sitios. La franja ya
llega hasta las 21:00 —lo que pasa es que el motor coloca la cena al abrir la
franja, y las 18:00 resulta ser justo donde está el pico de oferta—. Moverla
sería cambiar un valor por defecto bien calzado con la oferta real por uno que
sirve en una sola ciudad.

**Y lo de «odio madrugar» salió gratis.** Medido sobre el intérprete:

```
"...odio madrugar"  →  earliest_start 10:00
sin eso             →  earliest_start 09:00
```

El motor ya descarta una comida cuyo día no alcanza su franja —`dia.start <=
cierre`—. Con la franja de desayuno cerrando a las 9:30, un día que empieza a
las 10:00 no llega, y el desayuno no se pone. **Sin caso especial, sin regla
nueva.** El aviso lo dice con todas las letras: «Pediste desayuno y este día no
llega: empieza a las 10:00, después de que cierra la franja de desayuno a las
09:30».

Tres decisiones propias del desayuno:

- **Se pide, no se asume.** No entra por `include_meals` como el almuerzo y la
  cena: quien viaja casi siempre desayuna donde duerme, y meterle un comedor a
  las ocho de la mañana a todo el que madrugue sería decidir por él. Su
  ausencia tampoco se aconseja, o todo itinerario madrugador estrenaría un
  «llevá desayuno» que nadie pidió.
- **Dura 45 minutos, no 90.** Uno se sienta, come y sale. Noventa minutos a las
  ocho de la mañana se comen la primera visita. Si la persona pidió una
  duración para las comidas, manda la suya.
- **Puede ir primero, y antes no podía.** La búsqueda de posición arrancaba en
  1 porque un día no empieza almorzando, y esa misma regla dejaba al desayuno
  sin su único sitio natural: con la secuencia base, las ocho candidatas
  entraban por hora y por presupuesto y ninguna se podía colocar. Salvo que el
  día salga de un sitio fijo: ahí va detrás, que es ir a desayunar en vez de
  desayunar antes de salir del hotel.

**El fallo que costó encontrar fue de contabilidad.** Había una tabla global de
franjas y una cuenta aparte de cuántas comidas esperar, y funcionaban porque
coincidían por casualidad: con `MEAL_WINDOWS = (almuerzo, cena)`, tomar las
primeras `esperadas` daba lo correcto. Al entrar el desayuno a la tabla, `[:1]`
pasó a ser el desayuno: la reserva de kilómetros guardaba sitio para una comida
que ese día no se iba a poner, y se saltaba la cena.

Lo delató el banco, dos días más de «llevá comida» —de 9 a 11— en itinerarios
donde nadie había pedido desayunar. Y lo delató porque antes se comprobó que el
banco es determinista: dos corridas seguidas dieron cifras idénticas, así que
la diferencia no era ruido. La lista y la cuenta ahora salen de la misma
función.

Con eso, el banco vuelve exacto a la línea base —25/26, 334 paradas, 15% de
«llevá comida», variedad 3,64—: el desayuno no le toca un pelo a quien no lo
pide.

### La escapatoria existía y la puerta se cerraba antes de llegar a ella

Reportado desde la demo. La petición decía «ceno los dos días y **vuelvo antes
de las 11 p.m.**», y el itinerario contestaba:

> Pediste cena y este día no llega: termina a las 16:46 y la cena empieza a las
> 18:00, o sea 1 h 14 min de espera. **Decime hasta qué hora podés y lo acomodo**

Le pedía un dato que la persona acababa de dar, y que además no habría servido:
el día terminaba seis horas antes del tope que ella misma puso.

**El motor sí podía.** La última parada era Iglesia El Carmen —`culture`, cierra
a las 18:00— y salía a las 16:27: noventa y tres minutos de margen contra los
setenta y cuatro que hacían falta. Quedándose ahí un rato más, la cena entraba a
las 18:00 y el regreso al hotel caía sobre las 19:49, muy dentro de las 23:00.

Y la escapatoria ya estaba escrita. `_repartir_la_espera` convierte la espera
previa a una comida en rato en los lugares de antes, acotada por la luz y por
los horarios de cierre. El problema era de **orden**: corre dentro de
`schedule_day`, o sea después de que `_best_meal_insertion` ya descartó la
comida por llegar temprano. La puerta se cerraba antes de llegar a la salida.

El arreglo es que el suelo de hora temprana ceda lo que las paradas previas
puedan absorber. Lo que costó fue acotarlo, y lo acotó el banco en tres pasadas:

| | duros | paradas | variedad | días vacíos |
|---|---|---|---|---|
| antes | 25/26 | 320 | 3,56 | 0 |
| crédito en cualquier posición | 23/26 | **231** | **2,64** | **3** |
| solo al final de la secuencia | 24/26 | 332 | 3,59 | **2** |
| …y que la comida quepa antes del cierre del día | **25/26** | **334** | **3,64** | 0 |

- **Solo al final.** Una cena metida a media mañana no se adelanta: la franja la
  empuja a las 18:00 y todo lo que venía detrás queda fuera de hora y se cae.
  Ochenta y nueve paradas y tres días vacíos. Al final de la secuencia no hay
  nada que empujar.
- **Y que quepa antes de que cierre el día.** El suelo viejo lo impedía de
  casualidad. Sin esa comprobación, el caso `dia-corto` del banco —ventana de
  10:00 a 15:00— colocaba un almuerzo que terminaba a las 16:00 y el día entero
  se caía.
- **Para decidir, ninguna parada cuenta más que su propia duración.** El límite
  duro no sirve de criterio: un mirador abierto hasta el anochecer lo aceptaría
  todo, y con eso un día de una sola parada se quedaba **siete horas y media**
  ahí con tal de llegar a cenar. Lo detectó un test que ya existía —«si el día
  termina a media tarde, no se inventa una cena»—.

Ese techo vive solo en la decisión y no en el reparto, y la asimetría es
deliberada: el techo decide si vale la pena intentarlo, el reparto saca el mejor
día de una decisión ya tomada. Ponerlo también en el reparto dejaba hueco muerto
en el caso para el que esa función se escribió —un único mirador antes de la
cena, que debe quedarse hasta que toque salir— y hay un test que lo fija. La
estimación se queda corta a propósito: un sí de más mete una comida que deja
tiempo muerto, un no de más solo deja el día como estaba.

**Y el aviso dejó de pedir lo que ya le dijeron.** Cuando todavía queda día por
delante, lo que falta no son horas: es que a esa hora ya no hay dónde seguir.
Decirlo así es la diferencia entre una pregunta y un diagnóstico. El texto
anterior daba por hecho que el freno era el reloj, y es el mismo error que esta
bitácora ya tiene anotado en «Decir la causa equivocada, otra vez».

Resultado neto: catorce paradas más sobre el banco, mejor variedad, y el mismo
cumplimiento de límites duros.

### Volver a un itinerario: el servidor ya los tenía todos

Un plan se perdía al cerrar la pestaña, salvo que uno se acordara de copiar el
enlace. Y era una pérdida tonta, porque **el servidor ya guarda todos los
itinerarios**: eso es exactamente lo que hacen los códigos de compartir. Lo
único que faltaba era que el navegador recordara cuáles fueron tuyos.

Por eso esto no guarda contenido sino punteros: el código, y lo justo para
reconocer el plan en una lista sin tener que pedirlo —zona, días, paradas—. Si
alguien limpia el navegador pierde la lista, no los itinerarios; si todavía
tiene el enlace, el plan sigue ahí.

**Se recuerda lo que armaste, no lo que abriste de un enlace ajeno.** Un enlace
que te mandaron ya lo tenés, está en el mensaje donde llegó; un plan que
armaste y cerraste no está en ningún lado. La pérdida que esto arregla es la
segunda.

Va debajo de los ejemplos y no encima. En la primera visita la lista está
vacía, y los ejemplos son los que enseñan de qué es capaz el planificador;
quien ya tiene itinerarios sabe lo que hay y los encuentra igual.

**Lo guardado es entrada externa, y se valida como tal.** En `localStorage`
queda lo que escribió una versión anterior de este mismo código, lo que dejó
otra pestaña a medio escribir, o lo que alguien editó a mano. Una lista que se
pinta con `reciente.zona` y recibe un objeto sin `zona` revienta la pantalla de
entrada entera, que es lo primero que ve cualquiera. Cada entrada se valida y
las rotas se descartan **una por una**: que una esté mal no tiene por qué
borrar las otras cuatro.

Y los accesos van envueltos porque `localStorage` **lanza** —no devuelve
vacío— cuando el navegador bloquea el almacenamiento, que es el caso de una
ventana privada con las cookies de terceros apagadas. Es la misma razón por la
que `lib/tema.ts` envuelve los suyos.

Dos detalles que salieron de usarlo:

- **Un código que vuelve se sube, no se duplica.** Revisar un día vuelve a
  emitir el plan con el mismo código; sin esto la lista se llenaría de copias
  del mismo viaje y empujaría afuera a los demás.
- **Si el servidor ya no lo tiene, se saca solo.** Dejarlo en la lista es
  ofrecer una puerta que no abre. Se distingue del fallo de red por el 404 que
  ya devolvía `fetchCompartido`.

En un teléfono de 390×844 con tres itinerarios recordados, la lista queda 66 px
por debajo del pliegue del modal, que ya era desplazable por diseño. Se midió
antes de darlo por bueno: la primera lectura de la captura parecía un
desbordamiento y no lo era.

### El itinerario se baja al calendario, y el formato tiene trampas

Un itinerario con horas es, literalmente, una agenda. Hasta acá vivía en la
pestaña: se veía, se compartía por enlace, y nada más. Bajarlo al calendario es
lo que lo vuelve utilizable el día del viaje, con las alarmas y la ubicación
que el teléfono ya sabe manejar.

Se arma en el navegador y no en el servidor: son unas líneas de texto, el dato
ya está en pantalla, y una ida y vuelta más para formatear lo que ya tenemos
sería pagar latencia por nada. También significa que se despliega a Vercel sin
tocar Railway, que importa el día que Railway tiene los despliegues pausados.

**Solo aparece con fecha**, que es la misma regla que ya seguían la cabecera
del día y el clima: sin fecha no hay evento posible.

Lo que costó no fue generar el archivo sino que lo acepten. iCalendar es viejo
y estricto, y **ninguna de sus trampas se ve en la pantalla de quien genera el
archivo: fallan en el calendario de quien lo recibe**.

- **Las comas.** En el catálogo hay «La Puntilla, Zona de Restaurantes». Sin
  escapar, esa coma convierte el `SUMMARY` en dos valores y el evento llega con
  el nombre cortado, o el archivo no se importa. La barra se escapa primero, o
  se escaparían las barras que uno acaba de poner.
- **El límite de línea es de 75 octetos, no de caracteres.** Una «ñ» ocupa dos,
  así que contando caracteres un nombre con acentos se pasa sin que se note. El
  plegado cuenta bytes y continúa con un espacio al principio de la siguiente.
- **El UID tiene que ser estable.** Si llevara la hora de descarga, bajar el
  mismo día dos veces duplicaría los eventos en vez de actualizarlos. Lleva el
  código del itinerario compartido, que ya es estable.
- **El huso se declara.** Una hora flotante significa «la hora local de quien
  mire»: alguien que planifica el viaje desde Madrid vería las paradas siete
  horas corridas. Se emite un `VTIMEZONE` con −06:00 fijo y sin horario de
  verano, el mismo supuesto que hace `core/reloj.py`.

Validado sobre el archivo descargado de verdad, no sobre la cadena generada:
termina en CRLF, sin saltos sueltos, cero líneas de más de 75 octetos, bloques
`BEGIN`/`END` equilibrados y los siete UID únicos. 23 tests.

La etiqueta de cada parada —«Almuerzo», «Regreso al punto de partida», la
categoría— se le pasa desde el panel en vez de recalcularla. Si la lista dijera
«Almuerzo» y el evento «Comida», serían dos verdades del mismo dato.

Aparte, el enlace «Cómo llegar» de cada parada —que ya existía— ahora lleva el
modo del día. En un viaje que combina carro y caminata, abrir indicaciones en
carro para un día a pie manda por una carretera que ese día nadie va a tomar.

**Lo que no se hizo: un enlace de día completo a Google Maps.** La idea era
abrir el recorrido entero con todas las paradas en orden, y la documentación de
Maps URLs lo desarma: soporta hasta nueve puntos intermedios en escritorio pero
**solo tres en navegador de teléfono**, y donde no se soportan, el parámetro se
ignora. O sea, una ruta equivocada sin aviso, justo en el dispositivo donde uno
la usaría. En el banco, un día con n paradas lleva n−2 intermedias, y los días
de seis o más son 30 de 62: la mitad de los itinerarios romperían en silencio.
El enlace por parada no tiene ese techo, y además es como se viaja — se maneja
hasta la parada 1, se pasan dos horas ahí, y recién después se sale hacia la 2.

### Un botón no trae la manita, y eso no era un olvido

Lo reportó el usuario sobre las paradas del itinerario: responden al clic, pero
pasar el cursor por encima no cambia nada.

**Un `<button>` nativo usa `cursor: default`.** La hoja del navegador reserva
la manita para los enlaces, y eso es correcto según la especificación y falso
según lo que la gente espera: en la web de hoy todo lo que responde al clic la
muestra. No lo apagaba Tailwind ni ninguna regla del proyecto — era el valor
por defecto, intacto.

Medido sobre un itinerario en pantalla: de **29 elementos clicables, 16 no
tenían la manita**. Todos eran botones; los 13 que sí la tenían eran enlaces y
marcadores del mapa. O sea: no fallaba la lista de paradas, fallaban todos los
botones de la aplicación — «Empezar de nuevo», «Compartir», «Copiar», las
pestañas de día, Mapa/Satélite.

Por eso la regla va en la base y no en el componente donde se notó: arreglarlo
ahí habría dejado al próximo botón igual de mudo. Después del cambio, 28 de 29.

**El 29 es «Aplicar» deshabilitado, y queda así a propósito.** Sin texto
escrito no hace nada, y ofrecer la manita a algo que no responde es prometer de
más. Tampoco se usa `not-allowed`, que se lee como un error del usuario cuando
lo único que pasa es que todavía no escribió. Verificado: al escribir en el
campo pasa a `cursor: pointer`.

Aparte del cursor, la parada ahora se realza al pasar por encima. El realce
cubre **solo la columna del contenido**, que es lo que el botón envuelve: la
hora y la marca son celdas propias y no responden al clic, y pintarlas también
prometería un área que no existe. El relleno y el margen negativo se cancelan,
así que la caja crece hacia afuera y el texto no se mueve — medido, 0,00 px de
desplazamiento en las siete paradas.

El foco ya estaba resuelto: hay una regla global de `:focus-visible` con el
acento a 3:1 contra las dos superficies del tema.

### Tres paradas en el mismo pueblo se veían como una

En Suchitoto las paradas 4, 6 y 7 son el casco urbano. En el mapa se apilaban:
en un teléfono se veía la 4 y dos círculos asomando detrás. El número del pin
es el orden del recorrido, y un orden tapado no se lee ni se puede tocar.

Medido sobre los 60 días del banco, proyectados como los proyecta Leaflet:
**33 días (55%) tenían al menos un par de pines superpuestos, 69 pares en
total**. Los peores caen en el mismo píxel — «Ruinas de la Iglesia Vieja» y
«Vieja Parroquia de Santa María».

**Se separan en píxeles, no en coordenadas.** Dos paradas a 80 metros se tapan
a zoom 12 y se ven perfectas a zoom 16: lo que decide no es la distancia real
sino cuánta pantalla hay entre ellas. Por eso se recalcula en cada zoom, y por
eso el abanico **desaparece solo** en cuanto hay separación de verdad —
verificado en el navegador: al encuadrar, los pines 6 y 7 se abren 9,2 px cada
uno; al primer paso de zoom el corrimiento vuelve a cero.

El radio es el mínimo que despega a los vecinos del anillo: la cuerda entre dos
puntos separados por 2π/n en un círculo de radio r mide 2·r·sen(π/n), así que
r = diámetro / (2·sen(π/n)). Con dos pines da medio diámetro cada uno. El
abanico se centra en el punto compartido, de modo que el centro visual del
grupo sigue siendo donde están las paradas.

Un pin desplazado miente un poco sobre dónde está su lugar. El precio de no
hacerlo es que tres paradas se vean como una.

**El residuo se deja a propósito.** Con el abanico quedan 7 días y 13 pares:
cruzados, un pin que se abrió termina cerca de otro grupo que estaba justo
fuera del umbral. La salida obvia es repetir la pasada, y medida no sirve:

| pasadas | días con pines tapados | pares | corrimiento máximo |
|---|---|---|---|
| 1 | 7 (12%) | 13 | 35,2 px |
| 2 | 7 (12%) | 13 | 35,2 px |
| 3 | 7 (12%) | 13 | 42,2 px |
| 4 | 7 (12%) | 13 | 42,2 px |

Los grupos se rehacen y oscilan. Más pasadas mienten más sobre dónde están las
paradas y no destapan ni un pin.

El desplazamiento viaja dentro de los fotogramas de la animación de caída, no
después: una animación de `transform` pisa el `transform` del elemento mientras
corre, así que sin eso el pin caía en su sitio real y al terminar saltaba a su
lugar del abanico. Y va en el pin interior y no en el marcador que lo contiene
porque ahí Leaflet ya usa `transform` para colocarlo y `margin` para anclarlo:
las dos palancas de afuera están tomadas.

### La ruta salía partida en pedazos, y el culpable era un número viejo

Lo reportó el usuario: *"la ruta trazada a veces no se pinta a medias y le doy
zoom y se logra pintar pero entrecortada"*. Sonaba a problema de carga de datos.
No lo era.

El tramo se dibuja con una animación de trazado: `stroke-dasharray` igual al
largo del trazo y `stroke-dashoffset` de ese largo a cero. El largo se leía con
`getTotalLength()` justo después de crear la línea y se guardaba en una
variable CSS.

**Ese número envejece, y nadie lo volvía a mirar.** Por dos caminos:

- Se mide al agregar la línea, pero el mapa encuadra el itinerario *después*.
  El trazo se reproyecta más largo y el dasharray se queda con el valor viejo.
- Cada zoom vuelve a proyectar el trazo. El dasharray no se entera nunca.

Y cuando el dasharray queda más corto que el trazo, SVG no lo estira: **repite
el patrón**. Raya, hueco, raya. Medido en Chrome sobre un itinerario de tres
días:

| tramo | dasharray | largo real al cargar | tras acercar dos pasos |
|---|---|---|---|
| 1 | 443 px | 1.889 px | 3.557 px |
| 2 | 97 px | 419 px | 2.537 px |

O sea que **ya salía entrecortada al cargar**, no solo al hacer zoom: el
reporte decía "a veces no se pinta a medias" y eso era exactamente esto, un
trazo cubierto por dos o tres rayas con sus huecos.

La respuesta no es volver a medir en cada zoom —habría que escuchar `zoomend`
y recalcular cada tramo— sino dejar de medir. `pathLength="1"` le dice al
navegador que trate ese trazo como si midiera 1, sea cual sea su largo real.
Entonces `stroke-dasharray: 1` es el trazo entero a cualquier zoom. Es la
respuesta que SVG tiene para este problema.

Los tramos punteados quedan fuera a propósito: ahí el guion está en píxeles y
**es el dato** —dice que la distancia salió de la línea recta—. Normalizar el
trazo a 1 convertiría un guion de 2 px en uno del largo del tramo entero, o
sea en una línea sólida.

La función vivía dentro de `Mapa.tsx`, donde no se podía probar: Leaflet mide
elementos que en jsdom no tienen tamaño. Se movió a `components/trazo.ts`, que
recibe el nodo SVG y no sabe nada de Leaflet. Ocho tests, cinco de los cuales
fallan contra la versión anterior.

### Compartir un itinerario lo guarda el servidor, no el cliente

Hasta acá un itinerario vivía solo en la pestaña de quien lo pidió: se copiaba
como texto y nada más. Para un planificador de viajes eso es raro, porque el
acto siguiente a armar un plan es enseñárselo a quien va con vos.

La forma obvia es un `POST /share` que reciba el itinerario y devuelva un
código. **Esa forma guarda JSON arbitrario de un cliente para servírselo a
otros.** El frontend dibuja el sitio web de cada parada como un enlace, así que
un `javascript:` inyectado en ese campo sería XSS almacenado.

Como `/plan` ya tiene el itinerario armado del lado del servidor, se guarda ahí,
al terminar de armarlo y no cuando alguien pulsa compartir. Eso quita la entrada
del cliente de la ecuación y además hace que compartir sea copiar un enlace, sin
otra ida y vuelta: el código viaja con la última fase del stream.

El contenido se guarda entero y no se regenera al abrirlo. Un plan rearmado
puede salir distinto —el catálogo cambia, el pronóstico se mueve— y quien
comparte un itinerario comparte **ese**, no "lo que salga cuando lo abras".

Dos detalles:

- **El código no lleva `0`/`O` ni `1`/`I`/`l`.** Son 31 caracteres y diez
  posiciones, unos 49 bits: de sobra para que nadie llegue a un itinerario ajeno
  probando. Un enlace de viaje se dicta por teléfono más de lo que uno creería.
- **Guardar nunca lanza.** Compartir es un añadido: si la base está llena, lenta
  o caída, el itinerario tiene que llegar igual, solo que sin enlace. La primera
  versión cumplía esa promesa a medias —la comprobación de que la fila entró
  quedó fuera del `try`— y un fallo ahí se escapaba hasta el stream y tumbaba el
  plan entero. Lo encontró un test que ya existía, con un doble de sesión que no
  sabía hacer `rollback`.

### Las fuentes dejaron de ser de Google

Se pedían a `fonts.googleapis.com` con un `<link>`. Eso cuesta dos saltos antes
de ver texto con la fuente buena —resolver `fonts.googleapis.com`, leer la hoja,
y recién ahí ir a `fonts.gstatic.com` por el archivo— y de paso cuenta a cada
visitante ante un tercero.

La alternativa de manual es `next/font/google`, que autohospeda igual pero
descarga al compilar: ata el build a que Google esté alcanzable. Con los
archivos versionados en el repo y `next/font/local` no depende de la red nadie,
ni el build ni el navegador.

Se baja solo el subconjunto latino: cubre el español entero —acentos, eñe,
diéresis, los signos de apertura— y los nombres del catálogo. Son **94 kB** en
vez de los ~300 de todos los subconjuntos; lo que caiga fuera lo dibuja la
fuente del sistema, igual que cualquier glifo que falte.

El `display: swap` se mantiene, así que el texto se ve desde la primera pintura.
El salto que eso provoca lo absorbe `next/font`, que mide la fuente propia y
ajusta las métricas de la de reserva — que es precisamente lo que el `<link>` no
podía hacer.

---

### El itinerario se oscurece a la hora que de verdad oscurece

La petición era una animación que reaccionara al clima: lluvia cayendo sobre el
itinerario si el pronóstico la trae. Medí el pronóstico antes de dibujar nada
—84 días, seis zonas, la ventana de 09:00 a 20:00— y el dato dice que no:
**llueve en el 4% de esas horas**. Una animación que no sale casi nunca es una
animación que nadie ve.

El calor tampoco servía, por lo contrario: la temperatura va de 22° a 34° con
media de 29°, así que un efecto de calor saldría en todos los itinerarios y
diría lo mismo en todos. Un dato que no varía no es información.

Lo que sí varía dentro de **cada** itinerario es la luz. El motor ya calcula el
ocaso de la latitud y la fecha —`services/sol.py`, de 17:25 en noviembre a
18:28 en junio— y lo usa para no mandar a nadie a un mirador a oscuras. Ese
número estaba en el servidor y no llegaba a la pantalla.

Ahora llega: `DayOut.sunset` lo expone, y el hilo que une las paradas cambia de
color exactamente donde cae. El hilo ya era un eje de tiempo; ahora la posición
del corte **es** el dato, y se ve de un vistazo qué paradas quedan con luz sin
leer una sola hora.

Tres cosas que no eran obvias al escribirlo:

**El tramo se mide de llegada a llegada, no de salida a llegada.** El hilo
arranca bajo la marca de una parada y termina en la de la siguiente, así que lo
que abarca es todo ese rato, la estancia incluida. Medir solo el viaje dejaba
un hueco: un ocaso que cae mientras se cena no aparecía en ningún tramo.

**El color de la noche es `--acento`, no `--anil`.** El anil crudo sobre el
basalto del tema oscuro queda a ras del borde —`#2b3a67` contra `#2a353f`— y el
corte no se veía. `--acento` ya es el anil que cada tema puede permitirse.

**La hora no se tiñe: se dice.** Teñir la hora de las paradas nocturnas era lo
primero que hice, para que el dato no viviera solo en un color. Pero el anil
sobre el basalto baja ese texto menudo por debajo de AA, y `--tinta-suave` lo
cumple de sobra. Perder legibilidad para repetir algo que ya está escrito es
mal negocio: la hora se queda como estaba y lleva un `(ya de noche)` que solo
leen los lectores de pantalla.

Sin fecha no hay ocaso calculado, y entonces el hilo se queda del color de
siempre. Inventar a qué hora anochece para que el degradado salga siempre sería
exactamente el error que este proyecto evita en todo lo demás.

De paso salió un fallo viejo: la regla de `prefers-reduced-motion` acortaba la
duración de las animaciones pero no el `animation-delay`, y los escalonados de
esta pantalla —los pines, ahora el hilo— usan `backwards`, o sea que antes de
arrancar el elemento está a cero de opacidad. Quien pide menos movimiento veía
un parpadeo tardío de hasta medio segundo en vez de nada. Ahora el retraso
también se anula.

---

### La lluvia: medí mal y por poco entierro la función

Al descartar la animación de clima medí **horas con lluvia sobre horas de
paseo** y salió 4%. Con ese número dije que no y pasé a otra cosa. El número
era cierto y la pregunta estaba mal: lo que decide si un efecto se ve no es qué
fracción del tiempo llueve, sino **en cuántos itinerarios aparece**. Y lo medí
el 28 de octubre, al final de la temporada de lluvias, que es la peor fecha del
año para esa pregunta.

Volví a medir sobre las 20 zonas del nomenclátor, ventana de 09:00 a 20:00 y el
mismo umbral de 1 mm/h que usa el motor —320 días de pronóstico y 1.220 del
archivo histórico:

| | días con lluvia | itinerarios de 2 días | de 3 días |
|---|---|---|---|
| septiembre | **66%** | **85%** | **92%** |
| próximos 16 días | 13% | 21% | 28% |
| marzo | 9% | 14% | 18% |

En temporada sale en 9 de cada 10 itinerarios de tres días. Lo que lo decidió
no fue eso, sino el otro número: **de 1.540 días medidos, ni uno llovió la
ventana entera.** Media de 2,5 horas en septiembre, máximo 8. O sea que la
lluvia siempre marca *una parte* del día — el mismo criterio por el que la luz
del día ganó y el calor perdió.

La lección no es sobre la lluvia. Es que una medición que contesta la pregunta
equivocada se lee igual de convincente que una que contesta la correcta, y la
única defensa es decir en voz alta qué decide la pregunta antes de medirla.

**El motor ya lo sabía todo.** `_paradas_mojadas` calcula desde hace tiempo qué
paradas caen bajo agua, y solo las de afuera: que llueva mientras se está en un
museo no es un problema que resolver. Ese cálculo terminaba convertido en una
frase. Lo único que faltaba era dejarlo salir por parada, así que el predicado
se partió en `se_moja(parada, clima)` y `StopOut.rained_on` lo expone. Dos
lecturas del mismo hecho, una definición: el consejo nombra los lugares sin
repetirlos y la marca sale las dos veces que se pasa por el mismo sitio.

**Al lado del hilo, no encima.** El hilo ya dice dónde se acaba la luz, y dos
datos sobre la misma línea de un píxel se pisan. La lluvia ocupa una franja de
9 px pegada al hilo, con el trecho exacto que viene con agua, y la parada que
se moja lleva un paraguas. Un canal dice "este rato del día", el otro "y esta
parada tuya está afuera justo ahí".

Lo que costó afinarlo fue el tamaño. Las gotas solas no se ven: son finas y el
ojo las pierde en cuanto deja de mirar. Hizo falta un fondo tenue debajo —la
franja existe aunque uno no la mire— y dos capas de gotas a velocidades
distintas, porque una sola se lee como una textura quieta que alguien arrastra.
Se animan con `transform` sobre `::before` y `::after`, no con
`background-position`: el degradado se pinta una vez y de ahí lo mueve el
compositor. Y el radio es de 2 px y no capsular, porque con el radio completo
media hora de chubasco sale redonda por los dos lados y se lee como una
pastilla puesta ahí, no como el tramo de un eje.

Las tres primeras versiones se midieron en el navegador antes de elegir: una
franja de 6 px era invisible, una banda de 22 px detrás del hilo parecía un
esqueleto de carga, y la de 9 px con fondo fue la que se lee sin gritar.

Honestamente: dentro de esa columna de 24 px esto es una **banda discreta**, no
la animación aparatosa de la petición original. El sitio con espacio para eso
es el mapa, no la línea de tiempo.

---

### El backend ya contestaba y la pantalla tiraba la respuesta

La pregunta era si convenía un bot flotante sobre el mapa para que la revisión
pareciera un chat. La respuesta salió de leer qué devuelve `POST /plan/revise`
de verdad, llamándolo con tres pedidos:

| pedido | lo que devolvía |
|---|---|
| «empezá a las 7 y sólo 4 paradas» | `applied: {earliest_start: 07:00, max_stops_per_day: 4}`, `removed: [Montemilia, Monumento a La Constitución, Celeste Imperio, Palm Plaza]` |
| «menos carro, máximo 10 km» | `applied: {max_travel_km_per_day: 10.0}` |
| «sacá el museo» | 422 con explicación |

**El servidor nombraba una por una las cuatro paradas que quitaba, y
`page.tsx` se quedaba sólo con `resultado.itinerary`.** Un «sólo 4 paradas»
borraba cuatro lugares y la pantalla se callaba: había que comparar el antes
con el después, y el antes ya no existía porque tampoco había forma de volver.

Así que la burbuja no era la respuesta. La revisión no se sentía conversacional
porque **no contestaba** y porque **no se podía deshacer**, y una cáscara de
chat sobre eso habría prometido un hilo que no existe —cada revisión es una
orden que rehace el día, no un turno de una conversación con memoria—, encima
tapando mapa y diciendo «una IA te armó esto», que es justo lo que la división
entre modelo y motor existe para desmentir.

Lo construido es lo otro: la respuesta aparece sobre el mismo campo que la
pidió —qué restricción entendió, qué paradas sacó, qué no supo usar— y debajo
un «Volver al anterior».

**El historial vive en el cliente.** El servidor es sin estado a propósito:
cada revisión le manda el plan entero de ida y vuelta, así que guardar
versiones allá sería inventar sesiones para algo que la pestaña recuerda sola.
Se pierden al recargar, y está bien: lo que no se puede perder —el itinerario—
tiene su propio enlace. Es una pila y no un solo paso atrás porque revisar dos
veces seguidas es lo normal, y con un solo hueco el segundo cambio borra la
salida del primero.

De paso salió un defecto que nadie podía ver precisamente porque el campo se
tiraba: `applied` se serializaba con `str(v)` de Python. Una lista de
categorías llegaba al cliente como `"[<Category.nature: 'nature'>]"` —repr de
Python en una respuesta HTTP— y un número como texto. El día que alguien lo
pintara tendría que deshacer ese repr a mano, que es como se empieza a parsear
Python con expresiones regulares. Ahora sale JSON de verdad, y la traducción a
castellano vive en `lib/revision.ts`, que es donde toca: una API no debería
hablar castellano.

Dos detalles que no eran obvios:

**Deshacer sólo aparece cuando hay adónde volver**, no deshabilitado desde el
principio. Un botón apagado en el primer segundo enseña una puerta que todavía
no está y hace preguntarse qué falta para abrirla.

**Una clave de `applied` que no esté traducida sale cruda** en vez de
desaparecer. Si el motor aprende una restricción nueva y la pantalla no se
actualiza, el día se mueve igual: un cambio aplicado y sin nombrar es peor que
uno nombrado a medias.

Y en los tests, el mismo patrón que ya mordió antes: `Panel.prueba.tsx`
construía un segundo `<Panel>` a mano con la lista entera de props copiada, así
que añadir uno rompía la compilación de una prueba que no se había tocado. Pasó
a usar el ayudante que ya existía.

---

### «Respondió como éxito pero no lo agregó»

Reportado desde la demo: pedir «agregá desayuno» a un día que empieza a las
10:00. La revisión contestaba «Con desayuno» y el día salía sin desayuno. La
sospecha de quien lo reportó —que era por la hora de inicio— era correcta: la
franja del desayuno cierra a las 09:30.

Reproducido contra la API, el motor **ya sabía explicarlo**:

```
/itinerary  earliest_start 10:00 + must_include_meals [breakfast]
  advice: bring_breakfast → "Pediste desayuno y este día no llega:
          empieza a las 10:00, después de que cierra la franja"
```

Pero por el camino de la revisión salía `advice: []`. Dos fallos encadenados,
y ninguno visible desde el otro lado:

**1. El día revisado se juzgaba con las restricciones del viaje.** `revise_day`
rehacía el día con `restricciones_dia` —donde sí estaba el desayuno— y después
llamaba a `advise` con `constraints`, las del viaje, donde nadie lo había
pedido. `advise` leía ahí `must_include_meals`, no veía desayuno, y concluía
que no había nada que explicar. Ahora recibe `por_dia={target: ...}` y resuelve
las restricciones **dentro** del bucle de días, no antes.

Lo mismo pasaba con el corte de `include_meals`, que vivía antes del bucle:
una revisión que encendiera las comidas en un solo día se topaba con un
`return` que se había ido del itinerario entero sin mirar ninguno.

**2. Y aunque se generara, no se veía.** El consejo se pinta al final de la
lista de paradas —debajo de siete— mientras arriba, pegada al campo, la
revisión declaraba el éxito. Así que la respuesta de la revisión ahora carga
también los consejos **que ese cambio provocó**, diferenciados contra el
itinerario anterior: los que ya estaban siguen abajo, donde viven.

La lección es la de siempre con dos sitios que miran el mismo hecho: *aplicar
una restricción y cumplirla no son lo mismo*, y una pantalla que dice «Con
desayuno» está contando lo primero mientras quien lee entiende lo segundo.

Sin el itinerario anterior la comparación devuelve lista vacía en vez de
atribuirle al cambio todos los consejos del día. Entre atribuir de más y
callar, este proyecto calla: un día con lluvia pedida hace rato no se volvió
lluvioso porque alguien moviera la hora de inicio.

Lo que **no** se tocó: que esto sea consejo y no violación. No es un fallo del
motor —es consecuencia de la hora de inicio que se pidió— y el texto nombra la
causa y la hora exacta, que es más de lo que diría un `satisfies_all_
constraints: false`.

Banco después del cambio: 25/26 límites duros, 0 lugares inventados, 15% de
días con «llevá comida», 0 paradas fuera de hora.

---

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

**El clima no llega más allá de dieciséis días, y para más adelante no hay
nada.** Se dice en vez de rellenarlo, pero un viaje planificado para diciembre
se queda sin el dato. La salida sería la climatología: bajar los promedios
mensuales del archivo histórico de Open-Meteo una sola vez, guardarlos en tabla,
y responder "en esa época llueve casi todas las tardes" — sin llamada en vivo y
sin gastar cupo. No está hecho.

**Una zona sin lugares devolvía un 500.** `assemble` ligaba `medidor` dentro
del bucle de los días, así que un punto del país sin nada cerca llegaba a
`advise()` con el nombre sin asignar y reventaba con `UnboundLocalError`. El
arreglo es pasar `travel` en vez de un medidor ya resuelto, que es la regla que
el propio `assemble` enuncia doce líneas más arriba y que a `advise()` se le
había escapado; de paso, los avisos de un viaje que mezcla modos se calculaban
todos con la red del último día, así que el día a pie recibía consejos medidos
en carro.

**El clima informa y aconseja, pero todavía no decide.** El motor sabe que
llueve sobre el mirador de las 15:00 y lo dice; lo que no hace es preferir un
museo para esa franja y mover el mirador a la mañana. Eso tocaría la función de
costo, así que hay que medirlo contra los 26 casos antes de creerse que mejora
algo — es lo que ya pasó dos veces en este proyecto con cambios que parecían
obvios y no movieron nada.

---

## Lo que falta, en detalle

El [README](README.md#lo-que-falta) lo resume en una lista. Aca esta el motivo
de cada cosa, que es lo que importa cuando llegue el momento de arreglarla.

**El botón atrás del navegador no vuelve del itinerario.** La aplicación no
toca la URL, así que atrás saca del sitio. Que devuelva al estado vacío es
meter una entrada en el historial al enviar y escuchar `popstate`; arregla algo
que la gente ya trae aprendido del móvil. La petición escrita sí sobrevive a
"Empezar de nuevo", que era el caso más molesto.

**El volcado del catálogo no borra.** `make dump` genera
`INSERT ... ON CONFLICT DO NOTHING` más un `UPDATE` que sincroniza las
banderas, así que `make restore` se puede correr encima de producción: agrega
lo que falta y propaga las desactivaciones del filtro y de la deduplicación. Lo
que no hace es borrar: un lugar que ya no exista en el origen se queda en el
destino. Para eso hay que vaciar las cuatro tablas antes.

**Los itinerarios compartidos no se borran solos.** La tabla guarda la fecha de
creación y la cuenta de aperturas justamente para poder limpiarla —un enlace que
nadie abrió en tres meses no le hace falta a nadie—, pero no hay nada que corra
esa limpieza. Mientras el volumen sea el de un portafolio no molesta; con uso de
verdad, crece sin techo.

**El OSRM propio es solo local.** El grafo de El Salvador se arma con
`make osrm-datos` y se sirve en contenedor, así que en local no hay cupo ni
tercero. El despliegue sigue midiendo con ORS porque subirlo pide hornear el
grafo dentro de una imagen, y eso es un build de varios cientos de megas.

**La cobertura de horarios de apertura hace imposible el dato fino.** Once de
366 lugares bajo techo traen `opening_hours`. Mientras siga así, la hora de
cierre es una suposición uniforme y un museo que cierra a la una queda igual
que uno que cierra a las cinco.

**Los tests de frontend no cubren el mapa.** Leaflet toca `window` al importarse
y mide elementos que en jsdom no tienen tamaño; probarlo ahí sería probar un
doble. El mapa se verifica en un navegador de verdad, a mano. Lo que sí se
prueba es todo lo que se pudo sacar de Leaflet a un módulo aparte: la animación
del trazo, el abanico que separa los pines, y el cálculo de dónde se acaba la
luz.

**El clima informa y aconseja, pero todavía no decide.** Sabe que llueve sobre
el mirador de las 15:00 y lo dice; lo que no hace es mover el mirador a la
mañana. Reordenar por clima es meter una restricción blanda en un motor que hoy
solo conoce duras, y una restricción blanda mal pesada arruina itinerarios
enteros por una probabilidad del 30%.
