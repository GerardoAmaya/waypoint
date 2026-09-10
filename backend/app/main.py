from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import itinerary, places, plan
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
app.include_router(plan.router)


@app.get("/health", tags=["infra"])
def health() -> dict:
    """Verifica que el servicio pueda hacer su trabajo, no solo que responda.

    **Antes decia "ok" con la base vacia.** El primer despliegue paso la
    comprobacion con PostGIS instalado, cero tablas y cero lugares: el
    comando previo de Railway no habia corrido y nada lo dijo. El fallo salio
    a la luz mucho despues, al intentar cargar los datos.

    Un chequeo que solo mira si hay conexion no comprueba nada util. Aqui se
    miran las tres cosas sin las cuales el planificador devuelve itinerarios
    vacios: PostGIS, el esquema al dia, y un catalogo con lugares.
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        postgis = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        ).scalar()

        # La revision de Alembic dice si las migraciones corrieron. None
        # significa que la tabla ni existe, o sea que nunca corrio ninguna.
        try:
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:
            revision = None

        try:
            lugares = conn.execute(
                text("SELECT count(*) FROM places WHERE is_active")
            ).scalar()
        except Exception:
            lugares = None

    problemas = []
    if not postgis:
        problemas.append("falta PostGIS")
    if not revision:
        problemas.append("las migraciones no han corrido")
    if not lugares:
        problemas.append("el catalogo esta vacio")

    return {
        # "degraded" y no un 500: el servicio esta vivo y responde, pero no
        # puede hacer su trabajo. Decir "ok" seria mentir, y devolver un error
        # haria que el orquestador lo reiniciara en un bucle que no arregla
        # nada, porque lo que falta son datos y no un proceso sano.
        "status": "ok" if not problemas else "degraded",
        "database": "connected",
        "postgis": postgis or False,
        "schema_revision": revision,
        "catalog_places": lugares,
        "ors_configured": bool(settings.ors_api_key),
        "llm_configured": bool(settings.anthropic_api_key),
        "issues": problemas,
    }
