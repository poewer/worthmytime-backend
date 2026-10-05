from app.calc import WorkRate, compute, resolve_rate, work_time
from app.schemas import CalculationIn


def rate():
    return resolve_rate(7000, None)


def test_hourly_rate_from_income():
    assert round(rate().hourly_rate, 2) == 41.67
    assert rate().hours_per_month == 168


def test_simple_purchase():
    r = compute(CalculationIn(name="iPhone", purchase_price=5299, ownership_years=3), rate())
    assert round(r["work"]["hours"]) == 127
    assert r["work"]["working_days"] == 15.9
    assert r["work"]["working_weeks"] == 3.18
    assert r["work"]["working_months"] == 0.76
    assert r["work"]["income_percent"] == 75.7
    assert r["life_cost"]["per_day"] == 4.84
    assert round(r["life_cost"]["per_month"]) == 147


def test_tco_car():
    r = compute(
        CalculationIn.model_validate(
            {
                "name": "Car",
                "type": "TCO",
                "purchase_price": 80000,
                "ownership_years": 5,
                "costs": [
                    {"name": "fuel", "amount": 700, "frequency": "MONTHLY"},
                    {"name": "insurance", "amount": 3000, "frequency": "YEARLY"},
                    {"name": "service", "amount": 2000, "frequency": "YEARLY"},
                    {"name": "other", "amount": 100, "frequency": "MONTHLY"},
                ],
            }
        ),
        rate(),
    )
    assert r["total_cost"] == 153000
    assert round(r["work"]["hours"]) == 3672
    assert round(r["work"]["working_days"]) == 459
    assert r["work"]["working_years"] == 1.82


def test_recurring():
    r = compute(
        CalculationIn.model_validate(
            {"name": "Netflix", "type": "RECURRING", "costs": [{"name": "sub", "amount": 49, "frequency": "MONTHLY"}]}
        ),
        rate(),
    )
    by_label = {h["label"]: h for h in r["horizons"]}
    assert by_label["1 year"]["cost"] == 588
    assert (by_label["1 year"]["work"]["hours_part"], by_label["1 year"]["work"]["minutes_part"]) == (14, 7)
    assert by_label["10 years"]["work"]["working_days"] == 17.64


def test_income_percent_matches_months_and_hourly_rate_input():
    # stawka podana wprost: miesięczny odpowiednik = stawka * 168 h
    r = compute(CalculationIn(name="x", purchase_price=4200), resolve_rate(None, 25))
    assert r["work"]["working_months"] == 1.0
    assert r["work"]["income_percent"] == 100.0


def test_resale_reduces_total():
    r = compute(CalculationIn(name="x", type="TCO", purchase_price=1000, ownership_years=1, resale_value=400), rate())
    assert r["total_cost"] == 600


def test_work_time_rounding():
    assert work_time(49, WorkRate(41.67))["minutes_part"] == 11
