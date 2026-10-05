# WorthMyTime - backend

REST API (Sanic, Pydantic, SQLAlchemy async, Alembic).

## Uruchomienie lokalnie

```powershell
uv sync --python 3.12
uv run alembic upgrade head      # migracje (SQLite domyślnie, Postgres przez DATABASE_URL)
uv run -m app.main               # http://localhost:8001/api/v1/health
uv run ruff check .
uv run python -m pytest          # SQLite; TEST_DATABASE_URL=... uruchamia testy API na Postgresie
```

## Migracje (Alembic)

Schemat zarządzany jest wyłącznie migracjami; aplikacja przy starcie tylko sprawdza, czy tabele istnieją.

```powershell
uv run alembic revision --autogenerate -m "opis zmiany"   # po zmianie modeli w app/models.py
uv run alembic upgrade head
uv run alembic downgrade -1
```

Baza utworzona wcześniej przez `create_all` (bez tabeli `alembic_version`): `uv run alembic stamp head`.

Kontener wykonuje `alembic upgrade head` przy każdym starcie.

## Konfiguracja (`.env`, patrz `.env.example`)

| Zmienna | Opis |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` lub `sqlite+aiosqlite:///./worthmytime.db` |
| `JWT_SECRET` | min. 32 znaki; przy `DEBUG=false` aplikacja nie wystartuje z domyślnym lub krótkim |
| `CORS_ORIGINS` | lista domen po przecinku (`*` tylko do rozwoju) |
| `DEBUG` | `true` luzuje wymagania produkcyjne |
| `LOG_LEVEL` | `INFO` / `DEBUG` ... |
| `PORT` | domyślnie 8001 (w kontenerze 8000) |

Pełny stack (db + api + web): `docker compose up --build` w katalogu nadrzędnym (wymaga `JWT_SECRET`).
