"""Configuración centralizada. Todo se lee de variables de entorno (ver .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base de datos: PostgreSQL en producción, SQLite sólo para desarrollo rápido.
    database_url: str = "sqlite:///./dealhunter.db"

    # Seguridad
    secret_key: str = "cambia-esto-en-produccion"
    access_token_minutes: int = 60
    refresh_token_days: int = 30
    cors_origins: str = ""  # lista separada por comas; vacío = sin CORS (la app Android no lo necesita)

    # Planes (los límites se aplican SIEMPRE en el backend)
    default_tier: str = "free"
    free_tracked_limit: int = 25
    premium_tracked_limit: int = 1000

    # Límites de peticiones (por IP, en memoria; usar un proxy/WAF delante en producción)
    rate_limit_auth_per_min: int = 10
    rate_limit_write_per_min: int = 60

    # Worker de precios
    worker_poll_seconds: int = 30
    worker_batch_size: int = 20
    default_check_interval_minutes: int = 360
    near_target_check_interval_minutes: int = 60
    near_target_threshold_pct: float = 10.0
    unavailable_source_interval_minutes: int = 1440
    max_retry_attempts: int = 6
    significant_change_pct: float = 1.0

    # Conectores (todas opcionales: sin credenciales el conector queda "no disponible")
    meli_access_token: str = ""
    meli_client_id: str = ""
    meli_client_secret: str = ""
    meli_refresh_token: str = ""
    meli_token_file: str = ""  # donde se guarda el refresh token rotado (p. ej. /data/meli_token.json)
    meli_site_id: str = "MCO"
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_marketplace_id: str = "EBAY_US"
    amazon_paapi_access_key: str = ""
    amazon_paapi_secret_key: str = ""
    amazon_partner_tag: str = ""
    aliexpress_app_key: str = ""
    aliexpress_app_secret: str = ""
    generic_fetch_enabled: bool = True
    http_timeout_seconds: float = 10.0
    user_agent: str = "DealHunterAI/1.0 (+https://github.com/julianfarks/dealhunter)"

    # Notificaciones push (Firebase Cloud Messaging HTTP v1)
    fcm_project_id: str = ""
    fcm_service_account_file: str = ""

    # IA opcional. La clave vive SOLO aquí, nunca en la app Android.
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"
    ai_requires_premium: bool = True

    # Tipos de cambio (fuente pública; se guardan con fecha y procedencia)
    fx_source_url: str = "https://open.er-api.com/v6/latest/USD"
    fx_refresh_hours: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()
