"""FX transaction ORM model."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Transaction(BaseModel):
    """Completed FX execution record."""

    __tablename__ = "transactions"

    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), unique=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3))
    debited_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    credited_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
