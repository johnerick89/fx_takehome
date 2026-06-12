"""Execute and transaction Pydantic schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.currency import DECIMAL_PLACES, ROUNDING_MODE
from app.core.rates import RATE_DECIMAL_PLACES
from app.schemas.customer import _serialize_decimal_amount


def _serialize_rate(value: Decimal) -> str:
    """Serialize an exchange rate with fixed precision."""
    quantizer = Decimal("1").scaleb(-RATE_DECIMAL_PLACES)
    quantized = value.quantize(quantizer, rounding=ROUNDING_MODE)
    return f"{quantized:.{RATE_DECIMAL_PLACES}f}"


class ExecuteResponse(BaseModel):
    """Successful FX execution response."""

    model_config = ConfigDict(from_attributes=True)

    transaction_id: str = Field(validation_alias="id")
    quote_id: str
    customer_id: str
    from_currency: str
    to_currency: str
    debited_amount: Decimal
    credited_amount: Decimal
    exchange_rate: Decimal
    executed_at: datetime
    idempotency_key: str

    @field_serializer("debited_amount")
    def serialize_debited_amount(self, value: Decimal) -> str:
        """Serialize debited amount with currency precision."""
        return _serialize_decimal_amount(value, self.from_currency)

    @field_serializer("credited_amount")
    def serialize_credited_amount(self, value: Decimal) -> str:
        """Serialize credited amount with currency precision."""
        return _serialize_decimal_amount(value, self.to_currency)

    @field_serializer("exchange_rate")
    def serialize_exchange_rate(self, value: Decimal) -> str:
        """Serialize exchange rate as a string."""
        return _serialize_rate(value)

    @classmethod
    def from_transaction(cls, transaction: object) -> "ExecuteResponse":
        """Build a response from a transaction ORM object."""
        return cls.model_validate(transaction)
