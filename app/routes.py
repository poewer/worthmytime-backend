import secrets

from sanic import Blueprint, Request
from sanic.response import empty
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import calc
from .errors import ApiError
from .helpers import (
    apply_input,
    login_required,
    ok,
    parse,
    rate_from_calc,
    rate_from_user,
    resolve_rate_for_request,
    serialize_calc,
    to_input,
    user_profile,
)
from .models import Calculation, User
from .schemas import CalculateIn, CalculationIn, CompareIn, Credentials, ProfileIn
from .security import create_token, hash_password, verify_password

bp = Blueprint("api", url_prefix="/api/v1")


@bp.options("/<path:path>")
async def preflight(request: Request, path: str):
    # nagłówki CORS dokłada middleware on_response
    return empty(204)


@bp.get("/health")
async def health(request: Request):
    return ok({"status": "ok"})


# ---------- auth ----------


@bp.post("/auth/register")
async def register(request: Request):
    data = parse(Credentials, request)
    db = request.ctx.db
    user = User(email=data.email.lower(), password_hash=hash_password(data.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ApiError("Konto z tym adresem e-mail już istnieje", 409)
    return ok({"token": create_token(user.id), "profile": user_profile(user)}, 201)


@bp.post("/auth/login")
async def login(request: Request):
    data = parse(Credentials, request)
    user = await request.ctx.db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise ApiError("Nieprawidłowy e-mail lub hasło", 401)
    return ok({"token": create_token(user.id), "profile": user_profile(user)})


@bp.get("/auth/me")
@login_required
async def me(request: Request):
    user = request.ctx.user
    return ok({"id": user.id, "email": user.email, "profile": user_profile(user)})


# ---------- profil ----------


@bp.get("/profile")
@login_required
async def get_profile(request: Request):
    return ok(user_profile(request.ctx.user))


@bp.put("/profile")
@login_required
async def put_profile(request: Request):
    data = parse(ProfileIn, request)
    user = request.ctx.user
    user.currency = data.currency
    user.monthly_income = data.monthly_income
    user.hourly_rate = data.hourly_rate
    user.hours_per_day = data.hours_per_day
    user.days_per_week = data.days_per_week
    await request.ctx.db.commit()
    return ok(user_profile(user))


# ---------- obliczenia bezstanowe (bez logowania) ----------


@bp.post("/calculate")
async def calculate(request: Request):
    data = parse(CalculateIn, request)
    rate, currency = await resolve_rate_for_request(request, data.profile)
    return ok({"currency": currency, **calc.compute(data.calculation, rate)})


@bp.post("/compare")
async def compare(request: Request):
    data = parse(CompareIn, request)
    rate, currency = await resolve_rate_for_request(request, data.profile)

    async def side(inline: CalculationIn | None, saved_id: str | None) -> dict:
        if inline is not None:
            return calc.compute(inline, rate)
        user = await _require_user(request)
        saved = await _own_calc(request, user, saved_id)
        return calc.compute(to_input(saved), rate)

    a = await side(data.a, data.a_id)
    b = await side(data.b, data.b_id)
    return ok({"currency": currency, **calc.compare(a, b, rate)})


async def _require_user(request: Request) -> User:
    from .helpers import current_user

    user = await current_user(request)
    if user is None:
        raise ApiError("Wymagane uwierzytelnienie", 401)
    return user


# ---------- historia obliczeń ----------


async def _own_calc(request: Request, user: User, calc_id: str) -> Calculation:
    c = await request.ctx.db.get(Calculation, calc_id)
    if c is None or c.user_id != user.id:
        raise ApiError("Nie znaleziono obliczenia", 404)
    return c


@bp.post("/calculations")
@login_required
async def save_calculation(request: Request):
    data = parse(CalculationIn, request)
    user = request.ctx.user
    rate = rate_from_user(user)
    c = Calculation(
        user_id=user.id,
        currency=user.currency,
        hourly_rate=rate.hourly_rate,
        hours_per_day=rate.hours_per_day,
        days_per_week=rate.days_per_week,
    )
    apply_input(c, data)
    request.ctx.db.add(c)
    await request.ctx.db.commit()
    await request.ctx.db.refresh(c)
    return ok(serialize_calc(c), 201)


@bp.get("/calculations")
@login_required
async def list_calculations(request: Request):
    rows = await request.ctx.db.scalars(
        select(Calculation)
        .where(Calculation.user_id == request.ctx.user.id)
        .order_by(Calculation.created_at.desc())
    )
    return ok({"items": [serialize_calc(c) for c in rows]})


@bp.get("/calculations/<calc_id:str>")
@login_required
async def get_calculation(request: Request, calc_id: str):
    return ok(serialize_calc(await _own_calc(request, request.ctx.user, calc_id)))


@bp.put("/calculations/<calc_id:str>")
@login_required
async def update_calculation(request: Request, calc_id: str):
    data = parse(CalculationIn, request)
    user = request.ctx.user
    c = await _own_calc(request, user, calc_id)
    # edycja przelicza wynik według aktualnego profilu
    rate = rate_from_user(user)
    c.currency, c.hourly_rate = user.currency, rate.hourly_rate
    c.hours_per_day, c.days_per_week = rate.hours_per_day, rate.days_per_week
    apply_input(c, data)
    await request.ctx.db.commit()
    await request.ctx.db.refresh(c)
    return ok(serialize_calc(c))


@bp.delete("/calculations/<calc_id:str>")
@login_required
async def delete_calculation(request: Request, calc_id: str):
    c = await _own_calc(request, request.ctx.user, calc_id)
    await request.ctx.db.delete(c)
    await request.ctx.db.commit()
    return ok({"deleted": True})


@bp.post("/calculations/<calc_id:str>/duplicate")
@login_required
async def duplicate_calculation(request: Request, calc_id: str):
    src = await _own_calc(request, request.ctx.user, calc_id)
    copy = Calculation(
        user_id=src.user_id,
        currency=src.currency,
        hourly_rate=src.hourly_rate,
        hours_per_day=src.hours_per_day,
        days_per_week=src.days_per_week,
    )
    data = to_input(src)
    data.name = f"{src.name} (kopia)"[:200]
    apply_input(copy, data)
    request.ctx.db.add(copy)
    await request.ctx.db.commit()
    await request.ctx.db.refresh(copy)
    return ok(serialize_calc(copy), 201)


# ---------- udostępnianie ----------


@bp.post("/calculations/<calc_id:str>/share")
@login_required
async def share(request: Request, calc_id: str):
    c = await _own_calc(request, request.ctx.user, calc_id)
    if c.public_id is None:
        c.public_id = secrets.token_urlsafe(6)
        await request.ctx.db.commit()
    return ok({"public_id": c.public_id, "path": f"/s/{c.public_id}"})


@bp.delete("/calculations/<calc_id:str>/share")
@login_required
async def unshare(request: Request, calc_id: str):
    c = await _own_calc(request, request.ctx.user, calc_id)
    c.public_id = None
    await request.ctx.db.commit()
    return ok({"public_id": None})


@bp.get("/shared/<public_id:str>")
async def shared(request: Request, public_id: str):
    c = await request.ctx.db.scalar(select(Calculation).where(Calculation.public_id == public_id))
    if c is None:
        raise ApiError("Nie znaleziono udostępnionego wyniku", 404)
    return ok(serialize_calc(c, public=True))


# ---------- dashboard ----------


@bp.get("/dashboard")
@login_required
async def dashboard(request: Request):
    rows = list(
        await request.ctx.db.scalars(
            select(Calculation)
            .where(Calculation.user_id == request.ctx.user.id)
            .order_by(Calculation.created_at.desc())
        )
    )
    items = [(c, calc.compute(to_input(c), rate_from_calc(c))) for c in rows]
    total_cost = sum(r["total_cost"] for _, r in items)
    total_hours = sum(r["work"]["hours"] for _, r in items)
    total_days = sum(r["work"]["working_days"] for _, r in items)
    largest = max(items, key=lambda x: x[1]["total_cost"], default=None)

    recurring = [
        {
            "id": c.id,
            "name": c.name,
            "yearly_cost": next(h["cost"] for h in r["horizons"] if h["label"] == "1 year"),
            "yearly_hours": next(h["work"]["hours"] for h in r["horizons"] if h["label"] == "1 year"),
        }
        for c, r in items
        if c.type == "RECURRING"
    ]
    return ok(
        {
            "currency": request.ctx.user.currency,
            "count": len(items),
            "total_value": round(total_cost, 2),
            "total_hours": round(total_hours, 2),
            "total_working_days": round(total_days, 2),
            "largest_expense": (
                {"id": largest[0].id, "name": largest[0].name, "total_cost": largest[1]["total_cost"],
                 "hours": largest[1]["work"]["hours"]}
                if largest
                else None
            ),
            "recurring": recurring,
            "recurring_yearly_total": round(sum(x["yearly_cost"] for x in recurring), 2),
            "recent": [serialize_calc(c) for c, _ in items[:5]],
        }
    )
