from sanic import Request, Sanic
from sanic.exceptions import SanicException
from sanic.response import HTTPResponse, json as json_response
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import settings
from .logging_config import setup_logging
from .models import Base
from .routes import bp

log = setup_logging()


def create_app(database_url: str | None = None) -> Sanic:
    log.info("Start aplikacji (poziom logów: %s, CORS: %s)", settings.log_level.upper(), settings.cors_origins)
    app = Sanic("worthmytime", configure_logging=True)
    app.config.FALLBACK_ERROR_FORMAT = "json"
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

    @app.before_server_start
    async def setup_db(app):
        url = make_url(database_url or settings.database_url)
        safe_url = url.render_as_string(hide_password=True)
        log.info("Łączenie z bazą danych: %s", safe_url)
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
                log.info("Połączono z bazą danych (%s)", url.get_backend_name())
                await conn.run_sync(Base.metadata.create_all)
                log.info("Schemat bazy gotowy (tabele: %s)", ", ".join(sorted(Base.metadata.tables)))
        except Exception:
            log.exception("Nie udało się połączyć z bazą danych: %s", safe_url)
            await engine.dispose()
            raise
        app.ctx.engine = engine
        app.ctx.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    @app.after_server_stop
    async def close_db(app):
        await app.ctx.engine.dispose()

    @app.on_request
    async def open_session(request: Request):
        if request.method == "OPTIONS":
            return HTTPResponse(status=204)
        request.ctx.db = request.app.ctx.sessionmaker()

    @app.on_response
    async def close_session(request: Request, response):
        db = getattr(request.ctx, "db", None)
        if db is not None:
            await db.close()
        origin = request.headers.get("origin")
        if "*" in origins:
            response.headers["Access-Control-Allow-Origin"] = "*"
        elif origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        else:
            return
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "600"

    @app.exception(SanicException)
    async def api_error(request: Request, exc: SanicException):
        return json_response({"error": str(exc)}, status=exc.status_code)

    @app.exception(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("Unhandled error")
        return json_response({"error": "Wewnętrzny błąd serwera"}, status=500)

    app.blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, debug=settings.debug, single_process=True)
