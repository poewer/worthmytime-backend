"""Endpointy planowania: rejestr wydatków, lista życzeń i cele oszczędnościowe (wymagają konta)."""

import hashlib
from datetime import UTC, datetime

from sanic import Blueprint, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import calc
from .errors import ApiError
from .forecast import forecast
from .helpers import (
    NOT_LOAN_PAYMENT,
    load_plan,
    login_required,
    materialize_recurring,
    ok,
    parse,
    rate_from_user,
    today,
)
from .models import BudgetLoan, Expense, RecurringExpense, SavingsGoal, User, WishlistItem
from .money import rnd
from .planning import (
    goal_view,
    last_periods,
    month_bounds,
    monthly_summary,
    parse_period,
    period_of,
    totals_by_category,
    wish_stats,
    wish_view,
)
from .schemas import (
    Category,
    DecisionIn,
    DepositIn,
    ExpenseImportIn,
    ExpenseIn,
    GoalIn,
    LoanPaymentIn,
    RecurringIn,
    WishIn,
)

bp = Blueprint("planning", url_prefix="/api/v1")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    """SQLite zwraca daty bez strefy - traktujemy je jako UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _own(request: Request, model, item_id: str, user: User, what: str):
    row = await request.ctx.db.get(model, item_id)
    if row is None or row.user_id != user.id:
        raise ApiError(f"Nie znaleziono: {what}", 404)
    return row


# ---------- prognoza budżetu ----------


@bp.get("/budget/forecast")
@login_required
async def budget_forecast(request: Request):
    """Dzienny limit i prognoza końca miesiąca dla każdej kategorii budżetu."""
    user = request.ctx.user
    if user.hourly_rate is None and user.monthly_income is None:
        raise ApiError("Uzupełnij profil finansowy (dochód lub stawka godzinowa)", 409)
    plan = await load_plan(request, user, rate_from_user(user).monthly_income)
    return ok({"currency": user.currency, **forecast(plan, today())})


# ---------- rejestr wydatków ----------


def _expense(e: Expense) -> dict:
    return {
        "id": e.id,
        "category": e.category,
        "amount": e.amount,
        "note": e.note,
        "spent_on": e.spent_on.isoformat(),
        "source_type": e.source_type,
        "source_id": e.source_id,
    }


def _period_arg(request: Request) -> str:
    period = request.args.get("month") or period_of(today())
    try:
        parse_period(period)
    except ValueError:
        raise ApiError("Parametr month ma format YYYY-MM", 422)
    return period


@bp.get("/expenses")
@login_required
async def list_expenses(request: Request):
    period = _period_arg(request)
    await materialize_recurring(request, request.ctx.user)
    start, end = month_bounds(period)
    rows = list(
        await request.ctx.db.scalars(
            select(Expense)
            .where(Expense.user_id == request.ctx.user.id, Expense.spent_on >= start, Expense.spent_on < end)
            .order_by(Expense.spent_on.desc(), Expense.created_at.desc())
        )
    )
    # opłacone raty są na liście, ale nie wchodzą do sum (rata jest już zobowiązaniem w Potrzebach)
    totals = totals_by_category((e.category, e.amount) for e in rows if e.source_type != "LOAN")
    loan_payments = rnd(sum(e.amount for e in rows if e.source_type == "LOAN"), 2)
    return ok(
        {
            "month": period,
            "items": [_expense(e) for e in rows],
            "totals": totals,
            "total": rnd(sum(totals.values()), 2),
            "loan_payments": loan_payments,
        }
    )


@bp.post("/expenses")
@login_required
async def add_expense(request: Request):
    data = parse(ExpenseIn, request)
    e = Expense(
        user_id=request.ctx.user.id,
        category=data.category.value,
        amount=data.amount,
        note=data.note,
        spent_on=data.spent_on or today(),
    )
    request.ctx.db.add(e)
    await request.ctx.db.commit()
    return ok(_expense(e), 201)


@bp.post("/expenses/import")
@login_required
async def import_expenses(request: Request):
    """Dopisuje wiele wydatków naraz (np. z wyciągu bankowego).

    Idempotentne: ten sam `key` nie tworzy drugiego wpisu.
    """
    data = parse(ExpenseImportIn, request)
    user, db = request.ctx.user, request.ctx.db
    # klucz łączymy z użytkownikiem, bo unikalność źródła w bazie jest globalna
    ids = {item.key: hashlib.sha256(f"{user.id}:{item.key}".encode()).hexdigest()[:32] for item in data.items}
    existing = set(
        await db.scalars(
            select(Expense.source_id).where(
                Expense.user_id == user.id, Expense.source_type == "IMPORT", Expense.source_id.in_(set(ids.values()))
            )
        )
    )
    seen, created = set(existing), 0
    for item in data.items:
        source_id = ids[item.key]
        if source_id in seen:
            continue
        seen.add(source_id)
        db.add(
            Expense(
                user_id=user.id,
                category=item.category.value,
                amount=item.amount,
                note=item.note,
                spent_on=item.spent_on,
                source_type="IMPORT",
                source_id=source_id,
            )
        )
        created += 1
    try:
        await db.commit()
    except IntegrityError:  # równoległy import tego samego wyciągu
        await db.rollback()
        raise ApiError("Ten import jest już wykonywany, spróbuj ponownie", 409)
    return ok({"created": created, "skipped": len(data.items) - created}, 201 if created else 200)


@bp.delete("/expenses/<expense_id:str>")
@login_required
async def delete_expense(request: Request, expense_id: str):
    e = await _own(request, Expense, expense_id, request.ctx.user, "wydatku")
    await request.ctx.db.delete(e)
    await request.ctx.db.commit()
    return ok({"deleted": True})


@bp.get("/expenses/summary")
@login_required
async def expenses_summary(request: Request):
    try:
        months = max(1, min(24, int(request.args.get("months", 6))))
    except ValueError:
        raise ApiError("Parametr months musi być liczbą", 422)
    await materialize_recurring(request, request.ctx.user)
    periods = last_periods(today(), months)
    start, _ = month_bounds(periods[0])
    rows = await request.ctx.db.execute(
        select(Expense.spent_on, Expense.category, Expense.amount).where(
            Expense.user_id == request.ctx.user.id, Expense.spent_on >= start, NOT_LOAN_PAYMENT
        )
    )
    return ok({"months": monthly_summary(rows.all(), periods)})


# ---------- stałe wydatki ----------


def _recurring(t: RecurringExpense) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "category": t.category,
        "amount": t.amount,
        "day_of_month": t.day_of_month,
        "active": t.active,
        "start_date": t.start_date.isoformat(),
    }


@bp.get("/recurring-expenses")
@login_required
async def list_recurring(request: Request):
    rows = await request.ctx.db.scalars(
        select(RecurringExpense)
        .where(RecurringExpense.user_id == request.ctx.user.id)
        .order_by(RecurringExpense.day_of_month, RecurringExpense.created_at)
    )
    items = [_recurring(t) for t in rows]
    active = [t for t in items if t["active"]]
    return ok({"items": items, "monthly_total": rnd(sum(t["amount"] for t in active), 2)})


@bp.post("/recurring-expenses")
@login_required
async def add_recurring(request: Request):
    data = parse(RecurringIn, request)
    now = today()
    t = RecurringExpense(
        user_id=request.ctx.user.id,
        name=data.name,
        category=data.category.value,
        amount=data.amount,
        day_of_month=data.day_of_month,
        active=data.active,
        start_date=data.start_date or now,
    )
    request.ctx.db.add(t)
    await request.ctx.db.commit()
    await materialize_recurring(request, request.ctx.user)  # zaległe wpisy od start_date pojawiają się od razu
    return ok(_recurring(t), 201)


@bp.put("/recurring-expenses/<template_id:str>")
@login_required
async def update_recurring(request: Request, template_id: str):
    data = parse(RecurringIn, request)
    t = await _own(request, RecurringExpense, template_id, request.ctx.user, "stałego wydatku")
    if data.active and not t.active:
        t.generated_through = today()  # po ponownym włączeniu nie dopisujemy okresu wyłączenia
    t.name, t.category, t.amount = data.name, data.category.value, data.amount
    t.day_of_month, t.active = data.day_of_month, data.active
    await request.ctx.db.commit()
    return ok(_recurring(t))


@bp.delete("/recurring-expenses/<template_id:str>")
@login_required
async def delete_recurring(request: Request, template_id: str):
    t = await _own(request, RecurringExpense, template_id, request.ctx.user, "stałego wydatku")
    await request.ctx.db.delete(t)  # wpisy już dopisane do rejestru zostają
    await request.ctx.db.commit()
    return ok({"deleted": True})


# ---------- spłata rat ----------


@bp.post("/budget/loans/<loan_id:str>/pay")
@login_required
async def pay_loan_installment(request: Request, loan_id: str):
    """Oznacza ratę kredytu jako opłaconą w danym miesiącu i zapisuje ją w rejestrze (Potrzeby)."""
    data = parse(LoanPaymentIn, request)
    loan = await _own(request, BudgetLoan, loan_id, request.ctx.user, "kredytu")
    paid_on = data.paid_on or today()
    start, end = month_bounds(period_of(paid_on))
    already = await request.ctx.db.scalar(
        select(Expense.id).where(
            Expense.user_id == request.ctx.user.id,
            Expense.source_type == "LOAN",
            Expense.source_id == loan.id,
            Expense.spent_on >= start,
            Expense.spent_on < end,
        )
    )
    if already:
        raise ApiError("Rata za ten miesiąc jest już oznaczona jako opłacona", 409)
    e = Expense(
        user_id=request.ctx.user.id,
        category="NEEDS",
        amount=loan.installment_amount,
        note=f"Rata: {loan.name}",
        spent_on=paid_on,
        source_type="LOAN",
        source_id=loan.id,
    )
    request.ctx.db.add(e)
    await request.ctx.db.commit()
    return ok(_expense(e), 201)


# ---------- lista życzeń ----------


def _wish(item: WishlistItem, rate: calc.WorkRate) -> dict:
    work = calc.work_time(item.price, rate)
    view = wish_view(
        status=item.status,
        price=item.price,
        created_at=_aware(item.created_at),
        cooldown_days=item.cooldown_days,
        now=_now(),
        work=work,
    )
    return {
        "id": item.id,
        "name": item.name,
        "price": item.price,
        "category": item.category,
        "cooldown_days": item.cooldown_days,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        **view,
    }


async def _wishlist_payload(request: Request, user: User) -> dict:
    rate = rate_from_user(user)
    rows = await request.ctx.db.scalars(
        select(WishlistItem).where(WishlistItem.user_id == user.id).order_by(WishlistItem.created_at.desc())
    )
    items = [_wish(i, rate) for i in rows]
    return {"items": items, "stats": wish_stats(items), "currency": user.currency}


@bp.get("/wishlist")
@login_required
async def get_wishlist(request: Request):
    return ok(await _wishlist_payload(request, request.ctx.user))


@bp.post("/wishlist")
@login_required
async def add_wish(request: Request):
    data = parse(WishIn, request)
    user = request.ctx.user
    rate = rate_from_user(user)
    item = WishlistItem(
        user_id=user.id,
        name=data.name,
        price=data.price,
        category=data.category.value if data.category else None,
        cooldown_days=data.cooldown_days,
    )
    request.ctx.db.add(item)
    await request.ctx.db.commit()
    await request.ctx.db.refresh(item)
    return ok(_wish(item, rate), 201)


@bp.post("/wishlist/<item_id:str>/decision")
@login_required
async def decide_wish(request: Request, item_id: str):
    data = parse(DecisionIn, request)
    user = request.ctx.user
    item = await _own(request, WishlistItem, item_id, user, "pozycji listy życzeń")
    if item.status != "WAITING":
        raise ApiError("Decyzja została już podjęta", 409)
    item.status = data.decision
    item.decided_at = _now()
    await request.ctx.db.commit()
    return ok(_wish(item, rate_from_user(user)))


@bp.delete("/wishlist/<item_id:str>")
@login_required
async def delete_wish(request: Request, item_id: str):
    item = await _own(request, WishlistItem, item_id, request.ctx.user, "pozycji listy życzeń")
    await request.ctx.db.delete(item)
    await request.ctx.db.commit()
    return ok({"deleted": True})


# ---------- cele oszczędnościowe ----------


def _goal(g: SavingsGoal, hourly_rate: float | None, capacity: dict[str, float] | None = None) -> dict:
    """capacity: wolne środki kategorii pomniejszone o wpłaty innych celów z tej samej kategorii."""
    max_monthly = None
    if g.category and capacity is not None and g.category in capacity:
        max_monthly = rnd(max(capacity[g.category], 0.0), 2)
    # bez własnej wpłaty zakładamy maksimum, na jakie pozwala budżet kategorii
    contribution = g.monthly_contribution if g.monthly_contribution is not None else max_monthly
    return {
        "id": g.id,
        "name": g.name,
        "category": g.category,
        "target_amount": g.target_amount,
        "saved_amount": g.saved_amount,
        "monthly_contribution": g.monthly_contribution,
        "effective_contribution": contribution,
        "max_monthly_contribution": max_monthly,
        "contribution_source": (
            "USER"
            if g.monthly_contribution is not None
            else ("CATEGORY_AVAILABLE" if max_monthly is not None else None)
        ),
        "contribution_exceeds": bool(
            g.monthly_contribution is not None and max_monthly is not None and g.monthly_contribution > max_monthly
        ),
        "target_date": g.target_date.isoformat() if g.target_date else None,
        "created_at": g.created_at.isoformat(),
        **goal_view(
            target_amount=g.target_amount,
            saved_amount=g.saved_amount,
            monthly_contribution=contribution if contribution else None,
            target_date=g.target_date,
            today=today(),
            hourly_rate=hourly_rate,
        ),
    }


async def _capacity(request: Request, user: User, goals: list[SavingsGoal]) -> dict[str, dict[str, float]] | None:
    """Dla każdego celu: ile można miesięcznie przeznaczyć z jego kategorii (wolne środki - wpłaty innych celów)."""
    if user.hourly_rate is None and user.monthly_income is None:
        return None
    plan = await load_plan(request, user, rate_from_user(user).monthly_income)
    out: dict[str, dict[str, float]] = {}
    for g in goals:
        if not g.category:
            continue
        others = sum(
            o.monthly_contribution or 0.0
            for o in goals
            if o.id != g.id and o.category == g.category and o.completed_at is None
        )
        out[g.id] = {g.category: plan.available(Category(g.category)) - others}
    return out

async def _single_goal(request: Request, user: User, g: SavingsGoal) -> dict:
    rows = await request.ctx.db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user.id))
    caps = await _capacity(request, user, list(rows))
    return _goal(g, _hourly_rate(user), (caps or {}).get(g.id))


def _hourly_rate(user: User) -> float | None:
    if user.hourly_rate is None and user.monthly_income is None:
        return None
    return rate_from_user(user).hourly_rate


def _sync_completion(g: SavingsGoal) -> None:
    done = g.saved_amount >= g.target_amount
    if done and g.completed_at is None:
        g.completed_at = _now()
    elif not done:
        g.completed_at = None


@bp.get("/goals")
@login_required
async def list_goals(request: Request):
    user = request.ctx.user
    rate = _hourly_rate(user)
    rows = await request.ctx.db.scalars(
        select(SavingsGoal).where(SavingsGoal.user_id == user.id).order_by(SavingsGoal.created_at.desc())
    )
    goals = list(rows)
    caps = await _capacity(request, user, goals)
    return ok(
        {"items": [_goal(g, rate, (caps or {}).get(g.id)) for g in goals], "currency": user.currency}
    )


@bp.post("/goals")
@login_required
async def add_goal(request: Request):
    data = parse(GoalIn, request)
    user = request.ctx.user
    g = SavingsGoal(user_id=user.id, **data.model_dump())
    _sync_completion(g)
    request.ctx.db.add(g)
    await request.ctx.db.commit()
    return ok(await _single_goal(request, user, g), 201)


@bp.put("/goals/<goal_id:str>")
@login_required
async def update_goal(request: Request, goal_id: str):
    data = parse(GoalIn, request)
    user = request.ctx.user
    g = await _own(request, SavingsGoal, goal_id, user, "celu")
    for key, value in data.model_dump().items():
        setattr(g, key, value)
    _sync_completion(g)
    await request.ctx.db.commit()
    return ok(await _single_goal(request, user, g))


@bp.post("/goals/<goal_id:str>/deposit")
@login_required
async def deposit(request: Request, goal_id: str):
    data = parse(DepositIn, request)
    user = request.ctx.user
    g = await _own(request, SavingsGoal, goal_id, user, "celu")
    if g.saved_amount + data.amount < 0:
        raise ApiError("Nie można wypłacić więcej, niż odłożono", 422)
    g.saved_amount = rnd(g.saved_amount + data.amount, 2)
    _sync_completion(g)
    await request.ctx.db.commit()
    return ok(await _single_goal(request, user, g))


@bp.delete("/goals/<goal_id:str>")
@login_required
async def delete_goal(request: Request, goal_id: str):
    g = await _own(request, SavingsGoal, goal_id, request.ctx.user, "celu")
    await request.ctx.db.delete(g)
    await request.ctx.db.commit()
    return ok({"deleted": True})
