from functools import wraps
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sanic import Request
from sanic.response import json as json_response
from sqlalchemy import select

from . import calc
from .budget import BudgetPlan, analyze, loan_view
from .errors import ApiError
from .models import Budget, BudgetLoan, Calculation, Cost, User
from .schemas import CATEGORIES, BudgetIn, CalculationIn, CostIn, LoanIn, ProfileIn
from .security import decode_token

M = TypeVar("M", bound=BaseModel)


def parse(model: type[M], request: Request) -> M:
    data = request.json
    if data is None:
        raise ApiError("Wymagane ciało żądania w formacie JSON", 400)
    try:
        return model.model_validate(data)
    except ValidationError as e:
        errors = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in e.errors(include_url=False, include_context=False)
        ]
        raise ApiError("Błąd walidacji danych", 422, errors) from e


def ok(data, status: int = 200):
    return json_response(data, status=status)


async def current_user(request: Request) -> User | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    user_id = decode_token(header[7:])
    return await request.ctx.db.get(User, user_id) if user_id else None


def login_required(handler):
    @wraps(handler)
    async def wrapper(request: Request, *args, **kwargs):
        user = await current_user(request)
        if user is None:
            raise ApiError("Wymagane uwierzytelnienie", 401)
        request.ctx.user = user
        return await handler(request, *args, **kwargs)

    return wrapper


def user_profile(user: User) -> dict:
    return {
        "currency": user.currency,
        "monthly_income": user.monthly_income,
        "hourly_rate": user.hourly_rate,
        "hours_per_day": user.hours_per_day,
        "days_per_week": user.days_per_week,
        "effective_hourly_rate": _effective_rate(user),
        "hours_per_month": _effective_hours_month(user),
    }


def _effective_rate(user: User) -> float | None:
    if user.hourly_rate is None and user.monthly_income is None:
        return None
    return round(rate_from_user(user).hourly_rate, 2)


def _effective_hours_month(user: User) -> float:
    return round(calc.WorkRate(1, user.hours_per_day, user.days_per_week).hours_per_month, 2)


def rate_from_user(user: User) -> calc.WorkRate:
    if user.hourly_rate is None and user.monthly_income is None:
        raise ApiError("Uzupełnij profil finansowy (dochód lub stawka godzinowa)", 409)
    return calc.resolve_rate(user.monthly_income, user.hourly_rate, user.hours_per_day, user.days_per_week)


def rate_from_profile(p: ProfileIn) -> calc.WorkRate:
    return calc.resolve_rate(p.monthly_income, p.hourly_rate, p.hours_per_day, p.days_per_week)


async def resolve_rate_for_request(request: Request, profile: ProfileIn | None) -> tuple[calc.WorkRate, str]:
    """Profil z body ma pierwszeństwo, w drugiej kolejności profil zalogowanego."""
    if profile is not None:
        return rate_from_profile(profile), profile.currency
    user = await current_user(request)
    if user is None:
        raise ApiError("Podaj profil finansowy (profile) albo zaloguj się", 400)
    return rate_from_user(user), user.currency


def to_input(c: Calculation) -> CalculationIn:
    return CalculationIn(
        name=c.name,
        type=c.type,
        purchase_price=c.purchase_price,
        ownership_years=c.ownership_years,
        resale_value=c.resale_value,
        category=c.category,
        already_saved=c.already_saved,
        monthly_contribution=c.monthly_contribution,
        costs=[CostIn(name=x.name, amount=x.amount, frequency=x.frequency) for x in c.costs],
    )


def rate_from_calc(c: Calculation) -> calc.WorkRate:
    return calc.WorkRate(c.hourly_rate, c.hours_per_day, c.days_per_week)


def apply_input(c: Calculation, data: CalculationIn) -> None:
    c.name = data.name
    c.type = data.type.value
    c.purchase_price = data.purchase_price
    c.ownership_years = data.ownership_years
    c.resale_value = data.resale_value
    c.category = data.category.value if data.category else None
    c.already_saved = data.already_saved
    c.monthly_contribution = data.monthly_contribution
    c.costs = [
        Cost(position=i, name=x.name, amount=x.amount, frequency=x.frequency.value)
        for i, x in enumerate(data.costs)
    ]


