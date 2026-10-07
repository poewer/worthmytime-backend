from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "dev-secret-change-me-dev-secret-change-me"
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./worthmytime.db"
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_ttl_hours: int = 24 * 7
    cors_origins: str = "*"
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False
    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    rate_limit_api_per_minute: int = 300
    rate_limit_auth_per_minute: int = 20
    login_max_failures: int = 5
    login_lock_seconds: int = 900
    trust_proxy: bool = False  # True tylko za zaufanym reverse proxy (adres z X-Forwarded-For)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def production_problems(self) -> list[str]:
        """Błędy konfiguracji niedopuszczalne poza trybem DEBUG."""
        problems = []
        if self.jwt_secret == DEFAULT_JWT_SECRET:
            problems.append("JWT_SECRET ma wartość domyślną - ustaw własny sekret")
        elif len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            problems.append(f"JWT_SECRET jest krótszy niż {MIN_JWT_SECRET_LENGTH} znaków")
        return problems


settings = Settings()
