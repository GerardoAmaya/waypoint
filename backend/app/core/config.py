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
    #
    # 1,5 s son exactamente 40 llamadas por minuto, que es el limite por minuto
    # que ORS publica para matrix y para directions en el plan Standard. El
    # numero se habia deducido antes de ver la tabla y resulto ser el correcto.
    # El Pacer es uno solo para los dos endpoints, asi que el ritmo total se
    # queda por debajo de los dos limites a la vez.
    ors_min_interval_seconds: float = 1.5
    # Techo propio de peticiones por ventana de 24 horas, uno por endpoint.
    #
    # **Los dos endpoints se contabilizan aparte en ORS**, y por eso hay dos
    # numeros: la matriz responde "Quota exceeded" mientras direcciones sigue
    # contestando, y al reves. Con un solo techo compartido, el que corriera
    # primero se llevaba el presupuesto del otro.
    #
    # Los cupos del plan Standard de ORS, leidos de su tabla de planes:
    #
    #     Directions V2   2000 / dia,  40 / minuto
    #     Matrix V2        500 / dia,  40 / minuto
    #
    # **Los techos de antes eran diez veces mas bajos de lo necesario.** Estaban
    # en 45 y 180 porque se dedujeron a golpes: la cabecera
    # `X-Ratelimit-Limit: 200` de las respuestas de directions parecia decir el
    # cupo del dia y no —con `Remaining: 176` ORS ya contestaba "Quota
    # exceeded"—, asi que describe otra cosa. La tabla del plan es la fuente.
    #
    # Se deja un 10% de margen: si el techo propio coincidiera con el de ORS,
    # cualquier peticion hecha desde otro sitio con la misma llave —la demo
    # publicada, por ejemplo— nos dejaria chocar contra el limite de verdad en
    # vez de frenar antes.
    ors_daily_budget: int = 450
    ors_directions_budget: int = 1800

    # Limite por IP. Los itinerarios cuestan tokens de Haiku y cupo de rutas, y
    # la demo no tiene cuentas: sin techo, una persona curioseando vacia el
    # cupo diario en un minuto.
    plan_per_minute: int = 4
    plan_per_day: int = 40
    # El endpoint sin modelo es mas barato, pero gasta cupo de rutas igual.
    itinerary_per_minute: int = 12
    itinerary_per_day: int = 120
    # El clima. Sin llave: Open-Meteo no la pide para uso no comercial, asi que
    # aqui no hay nada que configurar en produccion y el interruptor existe solo
    # para poder apagarlo.
    #
    # El tiempo de espera es corto a proposito. El clima es un añadido del
    # itinerario: si el servicio tarda, el plan sale sin el. Esperar treinta
    # segundos por un dato opcional convierte una mejora en una caida.
    weather_enabled: bool = True
    weather_timeout_seconds: float = 4.0

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
