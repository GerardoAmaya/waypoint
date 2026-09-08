# Waypoint — Plan del proyecto

Planificador de viajes conversacional por El Salvador. Escribís tus gustos y
restricciones en lenguaje natural; el sistema arma un itinerario de varios días
sobre un mapa, con lugares reales y distancias reales, y lo reorganiza cuando le
pedís cambios.

---

## Por qué este proyecto y no otro

Complementa a DocuFlow en vez de repetirlo.

| | DocuFlow | Waypoint |
|---|---|---|
| Problema | Documento sucio → datos limpios | Deseo vago → plan ejecutable |
| Núcleo técnico | Extracción y verificación | Restricciones y optimización |
| Salida | Tablas y respuestas citadas | Mapa, ruta y línea de tiempo |
| Interacción | Una pasada por documento | Conversación con estado y edición parcial |
| Riesgo principal | El modelo alucina un dato | El modelo ignora una restricción |

Alcance cerrado a El Salvador: 2.930 lugares con nombre en OpenStreetMap, que
caben completos en la base. Eso elimina la carga bajo demanda, los topes por día
y el arranque en frío. Todo instantáneo, siempre.

---

## Stack

| Capa | Elección | Por qué |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Es lo que pide el puesto; ya lo tenemos rodado |
| Base de datos | PostgreSQL en Neon | Ya está configurada |
| Consultas espaciales | PostGIS | Distancias y radios en SQL, no en Python |
| Mapa | Leaflet + tiles de OpenStreetMap | Sin key, sin tarjeta |
| Lugares | Overpass API | Sin key. Se consulta una vez, no en vivo |
| Rutas y tiempos | OpenRouteService | Cuenta gratis, sin tarjeta |
| Modelo | Claude (Haiku para armar, Sonnet para conversar) | Crédito disponible |
| Frontend | Next.js + TypeScript + Tailwind | Ya lo tenemos rodado |
| Streaming | Server-Sent Events | El itinerario se construye a la vista |

**Sin Celery esta vez.** La carga del catálogo es un script que corre una vez; la
generación de itinerarios es petición-respuesta con streaming. Meter una cola
sería complejidad sin beneficio.

**Sin embeddings.** La selección de lugares se resuelve con filtros espaciales y
por categoría, más el criterio del modelo sobre los candidatos. Repetir la
búsqueda vectorial de DocuFlow no agregaría nada al portafolio.

---

## Despliegue

| Pieza | Dónde | Notas |
|---|---|---|
| Base de datos | Neon | Habilitar PostGIS |
| Backend | Railway | Sin torch: imagen de ~200 MB, entra en el plan de prueba |
| Frontend | Vercel | Variable `NEXT_PUBLIC_API_URL` |

El contenedor de DocuFlow pesaba 747 MB por OpenCV y Tesseract. Este no lleva
ninguno de los dos, así que **no vamos a chocar con el límite de 1 GB** que nos
frenó la vez pasada.

---

## Riesgos ya identificados

Analizados **antes** de escribir código, que es la lección de DocuFlow.

**Google Maps y Mapbox exigen tarjeta de crédito.** Descartados. El stack de
arriba no pide tarjeta en ninguna pieza.

**Nominatim permite 1 petición por segundo y bloquea por IP.** Por eso el
catálogo se carga una sola vez con un script pausado, y la aplicación nunca
consulta esas APIs en vivo.

**OpenRouteService tiene cupo diario.** Es la única API que se consulta en
tiempo real. Mitigación: la distancia entre dos puntos fijos no cambia, así que
se calcula una vez y se guarda en tabla. Más el mismo espaciado entre llamadas
que ya construimos para Voyage.

**Los datos de OSM traen ruido.** En la muestra aparecieron duplicados
("Cascadas de Huizucar" dos veces), nombres inútiles ("Mirador", "El Museo") y
cosas que no son turismo ("Letrero de Sonsonate"). Un itinerario que recomiende
"visitá Mirador" arruina la demo. El filtro de calidad es parte de la fase 1 y
su tasa de descarte es una métrica del README.

**La demo es pública y sin autenticación.** Cada itinerario cuesta tokens. Hace
falta un límite por IP antes de publicar.

---

## Dirección de diseño

El frontend no es el envoltorio del proyecto: es lo que se ve en la primera
captura y lo que decide si alguien sigue mirando. Se trata como una fase con
criterios propios, no como maquetado al final.

### De dónde sale la paleta

Del sujeto, no de un generador de temas. El Salvador tiene tres materiales
visuales propios: la roca volcánica, el añil que fue su exportación histórica, y
la arena negra del Pacífico. De ahí salen los colores, no de un azul corporativo
cualquiera.

```
--basalto    #131a20   fondo del mapa, roca volcánica
--niebla     #f4f2ed   superficie del panel
--anil       #2b3a67   trazo de ruta y acento principal
--cafe       #8c5a35   marcador de comida
--verde      #3f7a5e   marcador de naturaleza
--ocre       #b8863f   marcador de cultura
```

Mapa oscuro contra panel claro. El contraste separa "el territorio" de "el
plan", que son las dos cosas que el usuario mira alternadamente.

### Tipografía

Una sola familia con carácter propio, más una monoespaciada reservada para
horas, distancias y montos, donde alinear por dígito es función y no estilo.

Queda descartado Inter: es el valor por defecto de todo dashboard y no dice
nada. La familia final se decide en la fase 6 probando dos o tres candidatas
sobre contenido real, no sobre texto de relleno.

### El momento memorable

Uno solo, y es evidente cuál: **el itinerario materializándose**.

