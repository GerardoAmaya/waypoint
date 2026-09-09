.PHONY: up down logs migrate test lint psql ors-check ors-calibrate ors-warm zones refilter

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

# Sin --apply solo dice cuanto costaria. El cupo son 50 peticiones al dia.
ors-warm:
	docker compose exec api python -m scripts.warm_travel_cache

# Comprueba que cada zona del nomenclator tenga lugares alrededor. No gasta cupo.
zones:
	docker compose exec api python -m scripts.check_zones

# Reaplica el filtro de calidad al catalogo cargado. No escribe sin --apply.
refilter:
	docker compose exec api python -m scripts.refilter_places
