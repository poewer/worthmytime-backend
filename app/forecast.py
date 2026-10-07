"""Dzienny limit i prognoza końca miesiąca dla kategorii budżetu (czysta logika, bez I/O).

Wynik to symulacja na dotychczasowym tempie wydatków, a nie pewna prognoza.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from .budget import BudgetPlan
from .schemas import CATEGORIES, Category

# Do tylu pierwszych dni miesiąca tempo wydatków jest zbyt zaszumione, żeby z niego prognozować.
MIN_DAYS_FOR_PACE = 3


@dataclass(frozen=True)
class MonthClock:
    today: date
    days_in_month: int
    day_of_month: int
    days_left: int  # łącznie z dzisiejszym dniem

    @classmethod
    def of(cls, today: date) -> MonthClock:
        dim = calendar.monthrange(today.year, today.month)[1]
        return cls(today=today, days_in_month=dim, day_of_month=today.day, days_left=dim - today.day + 1)

    @property
    def month_end(self) -> date:
        return self.today.replace(day=self.days_in_month)


def category_forecast(
    category: Category, budget: float, variable_spent: float, fixed: float, clock: MonthClock
) -> dict:
    """
    budget          - miesięczny budżet kategorii
    variable_spent  - wydane z rejestru w tym miesiącu (zmienne wydatki, na nich liczymy tempo)
    fixed           - stałe zobowiązania w kategorii (raty kredytów w Potrzebach), już wliczone w "wydane"
    """
    spent = round(variable_spent + fixed, 2)
    available = round(budget - spent, 2)
    daily_limit = round(max(available, 0.0) / clock.days_left, 2)

    pace = round(variable_spent / clock.day_of_month, 2) if variable_spent > 0 else 0.0
    projected_total = None
    projected_usage = None
    runs_out_on = None
    if clock.day_of_month >= MIN_DAYS_FOR_PACE or variable_spent == 0:
        projected_total = round(fixed + pace * clock.days_in_month, 2)
        projected_usage = round(projected_total / budget * 100, 1) if budget > 0 else None
        if pace > 0 and available > 0:
            days_to_zero = int(available // pace)
            exhaustion = clock.today + timedelta(days=days_to_zero)
            if exhaustion <= clock.month_end:
                runs_out_on = exhaustion.isoformat()

    if available <= 0 and spent > 0:
        status = "OVER"
    elif projected_total is not None and projected_total > budget:
        status = "WARN"
    else:
        status = "OK"

    return {
        "category": category.value,
        "budget": round(budget, 2),
        "spent": spent,
        "available": available,
        "daily_limit": daily_limit,
        "pace_per_day": pace,
        "projected_total": projected_total,
        "projected_usage_percent": projected_usage,
        "runs_out_on": runs_out_on,
        "status": status,
    }


def forecast(plan: BudgetPlan, today: date) -> dict:
    clock = MonthClock.of(today)
    rows = []
    for c in CATEGORIES:
        fixed = plan.monthly_loans if c == Category.NEEDS else 0.0
        rows.append(category_forecast(c, plan.category_budget(c), plan.spent[c], fixed, clock))
    return {
        "today": today.isoformat(),
        "days_in_month": clock.days_in_month,
        "days_left": clock.days_left,
        "month_end": clock.month_end.isoformat(),
        "categories": rows,
    }
