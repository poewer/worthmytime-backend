from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./worthmytime.db"
    jwt_secret: str = "dev-secret-change-me-dev-secret-change-me"
    jwt_ttl_hours: int = 24 * 7
    cors_origins: str = "*"
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False
    log_level: str = "INFO"


settings = Settings()
