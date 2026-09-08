"""Configuracion de la aplicacion."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Waypoint"
    environment: str = "development"

    database_url: str = "postgresql+psycopg://waypoint:waypoint@db:5432/waypoint"

    # Origenes permitidos, separados por coma. En produccion va el dominio real
    # del frontend: con localhost cableado el navegador bloquea todo.
    cors_origins: str = "http://localhost:3000"

    anthropic_api_key: str | None = None
    planner_model: str = "claude-haiku-4-5-20251001"
    chat_model: str = "claude-sonnet-5"

    ors_api_key: str | None = None
    ors_base_url: str = "https://api.openrouteservice.org"
    # Ritmo minimo entre llamadas a ORS. Controlar el ritmo en origen es mejor
    # que reintentar contra un limite que ya sabemos que existe.
    ors_min_interval_seconds: float = 1.5

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
