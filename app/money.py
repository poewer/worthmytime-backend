"""Kwoty i zaokrąglenia w jednym miejscu.

Python `round()` zaokrągla do parzystej na reprezentacji binarnej (round(2.675, 2) == 2.67, round(0.5) == 0),
co dla pieniędzy daje niespodzianki. Tutaj zaokrąglamy zawsze ROUND_HALF_UP (od połowy w górę, dla ujemnych
od zera) na dziesiętnym zapisie liczby, więc 2.675 -> 2.68, a wynik jest zwykłym float (kontrakt API bez zmian).
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, overload

MONEY_DIGITS = 2  # kwoty w groszach (kolumny NUMERIC(14,2))
RATE_DIGITS = 4  # stawka godzinowa trzyma więcej miejsc, żeby nie zniekształcać przeliczeń (NUMERIC(14,4))


def _decimal(value: float | int | str | Decimal) -> Decimal:
    # repr() daje najkrótszy zapis, który wraca do tego samego float (0.1 -> '0.1', a nie 0.1000000000000000055...)
    return value if isinstance(value, Decimal) else Decimal(repr(float(value)) if not isinstance(value, str) else value)


@overload
def rnd(value: float | int | Decimal, ndigits: None = None) -> int: ...
@overload
def rnd(value: float | int | Decimal, ndigits: int) -> float: ...
def rnd(value, ndigits=None):
    """Zamiennik round(): ROUND_HALF_UP. Bez ndigits zwraca int, z ndigits float. NaN i nieskończoność bez zmian."""
    if isinstance(value, float) and not math.isfinite(value):
        return value
    quantum = Decimal(1).scaleb(-(ndigits or 0))
    rounded = _decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if ndigits is None else float(rounded)


def money(value: float | int | Decimal) -> float:
    """Kwota do pełnych groszy."""
    return rnd(value, MONEY_DIGITS)


def rate(value: float | int | Decimal) -> float:
    return rnd(value, RATE_DIGITS)


def coerce_money(value: Any) -> Any:
    """Walidator wejścia (przed sprawdzeniem ograniczeń): liczby zaokrągla do groszy, resztę zostawia."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    return money(number) if math.isfinite(number) else value


def coerce_rate(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    return rate(number) if math.isfinite(number) else value
