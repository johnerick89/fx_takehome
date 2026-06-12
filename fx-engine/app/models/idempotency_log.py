"""Idempotency log ORM model."""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class IdempotencyLog(BaseModel):
    """Stored idempotent execute responses."""

    __tablename__ = "idempotency_log"

    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    quote_id: Mapped[str] = mapped_column(String(36))
    transaction_id: Mapped[str] = mapped_column(String(36))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)
