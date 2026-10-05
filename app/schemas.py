from enum import Enum

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


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ProfileIn(BaseModel):
    currency: str = Field(default="PLN", min_length=3, max_length=3)
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

    @model_validator(mode="after")
    def _check(self):
        if self.type == CalcType.TCO and self.ownership_years is None:
            raise ValueError("Cost of ownership wymaga okresu posiadania (ownership_years)")
        if self.type == CalcType.RECURRING and not self.costs:
            raise ValueError("Koszt cykliczny wymaga co najmniej jednej pozycji w costs")
        return self


class CalculateIn(BaseModel):
    """Obliczenie bezstanowe; profil opcjonalny dla zalogowanych."""

    profile: ProfileIn | None = None
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
