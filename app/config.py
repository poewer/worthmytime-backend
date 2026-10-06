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
    # sesja w cookie: SameSite=lax przy froncie i API na tej samej stronie (site); przy różnych domenach "none"
    # (wymaga Secure i konkretnej domeny w CORS_ORIGINS)
    cookie_samesite: str = "lax"
    cookie_secure: bool | None = None  # brak = włączone poza trybem DEBUG
    cookie_domain: str | None = None
    trust_proxy: bool = False  # True tylko za zaufanym reverse proxy (adres z X-Forwarded-For)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def effective_cookie_secure(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else not self.debug

    def production_problems(self) -> list[str]:
        """Błędy konfiguracji niedopuszczalne poza trybem DEBUG."""
        problems = []
        if self.jwt_secret == DEFAULT_JWT_SECRET:
            problems.append("JWT_SECRET ma wartość domyślną - ustaw własny sekret")
        elif len(self.jwt_secret) < MIN_JWT_SECRET_LENGTH:
            problems.append(f"JWT_SECRET jest krótszy niż {MIN_JWT_SECRET_LENGTH} znaków")
        if self.cookie_samesite.lower() not in ("lax", "strict", "none"):
            problems.append("COOKIE_SAMESITE musi mieć wartość lax, strict albo none")
        elif self.cookie_samesite.lower() == "none" and not self.effective_cookie_secure:
            problems.append("COOKIE_SAMESITE=none wymaga COOKIE_SECURE=true")
        return problems


settings = Settings()
