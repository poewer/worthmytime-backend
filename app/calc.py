"""Czysty silnik obliczeń (bez I/O) - serce produktu.

Konwencje (WorthMyTime_Budget_Model.md, sekcje 3, 5, 21):
- godziny w miesiącu = hours_per_day * days_per_week * 52 / 12   (8h * 5d -> 173,33 h)
- rok roboczy        = days_per_week * 52                        (5d -> 260 dni)
- cykl DAILY         = 365,25 dnia w roku
"""

from dataclasses import dataclass

from .schemas import CalcType, CalculationIn, Frequency

WEEKS_PER_YEAR = 52
WEEKS_PER_MONTH = WEEKS_PER_YEAR / 12
DAYS_PER_YEAR = 365.25
OCCURRENCES_PER_YEAR = {
    Frequency.DAILY: DAYS_PER_YEAR,
    Frequency.WEEKLY: 52,
    Frequency.MONTHLY: 12,
    Frequency.YEARLY: 1,
}
RECURRING_HORIZONS = [("1 month", 1 / 12), ("1 year", 1), ("5 years", 5), ("10 years", 10)]


@dataclass(frozen=True)
class WorkRate:
    hourly_rate: float  # stawka użyta do przeliczeń (nominalna albo realna)
    hours_per_day: float = 8.0
    days_per_week: float = 5.0
    # dochód netto niezależny od trybu stawki; None = stawka * godziny w miesiącu
    net_income: float | None = None
    nominal_rate: float | None = None
    real_rate: float | None = None

    @property
    def hours_per_month(self) -> float:
        return self.hours_per_day * self.days_per_week * WEEKS_PER_MONTH

    @property
    def monthly_income(self) -> float:
        """Miesięczny dochód netto (przy stawce podanej wprost: stawka * godziny w miesiącu)."""
        if self.net_income is not None:
            return self.net_income
        return self.hourly_rate * self.hours_per_month

    @property
    def working_days_per_year(self) -> float:
        return self.days_per_week * WEEKS_PER_YEAR


def real_hourly_rate(
    net_income: float,
    hours_per_month: float,
    days_per_week: float,
    commute_minutes_per_day: float,
    work_costs_monthly: float,
) -> float:
    """Realna stawka: (dochód - koszty pracy) / (godziny pracy + godziny dojazdu w miesiącu)."""
    commute_hours = commute_minutes_per_day / 60 * days_per_week * WEEKS_PER_MONTH
    earned = max(net_income - work_costs_monthly, 0.01)
    return earned / (hours_per_month + commute_hours)


def resolve_rate(
    monthly_income: float | None,
    hourly_rate: float | None,
    hours_per_day: float = 8.0,
    days_per_week: float = 5.0,
    commute_minutes_per_day: float = 0.0,
    work_costs_monthly: float = 0.0,
    rate_mode: str = "NOMINAL",
) -> WorkRate:
    """Bezpośrednia stawka ma pierwszeństwo; w przeciwnym razie z dochodu.

    rate_mode=REAL zastępuje stawkę nominalną realną (z dojazdem i kosztami związanymi z pracą).
    """
    base = WorkRate(1.0, hours_per_day, days_per_week)
    hpm = base.hours_per_month
    if hourly_rate is not None:
        nominal, income = hourly_rate, hourly_rate * hpm
    elif monthly_income is not None:
        nominal, income = monthly_income / hpm, monthly_income
    else:
        raise ValueError("Brak dochodu i stawki godzinowej")
    real = real_hourly_rate(income, hpm, days_per_week, commute_minutes_per_day, work_costs_monthly)
    used = real if rate_mode == "REAL" else nominal
    return WorkRate(used, hours_per_day, days_per_week, net_income=income, nominal_rate=nominal, real_rate=real)


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
        # jaką część miesięcznej wypłaty pochłania wydatek (100 = cała wypłata); zawsze od dochodu netto
        "income_percent": round(money / rate.monthly_income * 100, 1) if rate.monthly_income > 0 else None,
    }


def _life_cost(total: float, years: float) -> dict:
    return {
        "years": years,
        "per_day": round(total / (years * DAYS_PER_YEAR), 2),
        "per_week": round(total / (years * DAYS_PER_YEAR / 7), 2),
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
    per_use = None
    if calc.expected_uses and total > 0:
        per_use_cost = total / calc.expected_uses
        per_use = {
            "uses": calc.expected_uses,
            "cost": round(per_use_cost, 2),
            "work_minutes": round(per_use_cost / rate.hourly_rate * 60, 1),
        }
    result = {
        "name": calc.name,
        "type": calc.type.value,
        "total_cost": total,
        "breakdown": lines,
        "hourly_rate": round(rate.hourly_rate, 2),
        "work": work_time(total, rate),
        "life_cost": _life_cost(total, years) if years else None,
        "per_use": per_use,
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
    month, ten = horizons[0], horizons[-1]
    # nagłówek wyniku = koszt jednego miesiąca (skala zrozumiała dla użytkownika);
    # dłuższe horyzonty (rok, 5 i 10 lat) pokazują, jak to narasta
    return {
        "name": calc.name,
        "type": calc.type.value,
        "total_cost": month["cost"],
        "breakdown": [
            {"name": c.name, "amount": c.amount, "frequency": c.frequency.value} for c in calc.costs
        ],
        "hourly_rate": round(rate.hourly_rate, 2),
        "work": month["work"],
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
