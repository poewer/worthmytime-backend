import math

import pytest

from app import calc
from app.money import coerce_money, coerce_rate, money, rate, rnd
from app.schemas import CalculationIn


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [
        (2.675, 2, 2.68),  # round() daje 2.67, bo 2.675 binarnie to 2.67499...
        (1.005, 2, 1.01),  # round() daje 1.0
        (0.125, 2, 0.13),  # round() zaokrągla do parzystej: 0.12
        (0.5, 0, 1),
        (1.5, 0, 2),
        (2.5, 0, 3),  # round(2.5) == 2
        (-2.5, 0, -3),  # symetrycznie od zera
        (-2.675, 2, -2.68),
        (0.0, 2, 0.0),
        (57.69230769, 2, 57.69),
        (1_000_000_000.005, 2, 1_000_000_000.01),
        (0.004, 2, 0.0),
        (0.005, 2, 0.01),
        (12345.6789, 1, 12345.7),
        (3, 2, 3.0),
    ],
)
def test_rnd_is_round_half_up(value, digits, expected):
    assert rnd(value, digits) == expected


def test_rnd_without_digits_returns_int():
    assert isinstance(rnd(2.5), int) and rnd(2.5) == 3
    assert rnd(10.4999) == 10


def test_rnd_passes_nan_and_inf_through():
    assert math.isnan(rnd(float("nan"), 2))
    assert rnd(float("inf"), 2) == float("inf")


def test_money_and_rate_precision():
    assert money(10.005) == 10.01
    assert rate(57.692307) == 57.6923
    assert money(0.1 + 0.2) == 0.3  # klasyczny błąd binarny znika po zaokrągleniu do groszy


def test_coerce_input_rounds_numbers_and_leaves_the_rest_to_validation():
    assert coerce_money(19.999) == 20.0
    assert coerce_money("12.345") == 12.35
    assert coerce_money(None) is None
    assert coerce_money("abc") == "abc"  # nieliczbę odrzuci dopiero walidator typu
    assert coerce_money(True) is True
    assert coerce_rate(40.123456) == 40.1235


def test_input_amounts_are_rounded_to_cents_before_constraints():
    data = CalculationIn(name="x", purchase_price=19.999)
    assert data.purchase_price == 20.0


def test_large_amounts_and_tiny_rates_stay_consistent():
    rate_ = calc.WorkRate(hourly_rate=0.01, hours_per_day=8, days_per_week=5)
    big = calc.work_time(1_000_000_000, rate_)
    assert big["hours"] == 100_000_000_000.0  # 1e9 zł przy stawce 1 gr/h, bez utraty dokładności groszy
    small = calc.work_time(0.01, rate_)
    assert small["hours"] == 1.0 and small["hours_part"] == 1 and small["minutes_part"] == 0

    normal = calc.WorkRate(hourly_rate=57.69, hours_per_day=8, days_per_week=5)
    assert calc.work_time(2500, normal)["hours"] == 43.34  # 43.335065...


def test_rounding_boundaries_in_work_time_use_half_up():
    rate_ = calc.WorkRate(hourly_rate=100.0, hours_per_day=8, days_per_week=5)
    # 0.125 h -> 7,5 min: pół minuty zaokrąglamy w górę do 8
    result = calc.work_time(12.5, rate_)
    assert result["hours"] == 0.13
    assert (result["hours_part"], result["minutes_part"]) == (0, 8)
