"""Parametry listy obliczeń: limit, kursor, wyszukiwanie, filtr typu, sortowanie (czyste funkcje, bez I/O)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from .errors import ApiError
from .schemas import CalcType, Category

DEFAULT_LIMIT = 100
MAX_LIMIT = 200
SORTS = ("created_desc", "created_asc", "name_asc", "name_desc")


@dataclass(frozen=True)
class ListParams:
    limit: int = DEFAULT_LIMIT
    offset: int = 0
    q: str | None = None
    type: str | None = None
    category: str | None = None
    sort: str = "created_desc"


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        prefix, value = raw.split(":", 1)
        offset = int(value)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ApiError("Nieprawidłowy kursor", 422) from None
    if prefix != "o" or offset < 0:
        raise ApiError("Nieprawidłowy kursor", 422)
    return offset


def parse_list_params(args: dict) -> ListParams:
    """args: słownik parametrów zapytania (pierwsza wartość każdego klucza)."""
    try:
        limit = int(args.get("limit", DEFAULT_LIMIT))
    except ValueError:
        raise ApiError("Parametr limit musi być liczbą", 422) from None
    if not 1 <= limit <= MAX_LIMIT:
        raise ApiError(f"Parametr limit musi być z zakresu 1-{MAX_LIMIT}", 422)

    sort = args.get("sort", "created_desc")
    if sort not in SORTS:
        raise ApiError(f"Parametr sort musi być jednym z: {', '.join(SORTS)}", 422)

    type_ = args.get("type")
    if type_ is not None and type_ not in {t.value for t in CalcType}:
        raise ApiError("Parametr type musi być jednym z: SIMPLE, RECURRING, TCO", 422)

    category = args.get("category")
    if category is not None and category not in {c.value for c in Category}:
        raise ApiError("Parametr category musi być jednym z: NEEDS, FUTURE, GOALS, FUN", 422)

    q = (args.get("q") or "").strip() or None
    if q and len(q) > 100:
        raise ApiError("Parametr q może mieć najwyżej 100 znaków", 422)

    cursor = args.get("cursor")
    return ListParams(
        limit=limit,
        offset=decode_cursor(cursor) if cursor else 0,
        q=q,
        type=type_,
        category=category,
        sort=sort,
    )


def escape_like(text: str) -> str:
    """Znaki specjalne LIKE (%, _) w frazie użytkownika traktujemy dosłownie."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
