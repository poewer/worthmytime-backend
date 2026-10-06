from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class Frequency(str, Enum):
    ONE_TIME = "ONE_TIME"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class CalcType(str, Enum):
    SIMPLE = "SIMPLE"
    RECURRING = "RECURRING"
    TCO = "TCO"


class Category(str, Enum):
    """Koszyki budżetu (WorthMyTime_Budget_Model.md, sekcja 7)."""

    NEEDS = "NEEDS"
    FUTURE = "FUTURE"
    GOALS = "GOALS"
    FUN = "FUN"


CATEGORIES = list(Category)
DEFAULT_PERCENTAGES = {Category.NEEDS: 50.0, Category.FUTURE: 25.0, Category.GOALS: 15.0, Category.FUN: 10.0}


class LoanIn(BaseModel):
    """Kredyt lub pożyczka w trakcie spłaty (rata to wymagalne zobowiązanie, P0)."""

    name: str = Field(min_length=1, max_length=100)
    installment_amount: float = Field(gt=0, description="wysokość miesięcznej raty")
    installments_left: int = Field(ge=1, le=600, description="liczba rat do spłacenia")
    loan_amount: float | None = Field(default=None, ge=0, description="pierwotna kwota kredytu (opcjonalnie)")


class BudgetIn(BaseModel):
    """Plan budżetu: procenty kategorii (suma 100) i wydatki w bieżącym miesiącu w każdej z nich."""

    percentages: dict[Category, float] = Field(default_factory=lambda: dict(DEFAULT_PERCENTAGES))
    spent: dict[Category, float] = Field(default_factory=dict)
    # kredyty i pożyczki: raty wchodzą automatycznie do kategorii NEEDS, więc nie wpisuje się ich w `spent`
    loans: list[LoanIn] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _check(self):
        pct = {c: float(self.percentages.get(c, 0)) for c in CATEGORIES}
        if any(v < 0 or v > 100 for v in pct.values()):
            raise ValueError("Procent kategorii musi być w zakresie 0-100")
        if abs(sum(pct.values()) - 100) > 0.01:
            raise ValueError("Procenty kategorii muszą sumować się do 100")
        spent = {c: float(self.spent.get(c, 0)) for c in CATEGORIES}
        if any(v < 0 for v in spent.values()):
            raise ValueError("Wydatki w kategorii nie mogą być ujemne")
        self.percentages, self.spent = pct, spent
        return self


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ProfileIn(BaseModel):
    currency: str = Field(default="PLN", min_length=3, max_length=3)
    # realna stawka: dojazd i koszty związane z pracą (opcjonalnie)
    commute_minutes_per_day: float = Field(default=0, ge=0, le=600)
    work_costs_monthly: float = Field(default=0, ge=0)
    rate_mode: Literal["NOMINAL", "REAL"] = "NOMINAL"
    monthly_income: float | None = Field(default=None, gt=0)
    hourly_rate: float | None = Field(default=None, gt=0)
    hours_per_day: float = Field(default=8, gt=0, le=24)
    days_per_week: float = Field(default=5, gt=0, le=7)

    @model_validator(mode="after")
    def _need_income_or_rate(self):
        if self.monthly_income is None and self.hourly_rate is None:
            raise ValueError("Podaj miesięczny dochód netto albo stawkę godzinową")
        self.currency = self.currency.upper()
        return self


class CostIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float = Field(ge=0)
    frequency: Frequency = Frequency.ONE_TIME


class CalculationIn(BaseModel):
    name: str = Field(default="Bez nazwy", min_length=1, max_length=200)
    type: CalcType = CalcType.SIMPLE
    purchase_price: float = Field(default=0, ge=0)
    ownership_years: float | None = Field(default=None, gt=0, le=100)
    resale_value: float = Field(default=0, ge=0)
    costs: list[CostIn] = Field(default_factory=list, max_length=50)
    # plan budżetowy (opcjonalnie): kategoria + cel oszczędnościowy
    expected_uses: int | None = Field(default=None, ge=1, le=1_000_000)
    category: Category | None = None
    already_saved: float = Field(default=0, ge=0)
    monthly_contribution: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _check(self):
        if self.type == CalcType.TCO and self.ownership_years is None:
            raise ValueError("Cost of ownership wymaga okresu posiadania (ownership_years)")
        if self.type == CalcType.RECURRING and not self.costs:
            raise ValueError("Koszt cykliczny wymaga co najmniej jednej pozycji w costs")
        return self


class ExpenseIn(BaseModel):
    category: Category
    amount: float = Field(gt=0, le=1_000_000_000)
    note: str | None = Field(default=None, max_length=200)
    spent_on: date | None = None  # domyślnie dziś


class WishIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: float = Field(gt=0, le=1_000_000_000)
    category: Category | None = None
    cooldown_days: int = Field(default=30, ge=0, le=365)


class DecisionIn(BaseModel):
    decision: Literal["BOUGHT", "DROPPED"]


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_amount: float = Field(gt=0, le=1_000_000_000)
    saved_amount: float = Field(default=0, ge=0)
    monthly_contribution: float | None = Field(default=None, gt=0)
    target_date: date | None = None


class DepositIn(BaseModel):
    amount: float = Field(description="dodatnia wpłata albo ujemna wypłata")

    @model_validator(mode="after")
    def _nonzero(self):
        if self.amount == 0:
            raise ValueError("Kwota nie może być zerem")
        return self


class CalculateIn(BaseModel):
    """Obliczenie bezstanowe; profil opcjonalny dla zalogowanych."""

    profile: ProfileIn | None = None
    budget: BudgetIn | None = None
    calculation: CalculationIn


class CompareIn(BaseModel):
    profile: ProfileIn | None = None
    a: CalculationIn | None = None
    b: CalculationIn | None = None
    a_id: str | None = None
    b_id: str | None = None

    @model_validator(mode="after")
    def _both_sides(self):
        if (self.a is None) == (self.a_id is None) or (self.b is None) == (self.b_id is None):
            raise ValueError("Każda strona porównania wymaga dokładnie jednego z: a/a_id oraz b/b_id")
        return self
