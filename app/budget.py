"""Analiza budżetowa zakupu (WorthMyTime_Budget_Model.md, sekcje 7, 10, 11, 13, 15, 16).

Czysty moduł bez I/O. Zwraca same fakty (kwoty, procenty) oraz ostrzeżenia jako kody z parametrami.
Każda reguła ostrzeżeń to osobna, jawna funkcja - łatwa do testów jednostkowych (sekcja 15).
Wyniki wynikają z założeń użytkownika (procenty i wydatki) i nie są poradą finansową.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from .calc import OCCURRENCES_PER_YEAR
from .planning import last_payment_date, next_payment_date, remaining_installments, repayment_progress
from .schemas import CATEGORIES, DEFAULT_PERCENTAGES, CalculationIn, Category, Frequency

# Hierarchia priorytetów (sekcja 8): P0 > P1 > P2 > P3 > P4
PRIORITY = {Category.NEEDS: "P0", Category.FUTURE: "P2", Category.GOALS: "P3", Category.FUN: "P4"}
# Przekroczenie kategorii o niższym priorytecie ma kosztować wyższe (sekcja 26, zasada 4)
LOW_PRIORITY = {Category.GOALS, Category.FUN}

TIGHT_USAGE_PERCENT = 80.0

CRITICAL, WARNING, INFO = "critical", "warning", "info"


@dataclass(frozen=True)
class BudgetPlan:
    monthly_income: float
    percentages: dict[Category, float] = field(default_factory=lambda: dict(DEFAULT_PERCENTAGES))
    spent: dict[Category, float] = field(default_factory=lambda: {c: 0.0 for c in CATEGORIES})
    # False = użytkownik nie ustawił budżetu; liczymy z domyślnego 50/25/15/10 i wydatków 0
    is_custom: bool = False
    # suma miesięcznych rat kredytów i pożyczek - wymagalne zobowiązania liczone w NEEDS (P0)
    monthly_loans: float = 0.0
    loans_count: int = 0
    last_installment_in_months: int = 0

    def effective_spent(self, category: Category) -> float:
        extra = self.monthly_loans if category == Category.NEEDS else 0.0
        return round(self.spent[category] + extra, 2)

    def category_budget(self, category: Category) -> float:
        return round(self.monthly_income * self.percentages[category] / 100, 2)

    def available(self, category: Category) -> float:
        return round(self.category_budget(category) - self.effective_spent(category), 2)

    @property
    def total_spent(self) -> float:
        return round(sum(self.spent.values()) + self.monthly_loans, 2)


@dataclass(frozen=True)
class Costs:
    """Koszt zakupu rozbity na część jednorazową i miesięczną (budżet jest miesięczny)."""

    upfront: float
    monthly: float


def split_costs(calc: CalculationIn) -> Costs:
    upfront = calc.purchase_price
    monthly = 0.0
    for c in calc.costs:
        if c.frequency == Frequency.ONE_TIME:
            upfront += c.amount
        else:
            monthly += c.amount * OCCURRENCES_PER_YEAR[c.frequency] / 12
    return Costs(round(upfront, 2), round(monthly, 2))


def _pct(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 1) if whole > 0 else None


# --- reguły ostrzeżeń -------------------------------------------------------------------------


def warning(code: str, level: str, **params) -> dict:
    return {"code": code, "level": level, "params": params}


def rule_upfront_exceeds_category(category: Category, budget: float, spent: float, upfront: float) -> dict | None:
    """CATEGORY_BUDGET_EXCEEDED: po zakupie wydatki w kategorii przekroczą jej miesięczny budżet."""
    projected = spent + upfront
    if upfront <= 0 or projected <= budget:
        return None
    level = WARNING if category in LOW_PRIORITY else CRITICAL
    return warning(
        "CATEGORY_BUDGET_EXCEEDED",
        level,
        category=category.value,
        overrun=round(projected - budget, 2),
        projected_usage_percent=_pct(projected, budget),
        available=round(budget - spent, 2),
    )


def rule_monthly_exceeds_category(category: Category, budget: float, spent: float, monthly: float) -> dict | None:
    """MONTHLY_COST_EXCEEDS_AVAILABLE: stała miesięczna opłata nie mieści się w dostępnym budżecie."""
    if monthly <= 0 or spent + monthly <= budget:
        return None
    level = WARNING if category in LOW_PRIORITY else CRITICAL
    return warning(
        "MONTHLY_COST_EXCEEDS_AVAILABLE",
        level,
        category=category.value,
        monthly_cost=monthly,
        available=round(budget - spent, 2),
        overrun=round(spent + monthly - budget, 2),
    )


def rule_category_tight(category: Category, budget: float, spent: float, upfront: float, monthly: float) -> dict | None:
    """CATEGORY_BUDGET_TIGHT: mieści się, ale zajmie większość budżetu kategorii."""
    projected = spent + upfront + monthly
    if (upfront <= 0 and monthly <= 0) or budget <= 0 or projected > budget:
        return None
    usage = projected / budget * 100
    if usage < TIGHT_USAGE_PERCENT:
        return None
    return warning("CATEGORY_BUDGET_TIGHT", INFO, category=category.value, projected_usage_percent=round(usage, 1))


def rule_budget_deficit(plan: BudgetPlan, upfront: float, monthly: float) -> dict | None:
    """BUDGET_DEFICIT: suma planowanych wydatków (z tym zakupem) przekracza miesięczny dochód."""
    planned = plan.total_spent + upfront + monthly
    if planned <= plan.monthly_income:
        return None
    return warning(
        "BUDGET_DEFICIT",
        CRITICAL,
        deficit=round(planned - plan.monthly_income, 2),
        planned_expenses=round(planned, 2),
        monthly_income=round(plan.monthly_income, 2),
    )


def rule_higher_priority_at_risk(category: Category, exceeded: list[dict]) -> dict | None:
    """HIGHER_PRIORITY_AT_RISK: przekroczenie P3/P4 oznacza sięgnięcie po środki z wyższych priorytetów."""
    if category not in LOW_PRIORITY or not exceeded:
        return None
    shortfall = max(w["params"]["overrun"] for w in exceeded)
    return warning(
        "HIGHER_PRIORITY_AT_RISK", WARNING, category=category.value, priority=PRIORITY[category], shortfall=shortfall
    )


def rule_loans_exceed_needs(plan: BudgetPlan) -> dict | None:
    """LOANS_EXCEED_NEEDS_BUDGET: same raty kredytów i pożyczek przekraczają budżet kategorii NEEDS."""
    needs_budget = plan.category_budget(Category.NEEDS)
    if plan.monthly_loans <= 0 or plan.monthly_loans <= needs_budget:
        return None
    return warning(
        "LOANS_EXCEED_NEEDS_BUDGET",
        CRITICAL,
        monthly_loans=round(plan.monthly_loans, 2),
        needs_budget=needs_budget,
        overrun=round(plan.monthly_loans - needs_budget, 2),
    )


def rule_contribution_exceeds_available(
    category: Category, planned: float | None, available: float
) -> dict | None:
    """CONTRIBUTION_EXCEEDS_AVAILABLE: planowana miesięczna wpłata jest większa niż wolne środki kategorii."""
    maximum = max(available, 0.0)
    if planned is None or planned <= maximum:
        return None
    level = WARNING if category in LOW_PRIORITY else CRITICAL
    return warning(
        "CONTRIBUTION_EXCEEDS_AVAILABLE",
        level,
        category=category.value,
        planned=round(planned, 2),
        max_monthly=round(maximum, 2),
        overrun=round(planned - maximum, 2),
    )


def rule_no_free_budget(category: Category, available: float, has_goal: bool) -> dict | None:
    """NO_FREE_BUDGET: w kategorii nie zostało nic wolnego, więc nie ma z czego odkładać w tym miesiącu."""
    if not has_goal or available > 0:
        return None
    return warning("NO_FREE_BUDGET", WARNING, category=category.value, available=round(available, 2))


def rule_no_budget_data(plan: BudgetPlan) -> dict | None:
    """NO_BUDGET_DATA: użytkownik nie ustawił budżetu - wynik opiera się na założeniach domyślnych."""
    return None if plan.is_custom else warning("NO_BUDGET_DATA", INFO)


# --- analiza ----------------------------------------------------------------------------------


def loan_view(
    name: str,
    installment: float,
    left: int,
    loan_amount: float | None,
    plan: BudgetPlan,
    hourly_rate: float | None,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    payment_day: int | None = None,
    today: date | None = None,
) -> dict:
    """Pochodne dla jednego kredytu: ile jeszcze do spłaty, kiedy koniec, jaki udział w dochodzie i w czasie pracy.

    Z datą końca spłaty liczba rat jest wyliczana na dziś, więc maleje sama z upływem czasu.
    """
    now = today or date.today()
    left = remaining_installments(now, left, end_date, payment_day)
    remaining = round(installment * left, 2)
    due_day = payment_day or (end_date.day if end_date else now.day)
    next_due = next_payment_date(now, due_day) if left > 0 else None
    last_due = last_payment_date(now, left, payment_day, end_date)
    return {
        "name": name,
        "installment_amount": installment,
        "installments_left": left,
        "loan_amount": loan_amount,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "payment_day": payment_day,
        "finished": left == 0,
        "next_payment_date": next_due.isoformat() if next_due else None,
        "days_to_next_payment": (next_due - now).days if next_due else None,
        "last_payment_date": last_due.isoformat() if last_due else None,
        "repayment_progress_percent": repayment_progress(start_date, end_date, now),
        "remaining_to_pay": remaining,
        "income_percent": _pct(installment, plan.monthly_income),
        "remaining_work_hours": round(remaining / hourly_rate, 1) if hourly_rate else None,
    }


def months_to_goal(remaining: float, contribution: float) -> float | None:
    """Sekcja 11: (cena - odłożone) / miesięczna wpłata."""
    if contribution <= 0:
        return None
    return round(max(0.0, remaining) / contribution, 1)


def analyze(calc: CalculationIn, plan: BudgetPlan) -> dict | None:
    """Wpływ zakupu na budżet jego kategorii. Zwraca None, gdy kategoria nie została wybrana."""
    category = calc.category
    if category is None:
        return None

    costs = split_costs(calc)
    budget = plan.category_budget(category)
    spent = plan.effective_spent(category)  # dla NEEDS razem z ratami kredytów
    available = round(budget - spent, 2)

    result: dict = {
        "category": category.value,
        "priority": PRIORITY[category],
        "percentage": plan.percentages[category],
        "category_budget": budget,
        "spent": spent,
        "available": available,
        "usage_percent": _pct(spent, budget),
        "is_custom": plan.is_custom,
        "obligations": {
            "monthly_installments": round(plan.monthly_loans, 2),
            "loans_count": plan.loans_count,
            "income_percent": _pct(plan.monthly_loans, plan.monthly_income),
            "last_installment_in_months": plan.last_installment_in_months,
            "included_in_category": category == Category.NEEDS,
        }
        if plan.loans_count
        else None,
        "upfront": None,
        "monthly": None,
    }

    if costs.upfront > 0:
        projected = round(spent + costs.upfront, 2)
        # ile maksymalnie można miesięcznie przeznaczyć na ten wydatek: wolne środki kategorii w tym miesiącu
        max_monthly = round(max(available, 0.0), 2)
        planned = calc.monthly_contribution  # plan użytkownika; bez niego zakładamy maksimum
        contribution = planned if planned is not None else max_monthly
        result["upfront"] = {
            "cost": costs.upfront,
            "projected_spent": projected,
            "projected_usage_percent": _pct(projected, budget),
            "purchase_share_percent": _pct(costs.upfront, budget),  # np. 250% miesięcznego FUN
            "coverage_ratio": _pct(costs.upfront, available) if available > 0 else None,
            "months_to_goal": months_to_goal(costs.upfront - calc.already_saved, contribution),
            "months_to_goal_full": math.ceil(max(0.0, costs.upfront - calc.already_saved) / contribution)
            if contribution > 0
            else None,
            "monthly_contribution": round(contribution, 2),
            "max_monthly_contribution": max_monthly,
            "contribution_source": "USER" if planned is not None else "CATEGORY_AVAILABLE",
            "already_saved": calc.already_saved,
            "income_percent": _pct(costs.upfront, plan.monthly_income),
        }

    if costs.monthly > 0:
        result["monthly"] = {
            "cost": costs.monthly,
            "projected_spent": round(spent + costs.monthly, 2),
            "projected_usage_percent": _pct(spent + costs.monthly, budget),
            "share_percent": _pct(costs.monthly, budget),
            "income_percent": _pct(costs.monthly, plan.monthly_income),
        }

    # Z planem odkładania (miesięczna wpłata) liczy się wpłata względem wolnych środków kategorii,
    # a nie cały zakup naraz; bez planu sprawdzamy zakup jednorazowy.
    saving_over_time = costs.upfront > 0 and calc.monthly_contribution is not None
    exceeded = [
        w
        for w in (
            rule_contribution_exceeds_available(category, calc.monthly_contribution, available)
            if saving_over_time
            else rule_upfront_exceeds_category(category, budget, spent, costs.upfront),
            rule_monthly_exceeds_category(category, budget, spent, costs.monthly),
        )
        if w
    ]
    warnings = [
        *exceeded,
        rule_higher_priority_at_risk(category, exceeded),
        rule_budget_deficit(plan, costs.upfront, costs.monthly),
        rule_loans_exceed_needs(plan),
        rule_no_free_budget(category, available, saving_over_time or costs.upfront > 0),
        None if exceeded else rule_category_tight(category, budget, spent, costs.upfront, costs.monthly),
        rule_no_budget_data(plan),
    ]
    result["warnings"] = [w for w in warnings if w]
    result["fits_budget"] = not exceeded
    return result
