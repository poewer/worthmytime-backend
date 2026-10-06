from datetime import date

import pytest

from app.budget import BudgetPlan
from app.forecast import MIN_DAYS_FOR_PACE, MonthClock, category_forecast, forecast
from app.schemas import Category


def clock(day: int, month: int = 10) -> MonthClock:
    return MonthClock.of(date(2026, month, day))


def test_month_clock_counts_today_as_remaining_day():
    c = clock(6)
    assert (c.days_in_month, c.day_of_month, c.days_left) == (31, 6, 26)
    assert clock(31).days_left == 1
    assert MonthClock.of(date(2027, 2, 1)).days_in_month == 28
    assert c.month_end == date(2026, 10, 31)


def test_daily_limit_is_free_budget_spread_over_remaining_days():
    # FUN: budżet 1 000, wydane 200, 6. października -> zostało 800 na 26 dni
    f = category_forecast(Category.FUN, 1000, 200, 0, clock(6))
    assert f["available"] == 800
    assert f["daily_limit"] == pytest.approx(800 / 26, abs=0.01)


def test_pace_projection_and_exhaustion_date():
    # 600 zł przez 10 dni = 60 zł/dzień; budżet 1 000, wolne 400 -> starczy na 6 dni (do 16.10)
    f = category_forecast(Category.FUN, 1000, 600, 0, clock(10))
    assert f["pace_per_day"] == 60.0
    assert f["projected_total"] == 1860.0 and f["projected_usage_percent"] == 186.0
    assert f["runs_out_on"] == "2026-10-16"
    assert f["status"] == "WARN"


def test_fixed_installments_count_in_spent_but_not_in_pace():
    # Potrzeby: budżet 5 000, rata 1 000 (stała) + 900 zmiennych przez 9 dni (100 zł/dzień)
    f = category_forecast(Category.NEEDS, 5000, 900, 1000, clock(9))
    assert f["spent"] == 1900 and f["available"] == 3100
    assert f["pace_per_day"] == 100.0
    assert f["projected_total"] == 1000 + 100 * 31
    assert f["status"] == "OK"


def test_no_projection_in_first_days_but_limit_still_shown():
    f = category_forecast(Category.FUN, 1000, 300, 0, clock(MIN_DAYS_FOR_PACE - 1))
    assert f["projected_total"] is None and f["runs_out_on"] is None
    assert f["daily_limit"] > 0


def test_no_spending_means_no_warning_and_fixed_only_projection():
    f = category_forecast(Category.FUN, 1000, 0, 0, clock(2))
    assert f["projected_total"] == 0 and f["status"] == "OK" and f["runs_out_on"] is None


def test_over_budget_status_and_zero_daily_limit():
    f = category_forecast(Category.FUN, 1000, 1200, 0, clock(15))
    assert f["status"] == "OVER" and f["available"] == -200 and f["daily_limit"] == 0


def test_runs_out_only_when_within_the_month():
    # 10 zł/dzień, wolne 900, 6.10 -> 90 dni, poza bieżącym miesiącem
    f = category_forecast(Category.FUN, 1000, 100, 0, clock(10))
    assert f["pace_per_day"] == 10.0 and f["runs_out_on"] is None and f["status"] == "OK"


def test_forecast_covers_all_categories_and_uses_loans_only_for_needs():
    plan = BudgetPlan(monthly_income=10000, monthly_loans=1000, loans_count=1)
    result = forecast(plan, date(2026, 10, 6))
    by = {r["category"]: r for r in result["categories"]}
    assert set(by) == {"NEEDS", "FUTURE", "GOALS", "FUN"}
    assert by["NEEDS"]["spent"] == 1000 and by["FUN"]["spent"] == 0
    assert result["days_left"] == 26 and result["month_end"] == "2026-10-31"