def _strip_income_percent(result: dict) -> None:
    """Procent wypłaty razem z ceną pozwoliłby odtworzyć dochód - nie pokazujemy go publicznie."""
    result["work"].pop("income_percent", None)
    for h in result.get("horizons", []):
        h["work"].pop("income_percent", None)


def _loan_totals(loans: list[LoanIn] | list[BudgetLoan]) -> dict:
    return {
        "monthly_loans": round(sum(x.installment_amount for x in loans), 2),
        "loans_count": len(loans),
        "last_installment_in_months": max((x.installments_left for x in loans), default=0),
    }


def plan_from_input(budget: BudgetIn | None, monthly_income: float) -> BudgetPlan:
    """Budżet przesłany w żądaniu (użytkownik anonimowy) albo domyślny 50/25/15/10."""
    if budget is None:
        return BudgetPlan(monthly_income=monthly_income)
    return BudgetPlan(
        monthly_income=monthly_income,
        percentages=dict(budget.percentages),
        spent=dict(budget.spent),
        is_custom=True,
        **_loan_totals(budget.loans),
    )


def plan_from_row(row: Budget | None, monthly_income: float, loans: list[BudgetLoan] | None = None) -> BudgetPlan:
    loans = loans or []
    if row is None:
        # kredyty obowiązują także bez ustawionych procentów - to realne zobowiązania
        return BudgetPlan(monthly_income=monthly_income, **_loan_totals(loans))
    return BudgetPlan(
        monthly_income=monthly_income,
        percentages={c: getattr(row, f"pct_{c.value.lower()}") for c in CATEGORIES},
        spent={c: getattr(row, f"spent_{c.value.lower()}") for c in CATEGORIES},
        is_custom=True,
        **_loan_totals(loans),
    )


async def load_loans(request: Request, user: User) -> list[BudgetLoan]:
    rows = await request.ctx.db.scalars(
        select(BudgetLoan).where(BudgetLoan.user_id == user.id).order_by(BudgetLoan.position)
    )
    return list(rows)


async def load_plan(request: Request, user: User, monthly_income: float) -> BudgetPlan:
    return plan_from_row(await request.ctx.db.get(Budget, user.id), monthly_income, await load_loans(request, user))


def serialize_budget(
    row: Budget | None,
    monthly_income: float | None,
    loans: list[BudgetLoan] | None = None,
    hourly_rate: float | None = None,
) -> dict:
    loans = loans or []
    plan = plan_from_row(row, monthly_income or 0.0, loans)
    return {
        "loans": [
            {
                "id": x.id,
                **loan_view(x.name, x.installment_amount, x.installments_left, x.loan_amount, plan, hourly_rate),
            }
            for x in loans
        ],
        "monthly_loans": plan.monthly_loans,
        "loans_income_percent": round(plan.monthly_loans / monthly_income * 100, 1) if monthly_income else None,
        "last_installment_in_months": plan.last_installment_in_months,
        "percentages": {c.value: plan.percentages[c] for c in CATEGORIES},
        "spent": {c.value: plan.spent[c] for c in CATEGORIES},
        "amounts": {c.value: plan.category_budget(c) for c in CATEGORIES} if monthly_income else None,
        "available": {c.value: plan.available(c) for c in CATEGORIES} if monthly_income else None,
        "monthly_income": round(monthly_income, 2) if monthly_income else None,
        "total_spent": plan.total_spent,
        "is_custom": row is not None,
    }


def serialize_calc(c: Calculation, *, public: bool = False, plan: BudgetPlan | None = None) -> dict:
    result = calc.compute(to_input(c), rate_from_calc(c))
    if plan is not None and not public:
        result["budget"] = analyze(to_input(c), plan)
    out = {
        "name": c.name,
        "type": c.type,
        "currency": c.currency,
        "created_at": c.created_at.isoformat(),
        "input": to_input(c).model_dump(mode="json"),
        "result": result,
    }
    if public:
        # Strona publiczna nie ujawnia stawki ani zapisanego profilu.
        out["result"].pop("hourly_rate", None)
        _strip_income_percent(out["result"])
        out.pop("input")
        out["input"] = {"name": c.name, "type": c.type}
        return out
    out.update(
        id=c.id,
        public_id=c.public_id,
        updated_at=c.updated_at.isoformat(),
    )
    return out
