"""Quote ORM model."""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class QuoteStatus(str, Enum):
    """Lifecycle status of a quote."""

    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class Quote(BaseModel):
    """FX quote with routing path and expiry."""

    __tablename__ = "quotes"

    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3))
    source_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    destination_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    routing_path: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=QuoteStatus.PENDING.value)
    stale_rate: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
