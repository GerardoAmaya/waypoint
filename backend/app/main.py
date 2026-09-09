from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import itinerary, places
from app.core.config import settings
from app.core.db import engine

app = FastAPI(
    title=settings.app_name,
    description="Planificador de viajes conversacional por El Salvador.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


app.include_router(places.router)
app.include_router(itinerary.router)


@app.get("/health", tags=["infra"])
def health() -> dict:
    """Verifica la conexion y que PostGIS este disponible.

    PostGIS no es opcional: las consultas espaciales son el nucleo del
    proyecto. Si falta, el servicio no puede hacer su trabajo.
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        postgis = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        ).scalar()

    return {
        "status": "ok",
        "database": "connected",
        "postgis": postgis or False,
        "ors_configured": bool(settings.ors_api_key),
        "llm_configured": bool(settings.anthropic_api_key),
    }
