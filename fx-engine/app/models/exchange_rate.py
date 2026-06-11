"""Exchange rate ORM model."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ExchangeRate(BaseModel):
    """Cached mid-market rate for a currency pair."""

    __tablename__ = "exchange_rates"

    base_currency: Mapped[str] = mapped_column(String(3))
    quote_currency: Mapped[str] = mapped_column(String(3))
    mid_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", name="uq_rate_pair"),
    )
