"""Zarządzanie kontem: zmiana hasła, usunięcie konta i eksport danych (RODO)."""

from datetime import date, datetime

from pydantic import BaseModel, Field
from sanic import Blueprint, Request
from sqlalchemy import delete, select

from .errors import ApiError
from .helpers import login_required, ok, parse, user_profile
from .models import Budget, BudgetLoan, Calculation, Cost, Expense, SavingsGoal, User, WishlistItem
from .security import create_token, hash_password, verify_password

bp = Blueprint("account", url_prefix="/api/v1")

# tabele z danymi użytkownika (poza obliczeniami i ich pozycjami) w kolejności eksportu
USER_TABLES = (
    ("budget", Budget),
    ("loans", BudgetLoan),
    ("expenses", Expense),
    ("wishlist", WishlistItem),
    ("goals", SavingsGoal),
)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)


def _row(obj) -> dict:
    """Wszystkie kolumny wiersza jako słownik JSON (daty w ISO)."""
    out = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name)
        out[col.name] = value.isoformat() if isinstance(value, (date, datetime)) else value
    return out


@bp.post("/auth/change-password")
@login_required
async def change_password(request: Request):
    data = parse(ChangePasswordIn, request)
    user = request.ctx.user
    if not verify_password(data.current_password, user.password_hash):
        raise ApiError("Obecne hasło jest nieprawidłowe", 403)
    if data.new_password == data.current_password:
        raise ApiError("Nowe hasło musi się różnić od obecnego", 422)
    user.password_hash = hash_password(data.new_password)
    await request.ctx.db.commit()
    return ok({"token": create_token(user.id)})


@bp.delete("/account")
@login_required
async def delete_account(request: Request):
    """Usuwa konto razem z całą historią: obliczenia (i publiczne linki), budżet, kredyty, wydatki, życzenia, cele."""
    data = parse(DeleteAccountIn, request)
    user = request.ctx.user
    if not verify_password(data.password, user.password_hash):
        raise ApiError("Hasło jest nieprawidłowe", 403)
    db = request.ctx.db
    calc_ids = select(Calculation.id).where(Calculation.user_id == user.id)
    await db.execute(delete(Cost).where(Cost.calculation_id.in_(calc_ids)))
    for model in (Calculation, Budget, BudgetLoan, Expense, WishlistItem, SavingsGoal):
        await db.execute(delete(model).where(model.user_id == user.id))
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
    return ok({"deleted": True})


@bp.get("/account/export")
@login_required
async def export_account(request: Request):
    """Pełny eksport danych użytkownika w JSON (bez hasha hasła)."""
    user, db = request.ctx.user, request.ctx.db
    calculations = list(await db.scalars(select(Calculation).where(Calculation.user_id == user.id)))
    costs = []
    if calculations:
        costs = list(await db.scalars(select(Cost).where(Cost.calculation_id.in_([c.id for c in calculations]))))
    body = {
        "exported_at": datetime.now().astimezone().isoformat(),
        "account": {
            "id": user.id,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
            **user_profile(user),
        },
        "calculations": [_row(c) for c in calculations],
        "costs": [_row(c) for c in costs],
    }
    for key, model in USER_TABLES:
        rows = list(await db.scalars(select(model).where(model.user_id == user.id)))
        body[key] = [_row(r) for r in rows] if key != "budget" else (_row(rows[0]) if rows else None)
    return ok(body)
