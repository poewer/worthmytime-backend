"""Centrum alertów: GET /alerts oraz POST /alerts/{key}/dismiss."""

from urllib.parse import unquote

from sanic import Blueprint, Request
from sqlalchemy import select

from . import alerts as rules
from .errors import ApiError
from .helpers import load_loans, load_plan, login_required, ok, rate_from_user, today
from .models import AlertDismissal, Expense, SavingsGoal, User, WishlistItem
from .planning import month_bounds, period_of, remaining_installments
from .routes_planning import _goal, _hourly_rate, _wish

bp = Blueprint("alerts", url_prefix="/api/v1")


async def compute_alerts(request: Request, user: User) -> list[dict]:
    """Wszystkie aktualne alerty użytkownika (bez uwzględnienia ukrytych)."""
    db, now = request.ctx.db, today()
    found: list[dict] = []

    has_rate = user.hourly_rate is not None or user.monthly_income is not None
    if has_rate:
        plan = await load_plan(request, user, rate_from_user(user).monthly_income)
        found += rules.rule_category_usage(plan)
        found += rules.rule_budget_deficit(plan)

    loans = await load_loans(request, user)
    start, _ = month_bounds(period_of(now))
    paid_rows = await db.execute(
        select(Expense.source_id, Expense.spent_on).where(
            Expense.user_id == user.id, Expense.source_type == "LOAN", Expense.spent_on >= start
        )
    )
    paid = {(source_id, spent_on.strftime("%Y-%m")) for source_id, spent_on in paid_rows}
    found += rules.rule_loan_due(
        [
            rules.LoanDue(
                id=loan.id,
                name=loan.name,
                installment_amount=loan.installment_amount,
                payment_day=loan.payment_day,
                has_installments_left=remaining_installments(
                    now, loan.installments_left, loan.end_date, loan.payment_day
                )
                > 0,
            )
            for loan in loans
        ],
        paid,
        now,
    )

    goals = list(await db.scalars(select(SavingsGoal).where(SavingsGoal.user_id == user.id)))
    hourly = _hourly_rate(user)
    states = []
    for g in goals:
        view = _goal(g, hourly)
        states.append(
            rules.GoalState(
                id=g.id,
                name=g.name,
                completed=view["completed"],
                target_date=g.target_date,
                on_track=view["on_track"],
                remaining=view["remaining"],
                required_monthly=view["required_monthly"],
            )
        )
    found += rules.rule_goal_schedule(states, now)

    if has_rate:
        rate = rate_from_user(user)
        wishes = await db.scalars(select(WishlistItem).where(WishlistItem.user_id == user.id))
        found += rules.rule_wish_ready([_wish(w, rate) for w in wishes])

    return rules.sort_alerts(found)


async def _dismissed(request: Request, user: User) -> dict[str, str]:
    rows = await request.ctx.db.scalars(select(AlertDismissal).where(AlertDismissal.user_id == user.id))
    return {d.key: d.state for d in rows}


@bp.get("/alerts")
@login_required
async def list_alerts(request: Request):
    user = request.ctx.user
    items = rules.visible(await compute_alerts(request, user), await _dismissed(request, user))
    levels = (rules.CRITICAL, rules.WARNING, rules.INFO)
    counts = {level: sum(1 for a in items if a["level"] == level) for level in levels}
    return ok({"items": items, "count": len(items), "counts": counts})


@bp.post("/alerts/<key:str>/dismiss")
@login_required
async def dismiss_alert(request: Request, key: str):
    """Ukrywa alert do zmiany jego stanu (np. przejścia z 80% na 100% budżetu kategorii)."""
    key = unquote(key)  # klient koduje dwukropek z klucza (CATEGORY_USAGE%3AFUN); parametr ścieżki zostaje zakodowany
    user, db = request.ctx.user, request.ctx.db
    current = next((a for a in await compute_alerts(request, user) if a["key"] == key), None)
    if current is None:
        raise ApiError("Nie znaleziono alertu", 404)
    row = await db.scalar(select(AlertDismissal).where(AlertDismissal.user_id == user.id, AlertDismissal.key == key))
    if row is None:
        db.add(AlertDismissal(user_id=user.id, key=key, state=current["state"]))
    else:
        row.state = current["state"]
    await db.commit()
    return ok({"dismissed": key})
