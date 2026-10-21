.PHONY: up down logs migrate test lint psql osrm osrm-datos osrm-down ors-check ors-trace ors-calibrate ors-warm ors-warm-apply ors-warm-zone zones refilter evaluate evaluate-real gazetteer gazetteer-dry web web-build web-check web-test dump restore

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

# --- OSRM propio ------------------------------------------------------------
#
# Construye el grafo de El Salvador una vez y levanta un servicio por perfil.
# Con esto se miden distancias sin cupo ni llave; ver app/services/osrm.py.
#
# Las tres ordenes son las de la documentacion de OSRM y van en ese orden:
# extract lee el .osm.pbf con un perfil de Lua, partition y customize preparan
# el algoritmo MLD, que es el que usa osrm-routed aca. Saltarse partition deja
# un grafo que arranca y contesta "NoRoute" a todo.
OSRM_IMAGEN = ghcr.io/project-osrm/osrm-backend:v5.27.1
OSRM_EXTRACTO = https://download.geofabrik.de/central-america/el-salvador-latest.osm.pbf

osrm-datos:
	@mkdir -p osrm/car osrm/foot
	@test -f osrm/el-salvador.osm.pbf || curl -fL --progress-bar -o osrm/el-salvador.osm.pbf $(OSRM_EXTRACTO)
	@for perfil in car foot; do \
		echo "--- preparando el grafo de $$perfil ---"; \
		cp osrm/el-salvador.osm.pbf osrm/$$perfil/el-salvador.osm.pbf; \
		docker run --rm -v "$(PWD)/osrm/$$perfil:/data" $(OSRM_IMAGEN) \
			osrm-extract -p /opt/$$perfil.lua /data/el-salvador.osm.pbf; \
		docker run --rm -v "$(PWD)/osrm/$$perfil:/data" $(OSRM_IMAGEN) \
			osrm-partition /data/el-salvador.osrm; \
		docker run --rm -v "$(PWD)/osrm/$$perfil:/data" $(OSRM_IMAGEN) \
			osrm-customize /data/el-salvador.osrm; \
		rm -f osrm/$$perfil/el-salvador.osm.pbf; \
	done
	@echo "listo. Pone esto en el .env y reinicia la api:"
	@echo "  OSRM_CAR_URL=http://osrm-car:5000"
	@echo "  OSRM_FOOT_URL=http://osrm-foot:5000"

osrm:
	@test -f osrm/car/el-salvador.osrm.mldgr || { echo "falta el grafo: corre primero make osrm-datos"; exit 1; }
	docker compose --profile osrm up -d osrm-car osrm-foot

osrm-down:
	docker compose --profile osrm stop osrm-car osrm-foot

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
# Una peticion de direcciones para saber si el trazo del mapa funciona ahora.
# check-ors prueba la matriz, que lleva su cupo aparte: uno puede estar agotado
# y el otro respondiendo.
ors-trace:
	docker compose exec api python -m scripts.check_directions

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
# rejected_reason, duplicate_of y same_place_as de cada lugar. Son las cuatro
# columnas que el filtro de calidad, la deduplicacion y la agrupacion de
# sitios cambian, y las unicas que hace falta igualar: el resto del registro no
# se edita, viene de OpenStreetMap.
#
# same_place_as entro despues y es facil de olvidar: la migracion crea la
# columna vacia, asi que sin esta linea el arreglo de "el mismo parque dos
# veces en un dia" se queda en local y produccion lo sigue haciendo.
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
		"SELECT 'UPDATE public.places p SET is_active = v.is_active, rejected_reason = v.rejected_reason, duplicate_of = v.duplicate_of, same_place_as = v.same_place_as FROM (VALUES ' \
		 || string_agg(format('(%L::uuid,%L::boolean,%L::text,%L::uuid,%L::uuid)', id, is_active, rejected_reason, duplicate_of, same_place_as), ',') \
		 || ') AS v(id, is_active, rejected_reason, duplicate_of, same_place_as) WHERE p.id = v.id;' FROM places;" \
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
