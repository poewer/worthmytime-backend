import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
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
