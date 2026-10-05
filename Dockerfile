FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000
RUN pip install --no-cache-dir \
    "sanic>=24.6" "pydantic[email]>=2.7" "pydantic-settings>=2.3" \
    "sqlalchemy[asyncio]>=2.0.30" "asyncpg>=0.29" "aiosqlite>=0.20" \
    "pyjwt>=2.8" "argon2-cffi>=23.1"
COPY app ./app
EXPOSE 8000
CMD ["python", "-m", "app.main"]
