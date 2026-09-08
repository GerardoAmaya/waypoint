# Waypoint

Planificador de viajes conversacional por El Salvador. Escribís tus gustos y
restricciones en lenguaje natural y el sistema arma un itinerario de varios días
sobre un mapa, con lugares reales y distancias reales.

**En construcción.** Ver `PLAN.md` para el alcance y las fases.

## Correr localmente

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api alembic upgrade head
curl http://localhost:8100/health
```
