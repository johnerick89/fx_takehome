"""Corridor spread ORM model."""

from decimal import Decimal

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class CorridorSpread(BaseModel):
    """Buy and sell spread configuration for a currency pair."""

    __tablename__ = "corridor_spreads"

    base_currency: Mapped[str] = mapped_column(String(3))
    quote_currency: Mapped[str] = mapped_column(String(3))
    buy_spread: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.005"))
    sell_spread: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.005"))

    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", name="uq_spread_pair"),
    )
