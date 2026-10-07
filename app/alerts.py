"""Centrum alertów: reguły liczone z istniejących danych (czyste funkcje, bez I/O i bez e-maili).

Każdy alert ma:
  key    stabilny identyfikator (reguła + przedmiot), służy do ukrywania
  code   reguła, po której front dobiera komunikat
  level  info | warning | critical
  state  odcisk stanu; ukryty alert wraca, gdy stan się zmieni (np. 80% -> 100%)
  params dane do komunikatu, link ekran w aplikacji
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from .budget import BudgetPlan
from .planning import next_payment_date
from .schemas import CATEGORIES

INFO, WARNING, CRITICAL = "info", "warning", "critical"
LEVEL_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}

USAGE_WARN_PERCENT = 80.0
USAGE_CRITICAL_PERCENT = 100.0
LOAN_DUE_DAYS = 3


def alert(code: str, subject: str | None, level: str, state: str, link: str, **params) -> dict:
    return {
        "key": f"{code}:{subject}" if subject else code,
        "code": code,
        "level": level,
        "state": state,
        "params": params,
        "link": link,
    }


def rule_category_usage(plan: BudgetPlan) -> list[dict]:
    """CATEGORY_USAGE: kategoria wykorzystała co najmniej 80% (ostrzeżenie) lub 100% (krytyczny) budżetu."""
    out = []
    for category in CATEGORIES:
        budget = plan.category_budget(category)
        if budget <= 0:
            continue
        used = plan.effective_spent(category)
        percent = round(used / budget * 100, 1)
        if percent < USAGE_WARN_PERCENT:
            continue
        over = percent >= USAGE_CRITICAL_PERCENT
        out.append(
            alert(
                "CATEGORY_USAGE",
                category.value,
                CRITICAL if over else WARNING,
                "100" if over else "80",
                "/budget",
                category=category.value,
                usage_percent=percent,
                budget=budget,
                spent=used,
                available=plan.available(category),
            )
        )
    return out


def rule_budget_deficit(plan: BudgetPlan) -> list[dict]:
    """BUDGET_DEFICIT: wydatki i raty razem przekraczają miesięczny dochód."""
    if plan.monthly_income <= 0 or plan.total_spent <= plan.monthly_income:
        return []
    return [
        alert(
            "BUDGET_DEFICIT",
            None,
            CRITICAL,
            "deficit",
            "/budget",
            monthly_income=plan.monthly_income,
            total_spent=plan.total_spent,
            deficit=round(plan.total_spent - plan.monthly_income, 2),
        )
    ]


@dataclass(frozen=True)
class LoanDue:
    id: str
    name: str
    installment_amount: float
    payment_day: int | None
    has_installments_left: bool


def rule_loan_due(
    loans: Iterable[LoanDue], paid: set[tuple[str, str]], today: date, within_days: int = LOAN_DUE_DAYS
) -> list[dict]:
    """LOAN_DUE: rata przypada w ciągu najbliższych dni (także dziś) i nie jest oznaczona jako opłacona.

    paid: pary (id kredytu, miesiąc terminu YYYY-MM) z wpisami o opłaconej racie.
    """
    out = []
    for loan in loans:
        if not loan.payment_day or not loan.has_installments_left:
            continue
        due = next_payment_date(today, loan.payment_day)
        days = (due - today).days
        if days > within_days or (loan.id, due.strftime("%Y-%m")) in paid:
            continue
        out.append(
            alert(
                "LOAN_DUE",
                loan.id,
                CRITICAL if days == 0 else WARNING,
                due.isoformat(),
                "/expenses",
                loan_id=loan.id,
                name=loan.name,
                amount=loan.installment_amount,
                due_date=due.isoformat(),
                days_left=days,
            )
        )
    return out


@dataclass(frozen=True)
class GoalState:
    id: str
    name: str
    completed: bool
    target_date: date | None
    on_track: bool | None
    remaining: float
    required_monthly: float | None


def rule_goal_schedule(goals: Iterable[GoalState], today: date) -> list[dict]:
    """GOAL_OVERDUE: termin minął, a cel niezrealizowany.

    GOAL_OFF_TRACK: przy obecnej wpłacie cel nie zdąży na termin.
    """
    out = []
    for g in goals:
        if g.completed or g.target_date is None:
            continue
        if g.target_date < today:
            out.append(
                alert(
                    "GOAL_OVERDUE",
                    g.id,
                    CRITICAL,
                    g.target_date.isoformat(),
                    "/goals",
                    goal_id=g.id,
                    name=g.name,
                    target_date=g.target_date.isoformat(),
                    remaining=g.remaining,
                )
            )
        elif g.on_track is False:
            out.append(
                alert(
                    "GOAL_OFF_TRACK",
                    g.id,
                    WARNING,
                    g.target_date.isoformat(),
                    "/goals",
                    goal_id=g.id,
                    name=g.name,
                    target_date=g.target_date.isoformat(),
                    remaining=g.remaining,
                    required_monthly=g.required_monthly,
                )
            )
    return out


def rule_wish_ready(wishes: Iterable[dict]) -> list[dict]:
    """WISH_READY: okres ostygnięcia minął, czas podjąć decyzję."""
    return [
        alert("WISH_READY", w["id"], INFO, "ready", "/wishlist", wish_id=w["id"], name=w["name"], price=w["price"])
        for w in wishes
        if w.get("ready")
    ]


def sort_alerts(alerts: Iterable[dict]) -> list[dict]:
    return sorted(alerts, key=lambda a: (LEVEL_ORDER[a["level"]], a["key"]))


def visible(alerts: Iterable[dict], dismissed: dict[str, str]) -> list[dict]:
    """Odfiltrowuje alerty ukryte przez użytkownika, o ile stan się nie zmienił."""
    return [a for a in alerts if dismissed.get(a["key"]) != a["state"]]
