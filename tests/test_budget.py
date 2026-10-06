"""Testy jednostkowe analizy budżetowej - przykłady z WorthMyTime_Budget_Model.md."""

import pytest

from app.budget import BudgetPlan, analyze, loan_view, months_to_goal, rule_budget_deficit, rule_category_tight
from app.schemas import BudgetIn, CalculationIn, Category

INCOME = 10_000.0


def plan(spent_fun: float = 0.0, custom: bool = True, **spent) -> BudgetPlan:
    s = {Category.NEEDS: 0.0, Category.FUTURE: 0.0, Category.GOALS: 0.0, Category.FUN: spent_fun}
    s.update({Category[k.upper()]: v for k, v in spent.items()})
    return BudgetPlan(monthly_income=INCOME, spent=s, is_custom=custom)


def calc(price: float, category: str | None = "FUN", **kw) -> CalculationIn:
    return CalculationIn(name="x", purchase_price=price, category=category, **kw)


def codes(result: dict) -> list[str]:
    return [w["code"] for w in result["warnings"]]


def test_category_budgets_from_default_split():
    p = plan()
    assert {c.value: p.category_budget(c) for c in Category} == {
        "NEEDS": 5000, "FUTURE": 2500, "GOALS": 1500, "FUN": 1000,
    }  # fmt: skip


def test_section_10_example_fun_400_spent_purchase_500():
    r = analyze(calc(500), plan(spent_fun=400))
    assert r["available"] == 600
    assert r["upfront"]["projected_spent"] == 900
    assert r["upfront"]["projected_usage_percent"] == 90.0
    assert r["upfront"]["coverage_ratio"] == pytest.approx(83.3, abs=0.05)
    assert r["fits_budget"] is True
    assert "CATEGORY_BUDGET_TIGHT" in codes(r)  # 90% >= 80%
    assert "CATEGORY_BUDGET_EXCEEDED" not in codes(r)


def test_section_24_playstation_exceeds_fun():
    r = analyze(calc(2500), plan())
    assert r["category_budget"] == 1000
    assert r["upfront"]["purchase_share_percent"] == 250.0  # 250% miesięcznego FUN
    assert r["upfront"]["income_percent"] == 25.0
    assert r["upfront"]["months_to_goal"] == 2.5
    assert r["fits_budget"] is False
    c = codes(r)
    assert "CATEGORY_BUDGET_EXCEEDED" in c
    assert "HIGHER_PRIORITY_AT_RISK" in c  # FUN to P4 - sięgnęłoby po wyższe priorytety
    exceeded = next(w for w in r["warnings"] if w["code"] == "CATEGORY_BUDGET_EXCEEDED")
    assert exceeded["params"]["overrun"] == 1500
    assert exceeded["level"] == "warning"


def test_exceeding_needs_is_critical_and_has_no_higher_priority_warning():
    r = analyze(calc(6000, "NEEDS"), plan())
    exceeded = next(w for w in r["warnings"] if w["code"] == "CATEGORY_BUDGET_EXCEEDED")
    assert exceeded["level"] == "critical"
    assert "HIGHER_PRIORITY_AT_RISK" not in codes(r)  # NEEDS to już P0


def test_months_to_goal_section_11_example():
    assert months_to_goal(5000 - 500, 1000) == 4.5
    r = analyze(calc(5000, "GOALS", already_saved=500, monthly_contribution=1000), plan())
    assert r["upfront"]["months_to_goal"] == 4.5
    assert r["upfront"]["months_to_goal_full"] == 5  # UI: około 5 miesięcy
    assert months_to_goal(100, 0) is None


def test_budget_deficit_rule():
    # wydatki 9 500 + zakup 800 > dochód 10 000
    r = analyze(calc(800), plan(spent_fun=0, needs=5000, future=2500, goals=2000))
    deficit = next(w for w in r["warnings"] if w["code"] == "BUDGET_DEFICIT")
    assert deficit["params"]["deficit"] == 300
    assert rule_budget_deficit(plan(needs=1000), 100, 0) is None


def test_recurring_cost_checked_against_monthly_available():
    rec = CalculationIn.model_validate(
        {"name": "sub", "type": "RECURRING", "category": "FUN",
         "costs": [{"name": "s", "amount": 1200, "frequency": "MONTHLY"}]}  # fmt: skip
    )
    r = analyze(rec, plan(spent_fun=100))
    assert r["upfront"] is None
    assert r["monthly"]["cost"] == 1200
    assert "MONTHLY_COST_EXCEEDS_AVAILABLE" in codes(r)
    assert r["fits_budget"] is False


def test_yearly_cost_is_normalized_to_monthly():
    rec = CalculationIn.model_validate(
        {"name": "ins", "type": "RECURRING", "category": "NEEDS",
         "costs": [{"name": "i", "amount": 1200, "frequency": "YEARLY"}]}  # fmt: skip
    )
    assert analyze(rec, plan())["monthly"]["cost"] == 100


def test_no_category_means_no_analysis():
    assert analyze(calc(100, None), plan()) is None


