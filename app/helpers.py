from functools import wraps
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sanic import Request
from sanic.response import json as json_response

from . import calc
from .errors import ApiError
from .models import Calculation, Cost, User
from .schemas import CalculationIn, CostIn, ProfileIn
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
    c.costs = [
        Cost(position=i, name=x.name, amount=x.amount, frequency=x.frequency.value)
        for i, x in enumerate(data.costs)
    ]


def serialize_calc(c: Calculation, *, public: bool = False) -> dict:
    result = calc.compute(to_input(c), rate_from_calc(c))
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
        out.pop("input")
        out["input"] = {"name": c.name, "type": c.type}
        return out
    out.update(
        id=c.id,
        public_id=c.public_id,
        updated_at=c.updated_at.isoformat(),
    )
    return out
