"""Customer balance ORM model."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Balance(BaseModel):
    """Per-currency balance for a customer."""

    __tablename__ = "balances"

    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))

    __table_args__ = (
        UniqueConstraint("customer_id", "currency", name="uq_balance_customer_currency"),
        CheckConstraint("amount >= 0", name="ck_balance_non_negative"),
    )
