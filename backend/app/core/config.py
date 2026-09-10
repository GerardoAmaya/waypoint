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
    # Techo propio de peticiones por ventana de 24 horas, uno por endpoint.
    #
    # **Los dos endpoints se contabilizan aparte en ORS**, y por eso hay dos
    # numeros: la matriz responde "Quota exceeded" mientras direcciones sigue
    # contestando, y al reves. Con un solo techo compartido, el que corriera
    # primero se llevaba el presupuesto del otro.
    #
    # **Lo que NO se sabe es cuanto da ORS al dia en cada uno.** La cabecera
    # `X-Ratelimit-Limit: 200` de las respuestas de direcciones parecia decirlo
    # y no: con `Remaining: 176` en esa misma cabecera, ORS ya contestaba
    # "Quota exceeded". O sea que esa cabecera describe un limite de RITMO y no
    # el cupo del dia, que no publica. Del de matriz solo sabemos que se agota
    # alrededor de las 50 peticiones, medido a golpes.
    #
    # Asi que estos numeros son techos NUESTROS, no espejos de los de ORS:
    # frenan antes de molestar al servicio y dejan margen para calibrar sin
    # quedarnos sin cupo para la demo. Al llegar al techo, los traslados se
    # estiman y las lineas se dibujan rectas: el itinerario sale igual.
    ors_daily_budget: int = 45
    ors_directions_budget: int = 180

    # Limite por IP. Los itinerarios cuestan tokens de Haiku y cupo de rutas, y
    # la demo no tiene cuentas: sin techo, una persona curioseando vacia el
    # cupo diario en un minuto.
    plan_per_minute: int = 4
    plan_per_day: int = 40
    # El endpoint sin modelo es mas barato, pero gasta cupo de rutas igual.
    itinerary_per_minute: int = 12
    itinerary_per_day: int = 120
    # X-Forwarded-For lo pone quien quiera. Solo se lee detras de un proxy que
    # lo reescriba; en local, confiar en el es regalar el limite.
    trust_proxy_header: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
