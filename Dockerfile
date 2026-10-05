FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000 PATH="/app/.venv/bin:$PATH" UV_COMPILE_BYTECODE=1

# zależności z lockfile (te same wersje co lokalnie)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

EXPOSE 8000
# migracje przy każdym starcie; potem API
CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]