def test_default_budget_adds_info_warning():
    assert "NO_BUDGET_DATA" in codes(analyze(calc(10), plan(custom=False)))
    assert "NO_BUDGET_DATA" not in codes(analyze(calc(10), plan(custom=True)))


def test_tight_rule_is_silent_below_threshold():
    assert rule_category_tight(Category.FUN, 1000, 0, 500, 0) is None
    assert rule_category_tight(Category.FUN, 1000, 0, 850, 0)["code"] == "CATEGORY_BUDGET_TIGHT"


def test_zero_percent_category_is_always_exceeded():
    pct = {Category.NEEDS: 60, Category.FUTURE: 25, Category.GOALS: 15, Category.FUN: 0}
    p = BudgetPlan(monthly_income=INCOME, percentages=pct, spent={c: 0.0 for c in Category}, is_custom=True)
    r = analyze(calc(50), p)
    assert "CATEGORY_BUDGET_EXCEEDED" in codes(r)
    assert r["upfront"]["projected_usage_percent"] is None  # brak budżetu -> brak procentu


def test_budget_in_requires_sum_100():
    assert BudgetIn().percentages[Category.FUN] == 10
    with pytest.raises(ValueError):
        BudgetIn(percentages={"NEEDS": 60, "FUTURE": 25, "GOALS": 15, "FUN": 10})


def loan_plan(monthly_loans: float, count: int = 1, last: int = 24, **spent) -> BudgetPlan:
    base = plan(**spent)
    return BudgetPlan(
        monthly_income=INCOME,
        spent=base.spent,
        is_custom=True,
        monthly_loans=monthly_loans,
        loans_count=count,
        last_installment_in_months=last,
    )


def test_loan_installments_reduce_needs_budget():
    p = loan_plan(1200, needs=2000)
    assert p.effective_spent(Category.NEEDS) == 3200
    assert p.available(Category.NEEDS) == 1800  # 5 000 - 2 000 - 1 200
    assert p.effective_spent(Category.FUN) == 0  # raty nie wpływają na inne kategorie
    assert p.total_spent == 3200


def test_needs_purchase_sees_loans_and_reports_obligations():
    r = analyze(calc(2000, "NEEDS"), loan_plan(1200, needs=2000))
    assert r["spent"] == 3200 and r["available"] == 1800
    assert r["upfront"]["projected_spent"] == 5200  # ponad budżet 5 000
    assert "CATEGORY_BUDGET_EXCEEDED" in codes(r)
    assert r["obligations"] == {
        "monthly_installments": 1200,
        "loans_count": 1,
        "income_percent": 12.0,
        "last_installment_in_months": 24,
        "included_in_category": True,
    }


def test_fun_purchase_not_charged_for_loans_but_deficit_counts_them():
    # NEEDS 5 000 + FUTURE 2 500 + GOALS 1 500 = 9 000 + raty 800 = 9 800; zakup 500 -> 10 300 > 10 000
    r = analyze(calc(500), loan_plan(800, needs=5000, future=2500, goals=1500))
    assert r["spent"] == 0 and r["obligations"]["included_in_category"] is False
    assert next(w for w in r["warnings"] if w["code"] == "BUDGET_DEFICIT")["params"]["deficit"] == 300


def test_loans_exceed_needs_budget_rule():
    r = analyze(calc(10), loan_plan(5500))
    w = next(w for w in r["warnings"] if w["code"] == "LOANS_EXCEED_NEEDS_BUDGET")
    assert w["level"] == "critical" and w["params"]["overrun"] == 500
    assert "LOANS_EXCEED_NEEDS_BUDGET" not in codes(analyze(calc(10), loan_plan(4000)))


def test_no_obligations_block_without_loans():
    assert analyze(calc(10), plan())["obligations"] is None


def test_manual_spent_expires_after_month_change():
    from app.helpers import manual_spent, plan_from_row
    from app.models import Budget

    row = Budget(
        user_id="u", spent_fun=300.0, spent_needs=0.0, spent_future=0.0, spent_goals=0.0, spent_period="2026-09"
    )
    row.pct_needs, row.pct_future, row.pct_goals, row.pct_fun = 50.0, 25.0, 15.0, 10.0
    assert manual_spent(row, "2026-09")[Category.FUN] == 300.0
    assert manual_spent(row, "2026-10")[Category.FUN] == 0.0  # nowy miesiąc: ręczna kwota wygasa
    assert manual_spent(row, None)[Category.FUN] == 300.0
    row.spent_period = None  # stare wiersze sprzed rejestru nie tracą kwot
    assert manual_spent(row, "2026-10")[Category.FUN] == 300.0

    p = plan_from_row(row, 10000.0, ledger={"FUN": 150.0}, period="2026-10")
    assert p.spent[Category.FUN] == 450.0  # 300 ręcznie (okres null) + 150 z rejestru


def test_loan_view_derived_values():
    v = loan_view("Kredyt", 800, 36, 40000, plan(), hourly_rate=50)
    assert v["remaining_to_pay"] == 28800
    assert v["income_percent"] == 8.0
    assert v["remaining_work_hours"] == 576.0
    assert loan_view("x", 100, 1, None, plan(), None)["remaining_work_hours"] is None