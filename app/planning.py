"""Czyste funkcje planowania: rejestr wydatków (miesiące), lista życzeń (ostygnięcie) i cele oszczędnościowe.

Bez I/O - łatwe do testów jednostkowych. Wyniki to symulacje na założeniach użytkownika, nie porada finansowa.
"""

from __future__ import annotations

import calendar
import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from .money import rnd
from .schemas import CATEGORIES

DAYS_PER_MONTH = 365.25 / 12


# --- miesiące i rejestr wydatków --------------------------------------------------------------


def period_of(d: date) -> str:
    """Miesiąc jako YYYY-MM."""
    return f"{d.year:04d}-{d.month:02d}"


def parse_period(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    y, m = int(year), int(month)
    if not 1 <= m <= 12:
        raise ValueError("miesiąc poza zakresem")
    return y, m


def month_bounds(period: str) -> tuple[date, date]:
    """Pierwszy dzień miesiąca i pierwszy dzień następnego (przedział półotwarty)."""
    y, m = parse_period(period)
    start = date(y, m, 1)
    return start, date(y + (m == 12), 1 if m == 12 else m + 1, 1)


def last_periods(today: date, count: int) -> list[str]:
    """Ostatnie `count` miesięcy łącznie z bieżącym, rosnąco."""
    y, m = today.year, today.month
    out = []
    for _ in range(count):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def totals_by_category(rows: Iterable[tuple[str, float]]) -> dict[str, float]:
    totals = {c.value: 0.0 for c in CATEGORIES}
    for category, amount in rows:
        totals[category] = rnd(totals.get(category, 0.0) + amount, 2)
    return totals


def monthly_summary(rows: Iterable[tuple[date, str, float]], periods: list[str]) -> list[dict]:
    """Sumy per miesiąc i kategoria; miesiące bez wydatków też są w wyniku (zera)."""
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {c.value: 0.0 for c in CATEGORIES})
    for spent_on, category, amount in rows:
        p = period_of(spent_on)
        if p in periods:
            buckets[p][category] += amount
    out = []
    for p in periods:
        totals = {k: rnd(v, 2) for k, v in buckets[p].items()} if p in buckets else {c.value: 0.0 for c in CATEGORIES}
        out.append({"month": p, "totals": totals, "total": rnd(sum(totals.values()), 2)})
    return out


# --- lista życzeń -----------------------------------------------------------------------------


def wish_view(
    *, status: str, price: float, created_at: datetime, cooldown_days: int, now: datetime, work: dict | None
) -> dict:
    ready_at = created_at + timedelta(days=cooldown_days)
    seconds_left = (ready_at - now).total_seconds()
    days_left = max(math.ceil(seconds_left / 86400), 0)
    return {
        "ready_at": ready_at.isoformat(),
        "days_left": days_left,
        "ready": status == "WAITING" and seconds_left <= 0,
        "work": work,
    }


def wish_stats(items: list[dict]) -> dict:
    """Ile pieniędzy i godzin pracy zaoszczędzono dzięki rezygnacji; ile czeka na decyzję."""
    dropped = [i for i in items if i["status"] == "DROPPED"]
    waiting = [i for i in items if i["status"] == "WAITING"]
    return {
        "dropped_count": len(dropped),
        "dropped_total": rnd(sum(i["price"] for i in dropped), 2),
        "dropped_hours": rnd(sum((i["work"] or {}).get("hours", 0.0) for i in dropped), 1),
        "waiting_count": len(waiting),
        "waiting_total": rnd(sum(i["price"] for i in waiting), 2),
        "ready_count": sum(1 for i in waiting if i["ready"]),
    }


# --- cele oszczędnościowe ---------------------------------------------------------------------


def goal_view(
    *,
    target_amount: float,
    saved_amount: float,
    monthly_contribution: float | None,
    target_date: date | None,
    today: date,
    hourly_rate: float | None,
) -> dict:
    remaining = rnd(max(target_amount - saved_amount, 0.0), 2)
    percent = rnd(saved_amount / target_amount * 100, 1)
    months_to_goal = rnd(remaining / monthly_contribution, 1) if monthly_contribution and remaining > 0 else None
    eta = today + timedelta(days=rnd(months_to_goal * DAYS_PER_MONTH)) if months_to_goal is not None else None

    required_monthly = None
    on_track = None
    if target_date and remaining > 0:
        months_left = max((target_date - today).days / DAYS_PER_MONTH, 1.0)
        required_monthly = rnd(remaining / months_left, 2)
        if eta is not None:
            on_track = eta <= target_date

    return {
        "remaining": remaining,
        "percent": percent,
        "completed": remaining == 0,
        "months_to_goal": months_to_goal,
        "months_to_goal_full": (
            math.ceil(remaining / monthly_contribution) if monthly_contribution and remaining else None
        ),
        "eta": eta.isoformat() if eta else None,
        "required_monthly": required_monthly,
        "on_track": on_track,
        "work_hours_remaining": rnd(remaining / hourly_rate, 1) if hourly_rate else None,
    }


# --- terminy spłat kredytów -------------------------------------------------------------------


def _month_date(year: int, month: int, day: int) -> date:
    """Dzień miesiąca z przycięciem do jego długości (termin 31. w lutym wypada 28./29.)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_months(d: date, months: int, day: int | None = None) -> date:
    index = d.year * 12 + (d.month - 1) + months
    return _month_date(index // 12, index % 12 + 1, day if day is not None else d.day)


def next_payment_date(today: date, payment_day: int) -> date:
    """Najbliższy termin raty w dniu `payment_day`, liczony od dziś włącznie."""
    this_month = _month_date(today.year, today.month, payment_day)
    return this_month if this_month >= today else add_months(today, 1, payment_day)


def remaining_installments(
    today: date, installments_left: int | None, end_date: date | None, payment_day: int | None
) -> int:
    """Ile rat zostało. Przy podanej dacie końca liczymy terminy do niej, więc liczba maleje sama z czasem."""
    if end_date is None:
        return installments_left or 0
    if end_date < today:
        return 0
    day = payment_day or end_date.day
    count, due = 0, next_payment_date(today, day)
    while due <= end_date:
        count += 1
        due = add_months(due, 1, day)
    return count


def last_payment_date(today: date, remaining: int, payment_day: int | None, end_date: date | None) -> date | None:
    """Data ostatniej raty: koniec okresu spłaty albo najbliższy termin + (pozostałe raty - 1) miesięcy."""
    if remaining <= 0:
        return None
    if end_date is not None:
        return end_date
    day = payment_day or today.day
    return add_months(next_payment_date(today, day), remaining - 1, day)


def repayment_progress(start_date: date | None, end_date: date | None, today: date) -> float | None:
    """Jaka część okresu spłaty (od - do) już minęła, w procentach."""
    if not start_date or not end_date or end_date <= start_date:
        return None
    done = (min(max(today, start_date), end_date) - start_date).days
    return rnd(done / (end_date - start_date).days * 100, 1)