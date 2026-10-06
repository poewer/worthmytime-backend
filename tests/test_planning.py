"""Testy jednostkowe czystych funkcji planowania i realnej stawki / kosztu na użycie."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.calc import compute, real_hourly_rate, resolve_rate
from app.planning import (
    goal_view,
    last_periods,
    month_bounds,
    monthly_summary,
    period_of,
    totals_by_category,
    wish_stats,
    wish_view,
)
from app.schemas import CalculationIn

# --- koszt na użycie ---------------------------------------------------------------------------


def test_cost_per_use_and_work_minutes_per_use():
    rate = resolve_rate(10000, None)  # 57,69 zł/h
    r = compute(CalculationIn(name="Rower", purchase_price=3000, expected_uses=300), rate)
    assert r["per_use"]["cost"] == 10.0
    assert r["per_use"]["uses"] == 300
    assert r["per_use"]["work_minutes"] == pytest.approx(10 / 57.69 * 60, abs=0.1)  # ~10,4 min


def test_per_use_for_tco_uses_total_cost_with_resale():
    calc = CalculationIn.model_validate(
        {"name": "Auto", "type": "TCO", "purchase_price": 80000, "ownership_years": 5, "resale_value": 30000,
         "expected_uses": 1000}  # fmt: skip
    )
    assert compute(calc, resolve_rate(10000, None))["per_use"]["cost"] == 50.0


def test_no_per_use_without_uses():
    assert compute(CalculationIn(name="x", purchase_price=100), resolve_rate(10000, None))["per_use"] is None


# --- realna stawka -----------------------------------------------------------------------------


def test_real_rate_is_lower_than_nominal_with_commute_and_costs():
    nominal = resolve_rate(10000, None)
    real = resolve_rate(10000, None, commute_minutes_per_day=90, work_costs_monthly=600)
    assert round(nominal.nominal_rate, 2) == 57.69
    # (10 000 - 600) / (173,33 + 1,5 h * 5 * 52/12 = 32,5 h) = 45,67
    assert round(real.real_rate, 2) == 45.67
    assert real.hourly_rate == real.nominal_rate  # tryb NOMINAL: do przeliczeń nadal stawka nominalna


def test_real_mode_changes_hours_but_income_percent_stays_on_net_income():
    nominal = compute(CalculationIn(name="x", purchase_price=2000), resolve_rate(10000, None))
    real = compute(
        CalculationIn(name="x", purchase_price=2000),
        resolve_rate(10000, None, commute_minutes_per_day=90, work_costs_monthly=600, rate_mode="REAL"),
    )
    assert real["work"]["hours"] > nominal["work"]["hours"]  # realnie ta sama kwota to więcej godzin
    assert real["work"]["income_percent"] == nominal["work"]["income_percent"] == 20.0


def test_real_rate_without_extras_equals_nominal():
    assert real_hourly_rate(10000, 173.333, 5, 0, 0) == pytest.approx(57.69, abs=0.01)


def test_real_rate_never_divides_by_zero_or_goes_negative():
    assert real_hourly_rate(500, 173.33, 5, 0, 5000) > 0


# --- miesiące i rejestr ------------------------------------------------------------------------


def test_periods():
    assert period_of(date(2026, 3, 9)) == "2026-03"
    assert month_bounds("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))
    assert last_periods(date(2026, 2, 10), 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_totals_and_monthly_summary_include_empty_months():
    assert totals_by_category([("FUN", 10.5), ("FUN", 4.5), ("NEEDS", 100)]) == {
        "NEEDS": 100.0, "FUTURE": 0.0, "GOALS": 0.0, "FUN": 15.0,
    }  # fmt: skip
    rows = [(date(2026, 10, 3), "FUN", 50.0), (date(2026, 8, 1), "NEEDS", 200.0), (date(2025, 1, 1), "FUN", 9.0)]
    out = monthly_summary(rows, ["2026-08", "2026-09", "2026-10"])
    assert [m["month"] for m in out] == ["2026-08", "2026-09", "2026-10"]
    assert out[0]["totals"]["NEEDS"] == 200.0
    assert out[1]["total"] == 0.0  # miesiąc bez wydatków
    assert out[2]["totals"]["FUN"] == 50.0  # wpis ze stycznia 2025 poza zakresem


# --- lista życzeń ------------------------------------------------------------------------------


def test_wish_view_cooldown():
    created = datetime(2026, 10, 1, tzinfo=UTC)
    work = {"hours": 10.0}
    waiting = wish_view(status="WAITING", price=500, created_at=created, cooldown_days=30,
                        now=created + timedelta(days=10), work=work)  # fmt: skip
    assert waiting["ready"] is False and waiting["days_left"] == 20
    ready = wish_view(status="WAITING", price=500, created_at=created, cooldown_days=30,
                      now=created + timedelta(days=30, hours=1), work=work)  # fmt: skip
    assert ready["ready"] is True and ready["days_left"] == 0
    decided = wish_view(status="DROPPED", price=500, created_at=created, cooldown_days=0,
                        now=created + timedelta(days=1), work=work)  # fmt: skip
    assert decided["ready"] is False  # gotowość dotyczy tylko oczekujących


def test_wish_stats_counts_savings_from_dropped_items():
    items = [
        {"status": "DROPPED", "price": 2500.0, "work": {"hours": 43.3}, "ready": False},
        {"status": "DROPPED", "price": 100.0, "work": {"hours": 1.7}, "ready": False},
        {"status": "BOUGHT", "price": 999.0, "work": {"hours": 17.3}, "ready": False},
        {"status": "WAITING", "price": 300.0, "work": {"hours": 5.2}, "ready": True},
    ]
    s = wish_stats(items)
    assert s["dropped_total"] == 2600 and s["dropped_hours"] == 45.0 and s["dropped_count"] == 2
    assert s["waiting_total"] == 300 and s["ready_count"] == 1


# --- cele oszczędnościowe ----------------------------------------------------------------------


def test_goal_progress_eta_and_required_monthly():
    g = goal_view(target_amount=5000, saved_amount=500, monthly_contribution=1000,
                  target_date=date(2027, 3, 1), today=date(2026, 10, 1), hourly_rate=50)  # fmt: skip
    assert g["remaining"] == 4500 and g["percent"] == 10.0
    assert g["months_to_goal"] == 4.5 and g["months_to_goal_full"] == 5
    assert g["eta"] == "2027-02-15"
    assert g["on_track"] is True  # 15 lutego < 1 marca
    assert g["required_monthly"] == pytest.approx(4500 / (151 / 30.4375), abs=0.01)
    assert g["work_hours_remaining"] == 90.0


def test_goal_off_track_completed_and_no_contribution():
    late = goal_view(target_amount=5000, saved_amount=0, monthly_contribution=500, target_date=date(2027, 1, 1),
                     today=date(2026, 10, 1), hourly_rate=None)  # fmt: skip
    assert late["on_track"] is False and late["work_hours_remaining"] is None
    done = goal_view(target_amount=1000, saved_amount=1200, monthly_contribution=100, target_date=None,
                     today=date(2026, 10, 1), hourly_rate=10)  # fmt: skip
    assert done["completed"] is True and done["remaining"] == 0 and done["eta"] is None
    none = goal_view(target_amount=1000, saved_amount=100, monthly_contribution=None, target_date=None,
                     today=date(2026, 10, 1), hourly_rate=None)  # fmt: skip
    assert none["months_to_goal"] is None and none["required_monthly"] is None
