.PHONY: up down logs migrate test lint psql

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

lint:
	docker compose exec api ruff check app tests
	docker compose exec api ruff format --check app tests

psql:
	docker compose exec db psql -U waypoint -d waypoint
