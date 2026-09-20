from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    autoria_api_key: str | None = None
    database_url: str | None = None
    min_year: int = 2012
    min_market_discount_percent: float = 15.0
    check_interval_seconds: int = 900
    max_listings_per_check: int = 1
    market_cache_hours: int = 24
    autoria_retry_after_seconds: int = 900
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')


settings = Settings()
