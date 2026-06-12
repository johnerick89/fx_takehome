"""Quote Pydantic schemas."""

import json
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.currency import DECIMAL_PLACES, ROUNDING_MODE
from app.core.rates import RATE_DECIMAL_PLACES
from app.schemas.customer import _serialize_decimal_amount


def _serialize_rate(value: Decimal) -> str:
    """Serialize an exchange rate with fixed precision."""
    quantizer = Decimal("1").scaleb(-RATE_DECIMAL_PLACES)
    quantized = value.quantize(quantizer, rounding=ROUNDING_MODE)
    return f"{quantized:.{RATE_DECIMAL_PLACES}f}"


class QuoteCreate(BaseModel):
    """Request body for generating a quote."""

    customer_id: str
    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str = Field(min_length=3, max_length=3)
    amount: str
    amount_side: Literal["source", "destination"]

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        """Ensure amount is a valid decimal."""
        Decimal(value)
        return value


class QuoteResponse(BaseModel):
    """Quote returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    quote_id: str = Field(validation_alias="id")
    customer_id: str
    from_currency: str
    to_currency: str
    source_amount: Decimal
    destination_amount: Decimal
    exchange_rate: Decimal
    rate_includes_spread: bool = True
    routing_path: list[str]
    stale: bool = Field(validation_alias="stale_rate")
    expires_at: datetime
    created_at: datetime

    @field_serializer("source_amount")
    def serialize_source_amount(self, value: Decimal) -> str:
        """Serialize source amount with currency precision."""
        return _serialize_decimal_amount(value, self.from_currency)

    @field_serializer("destination_amount")
    def serialize_destination_amount(self, value: Decimal) -> str:
        """Serialize destination amount with currency precision."""
        return _serialize_decimal_amount(value, self.to_currency)

    @field_serializer("exchange_rate")
    def serialize_exchange_rate(self, value: Decimal) -> str:
        """Serialize exchange rate as a string."""
        return _serialize_rate(value)

    @classmethod
    def from_quote(cls, quote: object) -> "QuoteResponse":
        """Build a response from a quote ORM object."""
        routing_path = json.loads(getattr(quote, "routing_path"))
        data = {
            "id": getattr(quote, "id"),
            "customer_id": getattr(quote, "customer_id"),
            "from_currency": getattr(quote, "from_currency"),
            "to_currency": getattr(quote, "to_currency"),
            "source_amount": getattr(quote, "source_amount"),
            "destination_amount": getattr(quote, "destination_amount"),
            "exchange_rate": getattr(quote, "exchange_rate"),
            "routing_path": routing_path,
            "stale_rate": getattr(quote, "stale_rate"),
            "expires_at": getattr(quote, "expires_at"),
            "created_at": getattr(quote, "created_at"),
        }
        return cls.model_validate(data)
