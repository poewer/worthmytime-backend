import os

# tryb deweloperski w testach (bez wymogu silnego JWT_SECRET)
os.environ.setdefault("DEBUG", "true")

from sanic import Sanic  # noqa: E402

Sanic.test_mode = True
