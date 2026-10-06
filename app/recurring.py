"""Stałe wydatki: wyliczanie terminów płatności (czyste funkcje, bez I/O)."""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date

MAX_BACKFILL_MONTHS = 36  # ile miesięcy wstecz maksymalnie dopisujemy za jednym razem


def due_date(year: int, month: int, day_of_month: int) -> date:
    """Termin w danym miesiącu; dzień 31 w krótszym miesiącu wypada w jego ostatnim dniu."""
    return date(year, month, min(day_of_month, calendar.monthrange(year, month)[1]))


def due_dates(
    day_of_month: int,
    start_date: date,
    generated_through: date | None,
    today: date,
) -> Iterator[date]:
    """Terminy płatności do dopisania: od start_date, po generated_through, nie później niż dziś.

    Wynik jest rosnący i nigdy nie obejmuje przyszłości, więc wielokrotne wywołanie
    (po przesunięciu generated_through na dziś) nie tworzy duplikatów.
    """
    first_month = max(start_date, date(today.year - MAX_BACKFILL_MONTHS // 12, today.month, 1))
    year, month = first_month.year, first_month.month
    while (year, month) <= (today.year, today.month):
        due = due_date(year, month, day_of_month)
        if due >= start_date and due <= today and (generated_through is None or due > generated_through):
            yield due
        month += 1
        if month > 12:
            year, month = year + 1, 1
