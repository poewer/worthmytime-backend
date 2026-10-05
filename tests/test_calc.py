from app.calc import WorkRate, compute, resolve_rate, work_time
from app.schemas import CalculationIn


def rate():
    return resolve_rate(7000, None)


def test_hourly_rate_from_income():
    # 8 h * 5 dni * 52 / 12 = 173,33 h/mies. (Budget Model, sekcja 3), a nie 168
    assert round(rate().hours_per_month, 2) == 173.33
    assert round(rate().hourly_rate, 2) == 40.38
    assert round(resolve_rate(10000, None).hourly_rate, 2) == 57.69  # przykład z dokumentu


def test_simple_purchase():
    r = compute(CalculationIn(name="iPhone", purchase_price=5299, ownership_years=3), rate())
    assert round(r["work"]["hours"]) == 131
    assert r["work"]["working_days"] == 16.4
    assert r["work"]["working_weeks"] == 3.28
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
    assert round(r["work"]["hours"]) == 3789
    assert round(r["work"]["working_days"]) == 474
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
    assert (by_label["1 year"]["work"]["hours_part"], by_label["1 year"]["work"]["minutes_part"]) == (14, 34)
    assert by_label["10 years"]["work"]["working_days"] == 18.2
    # nagłówek wyniku to koszt miesiąca, a nie 10 lat
    assert r["total_cost"] == 49
    assert r["work"]["income_percent"] == 0.7
    assert by_label["10 years"]["work"]["income_percent"] == 84.0


def test_income_percent_matches_months_and_hourly_rate_input():
    # stawka podana wprost: miesięczny odpowiednik = stawka * 173,33 h
    r = compute(CalculationIn(name="x", purchase_price=4333.33), resolve_rate(None, 25))
    assert r["work"]["working_months"] == 1.0
    assert r["work"]["income_percent"] == 100.0


def test_resale_reduces_total():
    r = compute(CalculationIn(name="x", type="TCO", purchase_price=1000, ownership_years=1, resale_value=400), rate())
    assert r["total_cost"] == 600


def test_work_time_rounding():
    assert work_time(49, WorkRate(41.67))["minutes_part"] == 11
