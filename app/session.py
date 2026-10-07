"""Sesja w ciasnym cookie (HttpOnly) z ochroną CSRF metodą double submit.

- `wmt_session`: token JWT, HttpOnly (niedostępny dla skryptów strony), Secure i SameSite z konfiguracji
- `wmt_csrf`: losowy token odczytywalny przez JS; zmieniające żądania uwierzytelnione cookie muszą odesłać go
  w nagłówku `X-CSRF-Token`. Nagłówek `Authorization: Bearer` nie wymaga CSRF (nie jest dołączany automatycznie).
"""

from __future__ import annotations

import secrets
from hmac import compare_digest

from sanic import Request
from sanic.response import HTTPResponse

from .config import settings
from .security import create_token

SESSION_COOKIE = "wmt_session"
CSRF_COOKIE = "wmt_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _cookie_kwargs() -> dict:
    return {
        "path": "/",
        "secure": settings.effective_cookie_secure,
        "samesite": settings.cookie_samesite.capitalize(),
        "domain": settings.cookie_domain or None,
        "max_age": settings.jwt_ttl_hours * 3600,
    }


def set_session_cookies(response: HTTPResponse, user_id: str) -> HTTPResponse:
    """Ustawia cookie sesji i CSRF; zwraca tę samą odpowiedź."""
    kwargs = _cookie_kwargs()
    response.add_cookie(SESSION_COOKIE, create_token(user_id), httponly=True, **kwargs)
    response.add_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), httponly=False, **kwargs)
    return response


def clear_session_cookies(response: HTTPResponse) -> HTTPResponse:
    domain = settings.cookie_domain or None
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", domain=domain)
    return response


def session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def csrf_valid(request: Request) -> bool:
    """Nagłówek musi się zgadzać z cookie CSRF (porównanie w stałym czasie)."""
    cookie = request.cookies.get(CSRF_COOKIE) or ""
    header = request.headers.get(CSRF_HEADER) or ""
    return bool(cookie) and bool(header) and compare_digest(cookie, header)
