# Desplegar Waypoint

Backend en Railway, base en Neon, frontend en Vercel. Los tres tienen plan
gratuito y ninguno pide tarjeta.

---

## 1. La base en Neon

Crear el proyecto y **habilitar PostGIS**, que no viene por defecto:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

La migración `0001` también la crea, así que si el rol tiene permiso se puede
saltar este paso. Si Neon lo rechaza, hay que habilitarla desde su consola SQL
antes del primer despliegue.

La cadena de conexión que da Neon usa `postgresql://`. Este proyecto usa el
driver `psycopg` 3, así que hay que cambiarle el esquema:

```
postgresql+psycopg://usuario:clave@ep-xxx.neon.tech/waypoint?sslmode=require
```

---

## 2. Los datos

**Se copian de local, no se vuelven a descargar.** Las cifras del README
—5.652 lugares activos, 5,9% de descarte, 1.45 de factor de desvío sobre 812
pares— describen un momento concreto del catálogo. Volver a bajar de Overpass
daría un catálogo distinto, porque OpenStreetMap cambia todos los días, y el
README pasaría a describir algo que ya no existe sin que nada avise.

```bash
make dump      # saca catalogo.dump de la base local
make restore DATABASE_URL="postgresql://...neon.tech/waypoint?sslmode=require"
```

El volcado lleva `places`, `travel_edges` y el nomenclátor. Las aristas de
traslado importan: son cupo de OpenRouteService ya gastado, y llevarlas
significa que la demo arranca con la caché caliente en las zonas que ya se
consultaron.

---

## 3. El backend en Railway

Railway lee `railway.json` de la raíz. Construye con el Dockerfile del backend,
corre `alembic upgrade head` antes de publicar, y comprueba `/health`.

**No hace falta tocar el directorio raíz del servicio.** Railway construye con
la raíz del repo como contexto, y el `Dockerfile` copia desde ahí
(`COPY backend/requirements.txt ...`). `docker compose` usa el mismo contexto,
así que las dos construcciones son idénticas: si funciona en local, funciona
allá. El `.dockerignore` de la raíz evita mandar el frontend con sus
`node_modules`.

**Las migraciones corren al arrancar, en `start.sh`.**

La primera versión las dejaba en el `preDeployCommand` de Railway, que es lo
teóricamente mejor: corre una vez y no compite entre réplicas. No corrió. El
despliegue salió con PostGIS instalado, cero tablas y un `/health` diciendo
`ok`; el fallo apareció mucho después, al intentar cargar los datos.

Hay dos explicaciones posibles y desde fuera no se distinguen. La clave espera
un arreglo y estaba escrita como cadena. Y Railway **deprecó Config as Code**:
los `railway.json` siguen funcionando hasta el 2026-12-01 solo para servicios
que ya lo usaban, y los nuevos no pueden optar por él.

Como no se puede saber cuál de las dos fue, no se apuesta a ninguna. Migrar al
arrancar se prueba con un `docker run` antes de subir nada, y la pega conocida
—varias réplicas corriendo Alembic a la vez— no aplica: el límite por IP ya
obliga a una sola instancia con un solo worker.

El `preDeployCommand` queda en `railway.json` con la forma correcta. Si corre,
Alembic no hace nada la segunda vez.

**Antes del 2026-12-01** hay que migrar a Infrastructure as Code
(`.railway/railway.ts`) o mover esta configuración a la interfaz de Railway.

Variables de entorno:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | la cadena de Neon con `postgresql+psycopg://` |
| `ANTHROPIC_API_KEY` | la llave |
| `ORS_API_KEY` | la llave |
| `CORS_ORIGINS` | el dominio de Vercel, sin barra final |
| `TRUST_PROXY_HEADER` | `true` |
| `ENVIRONMENT` | `production` |

**`TRUST_PROXY_HEADER=true` solo acá.** El límite por IP lee
`X-Forwarded-For`, que lo pone quien manda la petición. Detrás del proxy de
Railway el encabezado se reescribe y es fiable; en local, encenderlo regala el
límite, porque basta cambiar el valor en cada llamada para saltárselo.

`PORT` lo inyecta Railway y `start.sh` lo lee. No hay que ponerla a mano.

---

## 4. El frontend en Vercel

Directorio raíz: `frontend`. El resto lo detecta solo.

| Variable | Valor |
|---|---|
| `NEXT_PUBLIC_API_URL` | la URL pública de Railway, sin barra final |

**Ojo con las vistas previas.** Vercel le da un dominio distinto a cada rama, y
`CORS_ORIGINS` solo lleva el de producción, así que las vistas previas van a
fallar contra el backend. Es lo correcto por defecto —una lista de orígenes con
comodín deja de ser una lista— pero conviene saberlo antes de asustarse.

---

## 5. Comprobar que quedó

```bash
curl https://TU-BACKEND.up.railway.app/health
curl https://TU-BACKEND.up.railway.app/places/stats
```

El `health` ahora comprueba las tres cosas sin las cuales el planificador
devuelve itinerarios vacíos: PostGIS, el esquema al día y un catálogo con
lugares. Si algo falta responde `degraded` con la lista de problemas, en vez
del `ok` que dio cuando la base estaba sin migrar.

```json
{"status": "ok", "postgis": "3.6.0", "schema_revision": "0006",
 "catalog_places": 5658, "issues": []}
```

Sigue respondiendo 200 aunque esté degradado. Un 500 haría que Railway lo
reinicie en bucle, y lo que falta son datos, no un proceso sano: reiniciar no
arregla nada y esconde el problema detrás de un contenedor que no para de
morir.

Después, un itinerario de punta a punta desde el navegador.

---

## Lo que hay que saber de este despliegue

**Un solo worker, y no es casualidad.** El límite por IP lleva su cuenta en
memoria del proceso. Con cuatro workers cada uno tendría la suya y el techo
real sería cuatro veces el configurado, sin que nada falle ni avise. Está fijado
en `start.sh` con el motivo escrito al lado. Si algún día hace falta escalar, el
orden es mover la cuenta a un almacén compartido primero y subir los workers
después.

**El arranque en frío se nota.** En el plan gratuito de Railway el contenedor
duerme, y la primera petición después de un rato paga el arranque más la
conexión a Neon. El `healthcheckTimeout` está en 120 segundos por eso.

**El cupo de rutas es de 50 al día y es global**, no por usuario. La caché lo
estira: una zona ya consultada no vuelve a gastar. Por eso el volcado incluye
`travel_edges`.
