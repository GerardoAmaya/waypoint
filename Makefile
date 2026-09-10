.PHONY: up down logs migrate test lint psql ors-check ors-calibrate ors-warm ors-warm-apply ors-warm-zone zones refilter evaluate evaluate-real gazetteer gazetteer-dry web web-build web-check web-test dump restore

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

migrate:
	docker compose exec api alembic upgrade head

test:
	docker compose exec -e TEST_DATABASE_URL="postgresql+psycopg://waypoint:waypoint@db:5432/waypoint_test" \
		api python -m pytest tests/ -v

# Las mismas carpetas que revisa CI. Si divergen, make lint pasa y CI falla.
lint:
	docker compose exec api ruff check app tests scripts
	docker compose exec api ruff format --check app tests scripts

psql:
	docker compose exec db psql -U waypoint -d waypoint

ors-check:
	docker compose exec api python -m scripts.check_ors

ors-calibrate:
	docker compose exec api python -m scripts.calibrate_travel --sample 30

# Dos objetivos y no una bandera, como con el nomenclator: `make ors-warm
# --apply` no funciona —make se come el `--apply` como opcion propia y nunca
# llega al guion— y con un cupo de 50 peticiones al dia, un comando que
# aparenta gastar y no gasta es peor que uno que no existe.
#
# ors-warm no gasta nada: dice cuanto costaria. ors-warm-apply gasta.
ors-warm:
	docker compose exec api python -m scripts.warm_travel_cache

ors-warm-apply:
	docker compose exec api python -m scripts.warm_travel_cache --apply

# Una zona sola, para repartir el cupo en varios dias:
#   make ors-warm-zone ZONE=ataco
ors-warm-zone:
	@test -n "$(ZONE)" || (echo "Falta ZONE. Ej: make ors-warm-zone ZONE=ataco"; exit 1)
	docker compose exec api python -m scripts.warm_travel_cache --apply --zone "$(ZONE)"

# Comprueba que cada zona del nomenclator tenga lugares alrededor. No gasta cupo.
zones:
	docker compose exec api python -m scripts.check_zones

# Carga el nomenclator: departamentos, municipios, pueblos y barrios de OSM.
# Es lo que hace que "vivo en Mejicanos" resuelva; sin el, el proyecto solo
# conoce las veinte zonas escritas a mano.
gazetteer:
	docker compose exec api python -m scripts.load_gazetteer

gazetteer-dry:
	docker compose exec api python -m scripts.load_gazetteer --dry-run

# Reaplica el filtro de calidad al catalogo cargado. No escribe sin --apply.
refilter:
	docker compose exec api python -m scripts.refilter_places

# Mide cuantos itinerarios cumplen todas sus restricciones. No gasta cupo.
evaluate:
	docker compose exec api python -m scripts.evaluate --verbose

# Lo mismo con rutas reales de ORS. Gasta cupo: una peticion por caso.
evaluate-real:
	docker compose exec api python -m scripts.evaluate --real-routes

# El frontend corre fuera de docker: recarga en caliente sin montar volumenes.
web:
	cd frontend && npm install && npm run dev

web-build:
	cd frontend && npm run build

web-test:
	cd frontend && npm test

# Las mismas comprobaciones que corre CI sobre el frontend, en el mismo orden.
web-check:
	cd frontend && npm run typecheck && npm run lint && npm test && npm run build

# --------------------------------------------------------------------------
# Despliegue. Ver DEPLOY.md.
# --------------------------------------------------------------------------

# Vuelca los datos, no el esquema: el esquema lo pone Alembic en el destino.
# Se copian de local en vez de volver a bajar de Overpass porque las cifras del
# README describen ESTE catalogo, y OpenStreetMap cambia todos los dias.
#
# travel_edges va incluida a proposito: son peticiones a OpenRouteService ya
# pagadas, y llevarlas hace que la demo arranque con la cache caliente.
#
# **Con INSERT y ON CONFLICT DO NOTHING para que se pueda volver a correr.**
# Con COPY el volcado solo servia contra una base recien creada: sobre una que
# ya tenia los datos, psql chocaba con la clave primaria y abortaba por el
# ON_ERROR_STOP. Y eso es justo el caso normal —agregar al catalogo lo que se
# bajo despues del primer despliegue, como los 132 centros comerciales— asi
# que el volcado que hacia falta era uno aditivo.
#
# El precio esta medido y es aceptable: son 10.132 filas en total, asi que un
# INSERT por lote de 500 no cambia nada en la practica.
#
# **Y despues se sincronizan las banderas, porque los INSERT no pueden.**
# ON CONFLICT DO NOTHING no toca lo que ya existe, asi que una desactivacion
# no viaja: se filtro "2a Calle Poniente" —una calle etiquetada como
# atraccion, que entraba a los itinerarios con noventa minutos de visita— y en
# el destino seguia activa. Lo mismo con lo que decide la deduplicacion, que
# se recalcula entera en cada carga.
#
# Asi que al final del volcado va un UPDATE que iguala is_active,
# rejected_reason y duplicate_of de cada lugar. Son las tres columnas que el
# filtro de calidad y la deduplicacion cambian, y las unicas que hace falta
# igualar: el resto del registro no se edita, viene de OpenStreetMap.
#
# La tabla va cualificada como public.places: pg_dump pone `search_path = ''`
# en la cabecera del volcado, asi que un nombre sin esquema no se encuentra y
# el UPDATE muere con "relation does not exist".
#
# Sigue sin borrar nada: un lugar que ya no exista en el origen se queda en el
# destino. Para eso hay que vaciar las cuatro tablas antes, y eso es otra
# operacion.
dump:
	docker compose exec -T db pg_dump -U waypoint -d waypoint \
		--data-only --no-owner --no-privileges \
		--inserts --on-conflict-do-nothing --rows-per-insert=500 \
		-t places -t place_names -t travel_edges -t route_legs \
		> catalogo.dump
	@docker compose exec -T db psql -U waypoint -d waypoint -t -A -c \
		"SELECT 'UPDATE public.places p SET is_active = v.is_active, rejected_reason = v.rejected_reason, duplicate_of = v.duplicate_of FROM (VALUES ' \
		 || string_agg(format('(%L::uuid,%L::boolean,%L::text,%L::uuid)', id, is_active, rejected_reason, duplicate_of), ',') \
		 || ') AS v(id, is_active, rejected_reason, duplicate_of) WHERE p.id = v.id;' FROM places;" \
		>> catalogo.dump
	@wc -c catalogo.dump
	@grep -c "ON CONFLICT DO NOTHING" catalogo.dump | xargs echo "lotes de insercion:"
	@grep -c "SET is_active = v.is_active" catalogo.dump | xargs echo "sincronizacion de banderas:"

# Requiere DATABASE_URL con la cadena de Neon y psql instalado en la maquina.
#   make restore DATABASE_URL="postgresql://...neon.tech/waypoint?sslmode=require"
#
# Se puede correr encima de un destino que ya tiene datos: agrega lo que falta
# y deja lo que hay. Ver el comentario de dump.
restore:
	@test -n "$(DATABASE_URL)" || (echo "Falta DATABASE_URL"; exit 1)
	@test -f catalogo.dump || (echo "Falta catalogo.dump: corre make dump primero"; exit 1)
	psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f catalogo.dump
	@echo "Comproba con: curl TU-BACKEND/places/stats"
