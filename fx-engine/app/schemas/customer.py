"""Customer and balance Pydantic schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

from app.core.currency import DECIMAL_PLACES, ROUNDING_MODE


def _serialize_decimal_amount(value: Decimal, currency: str | None = None) -> str:
    """Serialize a decimal amount as a plain string without exponent notation."""
    if currency is not None:
        places = DECIMAL_PLACES.get(currency, 8)
        quantizer = Decimal("1").scaleb(-places)
        quantized = value.quantize(quantizer, rounding=ROUNDING_MODE)
        return f"{quantized:.{places}f}"

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class CustomerCreate(BaseModel):
    """Request body for creating a customer."""

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr


class CustomerResponse(BaseModel):
    """Customer returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    created_at: datetime


class CustomerListResponse(BaseModel):
    """Paginated customer list."""

    customers: list[CustomerResponse]
    total: int
    skip: int
    limit: int


class BalanceResponse(BaseModel):
    """Single currency balance."""

    model_config = ConfigDict(from_attributes=True)

    currency: str
    amount: Decimal

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        """Serialize monetary amounts as strings."""
        return _serialize_decimal_amount(value, self.currency)


class BalanceListResponse(BaseModel):
    """All balances for a customer."""

    customer_id: str
    balances: list[BalanceResponse]


class BalanceCreditRequest(BaseModel):
    """Request body for crediting a balance."""

    currency: str = Field(min_length=3, max_length=3)
    amount: str

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        """Ensure amount is a valid decimal string."""
        Decimal(value)
        return value


class BalanceCreditResponse(BaseModel):
    """Balance after a credit operation."""

    currency: str
    amount: Decimal
    previous_amount: Decimal

    @field_serializer("amount", "previous_amount")
    def serialize_amounts(self, value: Decimal) -> str:
        """Serialize monetary amounts as strings."""
        return _serialize_decimal_amount(value, self.currency)