El usuario escribe su frase y entonces, en secuencia: los pines caen sobre el
mapa uno por uno conforme llegan por streaming, la ruta se dibuja de parada en
parada, y la línea de tiempo se llena a la derecha. Dura unos segundos y ocurre
una sola vez por consulta.

Ese momento se cuida al detalle. Todo lo demás queda quieto y disciplinado.

### Movimiento: qué sí y qué no

**Sí, porque muestra lo que cambió:**
- Los pines caen escalonados, no todos juntos
- La ruta se dibuja siguiendo el orden real del recorrido
- Al editar un día, solo las paradas que cambian se mueven; el resto permanece
- El mapa encuadra suavemente cuando cambia el día seleccionado

**No, porque es el adorno genérico que delata una plantilla:**
- Aparecer con desvanecido cada sección al hacer scroll
- Transiciones en el hover de cada tarjeta
- Elementos que rebotan sin motivo
- Cualquier animación que no responda a una acción del usuario

### Piso de calidad

No se considera terminada la fase 6 sin esto:

- Funciona en móvil, con el mapa y el panel apilados
- Foco de teclado visible en todo elemento interactivo
- `prefers-reduced-motion` respetado: sin espera, el resultado aparece completo
- Contraste suficiente para leer el panel a plena luz
- Estados de vacío y de error redactados con dirección, no con disculpas
- Sin bibliotecas de componentes prefabricados que impongan su propio aspecto

### Bibliotecas

| Para qué | Cuál |
|---|---|
| Mapa | Leaflet con react-leaflet |
| Animación | Motion (antes Framer Motion) |
| Estilos | Tailwind |

Nada de kits de componentes. Un kit resuelve rápido y hace que el proyecto se
vea como los otros mil que usan el mismo kit.

### Cómo se juzga

"Que quede perfecto" no es verificable. Estos tres criterios sí:

1. Una captura de la pantalla principal se distingue de cualquier otro
   planificador de viajes
2. Alguien que nunca vio la aplicación entiende qué hace en cinco segundos
3. La secuencia de construcción del itinerario se puede grabar en quince
   segundos y se entiende sin narración

Si alguno falla, la fase 6 no está terminada.

---

## Fases

Cada fase deja algo verificable. No se pasa a la siguiente sin correr su
verificación.

### Fase 0 — Comprobaciones previas

Confirmar que PostGIS se puede habilitar en Neon, sacar la cuenta de
OpenRouteService y anotar su cupo diario real, y medir cuánto tarda una consulta
de ruta.

*Verificación:* `CREATE EXTENSION postgis` funciona y una llamada a ORS devuelve
una distancia.

### Fase 1 — Catálogo de lugares

Script que descarga los lugares de El Salvador desde Overpass, deduplica por
similitud de nombre más proximidad geográfica, filtra por calidad y los guarda
en Postgres con categoría, coordenadas y etiquetas.

*Verificación:* reporte con cuántos entraron, cuántos se descartaron y por qué.
Revisión a ojo de cincuenta al azar.

### Fase 2 — API de lugares

Consultas espaciales: qué hay cerca de un punto, dentro de un radio, filtrado
por categoría. Todo en SQL con PostGIS.

*Verificación:* "restaurantes a menos de 2 km del centro de Santa Ana" devuelve
resultados correctos.

### Fase 3 — Motor de itinerarios

El núcleo. Convierte restricciones en límites duros: hora mínima de inicio,
kilómetros máximos por día, presupuesto, categorías preferidas. Selecciona
lugares, los ordena geográficamente y asigna horarios.

*Verificación:* un conjunto de casos de prueba donde cada restricción se puede
comprobar de forma automática.

### Fase 4 — Distancias reales

Integración con OpenRouteService, con caché en tabla y espaciado entre llamadas.
Los tiempos de traslado alimentan la fase 3 en vez de ser decorativos.

*Verificación:* dos paradas conocidas devuelven un tiempo verosímil, y la
segunda consulta no llama a la API.

### Fase 5 — Capa conversacional

Interpretar la frase del usuario y extraer las restricciones. Streaming del
itinerario mientras se construye. Edición incremental: "el día 3 se ve caro"
recalcula solo el día 3.

*Verificación:* la edición parcial no altera los otros días.

### Fase 6 — Frontend

Mapa con pines y ruta, línea de tiempo del itinerario, chat lateral. Los pines
aparecen conforme llegan por streaming.

*Verificación:* la demo corre de punta a punta en el navegador.

### Fase 7 — Evaluación

Un conjunto de peticiones con restricciones conocidas y una medición automática
de cuántos itinerarios las cumplen todas. Más el conteo de lugares inventados,
que debe ser cero por construcción.

*Verificación:* números reproducibles para el README.

### Fase 8 — Despliegue y documentación

Railway, Vercel, límite por IP, README con capturas y métricas.

---

## Las métricas del README

Definidas desde ahora para que el proyecto se construya hacia ellas.

- **Cumplimiento de restricciones:** porcentaje de itinerarios que respetan
  todas las condiciones declaradas por el usuario
- **Lugares inventados:** debe ser cero. Cada parada sale del catálogo, no del
  modelo
- **Tasa de descarte del catálogo:** cuántos de los 2.930 sobrevivieron al
  filtro de calidad
- **Costo por itinerario** y latencia hasta el primer pin en pantalla

---

## Lo que no vamos a hacer

Reservas ni pagos. Cuentas de usuario. Aplicación móvil. Varios países.
Recomendaciones personalizadas por historial.

Cada uno de esos suena bien y ninguno agrega nada que un entrevistador no pueda
ver ya en las fases 1 a 7.
