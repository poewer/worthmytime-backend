import os

# tryb deweloperski w testach (bez wymogu silnego JWT_SECRET)
os.environ.setdefault("DEBUG", "true")
# limity żądań wyłączone w testach (testy ograniczeń tworzą aplikację z własnymi limitami)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# testy nie zależą od lokalnego .env (np. CORS_ORIGINS ustawionego pod przeglądarkę)
os.environ.setdefault("CORS_ORIGINS", "*")

from sanic import Sanic  # noqa: E402

Sanic.test_mode = True
