"""Exchange rate Pydantic schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app.core.rates import RATE_DECIMAL_PLACES
from app.core.currency import ROUNDING_MODE


def _serialize_rate(value: Decimal) -> str:
    """Serialize an exchange rate with fixed precision."""
    quantizer = Decimal("1").scaleb(-RATE_DECIMAL_PLACES)
    quantized = value.quantize(quantizer, rounding=ROUNDING_MODE)
    return f"{quantized:.{RATE_DECIMAL_PLACES}f}"


class RateResponse(BaseModel):
    """Single cached exchange rate with spreads applied."""

    model_config = ConfigDict(from_attributes=True)

    base_currency: str
    quote_currency: str
    mid_rate: Decimal
    buy_rate: Decimal
    sell_rate: Decimal
    fetched_at: datetime

    @field_serializer("mid_rate", "buy_rate", "sell_rate")
    def serialize_rates(self, value: Decimal) -> str:
        """Serialize rates as strings."""
        return _serialize_rate(value)


class RateListResponse(BaseModel):
    """All cached exchange rates."""

    rates: list[RateResponse]
    fetched_at: datetime | None
    age_seconds: int | None
    stale: bool


class SpreadUpdateRequest(BaseModel):
    """Request body for updating corridor spreads."""

    buy_spread: str
    sell_spread: str

    @field_validator("buy_spread", "sell_spread")
    @classmethod
    def validate_spread(cls, value: str) -> str:
        """Ensure spread values are valid decimals."""
        Decimal(value)
        return value


class SpreadResponse(BaseModel):
    """Corridor spread configuration."""

    model_config = ConfigDict(from_attributes=True)

    base_currency: str
    quote_currency: str
    buy_spread: Decimal
    sell_spread: Decimal

    @field_serializer("buy_spread", "sell_spread")
    def serialize_spreads(self, value: Decimal) -> str:
        """Serialize spreads as strings."""
        return _serialize_rate(value)
