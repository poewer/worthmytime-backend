import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="PLN")
    monthly_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    hourly_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    hours_per_day: Mapped[float] = mapped_column(Float, default=8.0)
    days_per_week: Mapped[float] = mapped_column(Float, default=5.0)
    commute_minutes_per_day: Mapped[float] = mapped_column(Float, default=0.0)
    work_costs_monthly: Mapped[float] = mapped_column(Float, default=0.0)
    rate_mode: Mapped[str] = mapped_column(String(7), default="NOMINAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    calculations: Mapped[list["Calculation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Calculation(Base):
    __tablename__ = "calculations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))  # SIMPLE | RECURRING | TCO
    purchase_price: Mapped[float] = mapped_column(Float, default=0.0)
    ownership_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    resale_value: Mapped[float] = mapped_column(Float, default=0.0)
    # Migawka profilu z chwili zapisu - wynik jest stabilny, a strona publiczna
    # nie musi sięgać do profilu użytkownika.
    currency: Mapped[str] = mapped_column(String(3), default="PLN")
    hourly_rate: Mapped[float] = mapped_column(Float)
    hours_per_day: Mapped[float] = mapped_column(Float, default=8.0)
    days_per_week: Mapped[float] = mapped_column(Float, default=5.0)
    expected_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_income: Mapped[float | None] = mapped_column(Float, nullable=True)  # migawka dochodu netto
    category: Mapped[str | None] = mapped_column(String(10), nullable=True)
    already_saved: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    public_id: Mapped[str | None] = mapped_column(String(16), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="calculations")
    costs: Mapped[list["Cost"]] = relationship(
        back_populates="calculation",
        cascade="all, delete-orphan",
        order_by="Cost.position",
        lazy="selectin",
    )


class Cost(Base):
    __tablename__ = "costs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    calculation_id: Mapped[str] = mapped_column(
        ForeignKey("calculations.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float)
    frequency: Mapped[str] = mapped_column(String(10))  # ONE_TIME|DAILY|WEEKLY|MONTHLY|YEARLY

    calculation: Mapped[Calculation] = relationship(back_populates="costs")


class BudgetLoan(Base):
    """Kredyt lub pożyczka użytkownika; suma rat to zobowiązanie w kategorii NEEDS."""

    __tablename__ = "budget_loans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(100))
    installment_amount: Mapped[float] = mapped_column(Float)
    installments_left: Mapped[int] = mapped_column(Integer)
    loan_amount: Mapped[float | None] = mapped_column(Float, nullable=True)


class Budget(Base):
    """Plan budżetu użytkownika: procenty kategorii i wydatki w bieżącym miesiącu."""

    __tablename__ = "budgets"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    pct_needs: Mapped[float] = mapped_column(Float, default=50.0)
    pct_future: Mapped[float] = mapped_column(Float, default=25.0)
    pct_goals: Mapped[float] = mapped_column(Float, default=15.0)
    pct_fun: Mapped[float] = mapped_column(Float, default=10.0)
    spent_needs: Mapped[float] = mapped_column(Float, default=0.0)
    spent_future: Mapped[float] = mapped_column(Float, default=0.0)
    spent_goals: Mapped[float] = mapped_column(Float, default=0.0)
    spent_fun: Mapped[float] = mapped_column(Float, default=0.0)
    # miesiąc (YYYY-MM), którego dotyczą ręczne kwoty spent_*; po zmianie miesiąca wygasają
    spent_period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

class Expense(Base):
    """Wydatek zapisany w rejestrze; sumy z bieżącego miesiąca zasilają "wydane" w kategoriach budżetu."""

    __tablename__ = "expenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(10))
    amount: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    spent_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WishlistItem(Base):
    """Rzecz, którą użytkownik chce kupić, z okresem ostygnięcia na przemyślenie decyzji."""

    __tablename__ = "wishlist_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[float] = mapped_column(Float)
    category: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cooldown_days: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(10), default="WAITING")  # WAITING | BOUGHT | DROPPED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavingsGoal(Base):
    """Trwały cel oszczędnościowy z postępem."""

    __tablename__ = "savings_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_amount: Mapped[float] = mapped_column(Float)
    saved_amount: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)