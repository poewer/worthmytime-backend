"""Czysty silnik obliczeń (bez I/O) - serce produktu.

Konwencje (zgodne z dokumentem MVP):
- miesiąc roboczy = hours_per_day * days_per_week * 4.2  (8h * 5d -> 168 h)
- rok roboczy     = days_per_week * 4.2 * 12             (5d -> 252 dni)
"""

from dataclasses import dataclass

from .schemas import CalcType, CalculationIn, Frequency

WEEKS_PER_MONTH = 4.2
OCCURRENCES_PER_YEAR = {
    Frequency.DAILY: 365,
    Frequency.WEEKLY: 52,
    Frequency.MONTHLY: 12,
    Frequency.YEARLY: 1,
}
RECURRING_HORIZONS = [("1 month", 1 / 12), ("1 year", 1), ("5 years", 5), ("10 years", 10)]


@dataclass(frozen=True)
class WorkRate:
    hourly_rate: float
    hours_per_day: float = 8.0
    days_per_week: float = 5.0

    @property
    def hours_per_month(self) -> float:
        return self.hours_per_day * self.days_per_week * WEEKS_PER_MONTH

    @property
    def working_days_per_year(self) -> float:
        return self.days_per_week * WEEKS_PER_MONTH * 12


def resolve_rate(
    monthly_income: float | None,
    hourly_rate: float | None,
    hours_per_day: float = 8.0,
    days_per_week: float = 5.0,
) -> WorkRate:
    """Bezpośrednia stawka ma pierwszeństwo; w przeciwnym razie z dochodu."""
    base = WorkRate(1.0, hours_per_day, days_per_week)
    if hourly_rate is not None:
        rate = hourly_rate
    elif monthly_income is not None:
        rate = monthly_income / base.hours_per_month
    else:
        raise ValueError("Brak dochodu i stawki godzinowej")
    return WorkRate(rate, hours_per_day, days_per_week)


def cost_over_years(amount: float, frequency: Frequency, years: float) -> float:
    if frequency == Frequency.ONE_TIME:
        return amount
    return amount * OCCURRENCES_PER_YEAR[frequency] * years


def work_time(money: float, rate: WorkRate) -> dict:
    hours = money / rate.hourly_rate
    days = hours / rate.hours_per_day
    weeks = days / rate.days_per_week
    years = days / rate.working_days_per_year
    months = hours / rate.hours_per_month
    total_minutes = round(hours * 60)
    sign = -1 if total_minutes < 0 else 1
    h, m = divmod(abs(total_minutes), 60)
    return {
        "hours": round(hours, 2),
        "hours_part": sign * h,
        "minutes_part": m,
        "working_days": round(days, 2),
        "working_weeks": round(weeks, 2),
        "working_months": round(months, 2),
        "working_years": round(years, 2),
        # jaką część miesięcznej wypłaty pochłania wydatek (100 = cała wypłata)
        "income_percent": round(months * 100, 1),
    }


def _life_cost(total: float, years: float) -> dict:
    return {
        "years": years,
        "per_day": round(total / (years * 365), 2),
        "per_week": round(total / (years * 365 / 7), 2),
        "per_month": round(total / (years * 12), 2),
    }


def compute(calc: CalculationIn, rate: WorkRate) -> dict:
    if calc.type == CalcType.RECURRING:
        return _compute_recurring(calc, rate)

    years = calc.ownership_years
    lines = []
    if calc.purchase_price:
        lines.append({"name": "Purchase", "amount": calc.purchase_price})
    if calc.type == CalcType.TCO or years:
        for c in calc.costs:
            lines.append(
                {
                    "name": c.name,
                    "amount": round(cost_over_years(c.amount, c.frequency, years or 1), 2),
                    "frequency": c.frequency.value,
                }
            )
    else:
        for c in calc.costs:
            if c.frequency == Frequency.ONE_TIME:
                lines.append({"name": c.name, "amount": c.amount, "frequency": "ONE_TIME"})
    if calc.resale_value:
        lines.append({"name": "Resale", "amount": -calc.resale_value})

    total = round(sum(line["amount"] for line in lines), 2)
    result = {
        "name": calc.name,
        "type": calc.type.value,
        "total_cost": total,
        "breakdown": lines,
        "hourly_rate": round(rate.hourly_rate, 2),
        "work": work_time(total, rate),
        "life_cost": _life_cost(total, years) if years else None,
    }
    return result


def _compute_recurring(calc: CalculationIn, rate: WorkRate) -> dict:
    per_year = sum(
        c.amount * OCCURRENCES_PER_YEAR[c.frequency]
        for c in calc.costs
        if c.frequency != Frequency.ONE_TIME
    )
    one_time = sum(c.amount for c in calc.costs if c.frequency == Frequency.ONE_TIME)
    horizons = []
    for label, years in RECURRING_HORIZONS:
        cost = round(per_year * years + one_time, 2)
        horizons.append({"label": label, "years": round(years, 4), "cost": cost, "work": work_time(cost, rate)})
    ten = horizons[-1]
    return {
        "name": calc.name,
        "type": calc.type.value,
        "total_cost": ten["cost"],
        "breakdown": [
            {"name": c.name, "amount": c.amount, "frequency": c.frequency.value} for c in calc.costs
        ],
        "hourly_rate": round(rate.hourly_rate, 2),
        "work": ten["work"],
        "horizons": horizons,
        "summary": {"years": 10, "working_days": ten["work"]["working_days"]},
        "life_cost": None,
    }


def compare(a: dict, b: dict, rate: WorkRate) -> dict:
    diff_hours = round(a["work"]["hours"] - b["work"]["hours"], 2)
    return {
        "a": a,
        "b": b,
        "difference": {
            "cost": round(a["total_cost"] - b["total_cost"], 2),
            "hours": diff_hours,
            "working_days": round(diff_hours / rate.hours_per_day, 2),
        },
    }
