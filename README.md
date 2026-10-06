# WorthMyTime - backend

REST API (Sanic, Pydantic, SQLAlchemy async, Alembic).

## Uruchomienie lokalnie

```powershell
uv sync --python 3.12
uv run alembic upgrade head      # migracje (SQLite domyĹ›lnie, Postgres przez DATABASE_URL)
uv run -m app.main               # http://localhost:8001/api/v1/health
uv run ruff check .
uv run python -m pytest          # SQLite; TEST_DATABASE_URL=... uruchamia testy API na Postgresie
```

## Migracje (Alembic)

> Na Windowsie `uv run alembic ...` bywa blokowane ("Failed to spawn ... Odmowa dostÄ™pu"), bo system nie pozwala uruchamiaÄ‡ plikĂłw `.exe` z `.venv\Scripts`. UĹĽyj wtedy `uv run python -m alembic ...` (albo `.\.venv\Scripts\python.exe -m alembic ...`). To samo dotyczy `pytest` i `ruff`.

Schemat zarzÄ…dzany jest wyĹ‚Ä…cznie migracjami; aplikacja przy starcie tylko sprawdza, czy tabele istniejÄ….

```powershell
uv run alembic revision --autogenerate -m "opis zmiany"   # po zmianie modeli w app/models.py
uv run alembic upgrade head
uv run alembic downgrade -1
```

Baza utworzona wczeĹ›niej przez `create_all` (bez tabeli `alembic_version`): najpierw oznacz jÄ… rewizjÄ… odpowiadajÄ…cÄ… jej schematowi, a potem zastosuj nowsze migracje. Baza sprzed `0002` (bez tabeli `budgets`):

```powershell
uv run alembic stamp 0001
uv run alembic upgrade head
```

Kontener wykonuje `alembic upgrade head` przy kaĹĽdym starcie.

## Konfiguracja (`.env`, patrz `.env.example`)

| Zmienna | Opis |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` lub `sqlite+aiosqlite:///./worthmytime.db` |
| `JWT_SECRET` | min. 32 znaki; przy `DEBUG=false` aplikacja nie wystartuje z domyĹ›lnym lub krĂłtkim |
| `CORS_ORIGINS` | lista domen po przecinku (`*` tylko do rozwoju) |
| `DEBUG` | `true` luzuje wymagania produkcyjne |
| `LOG_LEVEL` | `INFO` / `DEBUG` ... |
| `PORT` | domyĹ›lnie 8001 (w kontenerze 8000) |

PeĹ‚ny stack (db + api + web): `docker compose up --build` w katalogu nadrzÄ™dnym (wymaga `JWT_SECRET`).

## Kopie zapasowe i monitoring

Skrypty kopii zapasowej, test odtworzenia i monitoring `/health`: [ops/README.md](ops/README.md).

