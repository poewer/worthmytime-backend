from sanic import Request, Sanic
from sanic.exceptions import SanicException
from sanic.response import HTTPResponse, json as json_response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import settings
from .models import Base
from .routes import bp


def create_app(database_url: str | None = None) -> Sanic:
    app = Sanic("worthmytime", configure_logging=True)
    app.config.FALLBACK_ERROR_FORMAT = "json"
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

    @app.before_server_start
    async def setup_db(app):
        engine = create_async_engine(database_url or settings.database_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
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
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Vary"] = "Origin"

    @app.exception(SanicException)
    async def api_error(request: Request, exc: SanicException):
        return json_response({"error": str(exc)}, status=exc.status_code)

    @app.exception(Exception)
    async def unexpected(request: Request, exc: Exception):
        app.logger.exception("Unhandled error")
        return json_response({"error": "Wewnętrzny błąd serwera"}, status=500)

    app.blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, debug=settings.debug, single_process=True)
