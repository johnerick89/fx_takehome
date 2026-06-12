"""Quote generation business logic."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.currency import DECIMAL_PLACES, ROUNDING_MODE, SUPPORTED_CURRENCIES
from app.core.exceptions import (
    CustomerNotFoundError,
    InvalidAmountError,
    InvalidCurrencyPairError,
    RatesStaleError,
    UnsupportedCurrencyError,
)
from app.models.customer import Customer
from app.models.quote import Quote, QuoteStatus
from app.services.routing_service import RoutingResult, resolve_route

QUOTE_TTL_SECONDS = 60


def _quantize_amount(amount: Decimal, currency: str) -> Decimal:
    """Round an amount to the currency's decimal places."""
    places = DECIMAL_PLACES[currency]
    quantizer = Decimal("1").scaleb(-places)
    return amount.quantize(quantizer, rounding=ROUNDING_MODE)


def _calculate_amounts(
    routing: RoutingResult,
    amount: Decimal,
    amount_side: str,
    from_currency: str,
    to_currency: str,
) -> tuple[Decimal, Decimal]:
    """Compute source and destination amounts from routing legs."""
    if amount_side == "source":
        source_amount = _quantize_amount(amount, from_currency)
        working = source_amount
        for leg in routing.legs:
            working *= leg.rate
        destination_amount = _quantize_amount(working, to_currency)
        return source_amount, destination_amount

    destination_amount = _quantize_amount(amount, to_currency)
    working = destination_amount
    for leg in reversed(routing.legs):
        working /= leg.rate
    source_amount = _quantize_amount(working, from_currency)
    return source_amount, destination_amount


def _verify_direct_pair_invariant(
    routing: RoutingResult,
    source_amount: Decimal,
    destination_amount: Decimal,
    to_currency: str,
) -> None:
    """Ensure direct-pair rounding invariant holds exactly."""
    if len(routing.path) != 2:
        return

    expected_destination = _quantize_amount(
        source_amount * routing.effective_rate,
        to_currency,
    )
    if expected_destination != destination_amount:
        raise InvalidAmountError(
            "Quote amount invariant failed after rounding for direct pair"
        )


def create_quote(
    db: Session,
    customer_id: str,
    from_currency: str,
    to_currency: str,
    amount: Decimal,
    amount_side: str,
) -> Quote:
    """Generate a quote with routing, spreads, and 60-second expiry."""
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFoundError(f"Customer {customer_id} not found")

    if from_currency not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(f"Unsupported currency: {from_currency}")
    if to_currency not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(f"Unsupported currency: {to_currency}")
    if from_currency == to_currency:
        raise InvalidCurrencyPairError("Source and destination currencies must differ")
    if amount <= 0:
        raise InvalidAmountError("Amount must be greater than zero")
    if amount_side not in {"source", "destination"}:
        raise InvalidAmountError("amount_side must be 'source' or 'destination'")

    routing = resolve_route(db, from_currency, to_currency)
    if routing.blocked:
        raise RatesStaleError("Cached rates are too old to generate quotes")

    source_amount, destination_amount = _calculate_amounts(
        routing,
        amount,
        amount_side,
        from_currency,
        to_currency,
    )
    _verify_direct_pair_invariant(
        routing,
        source_amount,
        destination_amount,
        to_currency,
    )

    quote = Quote(
        customer_id=customer_id,
        from_currency=from_currency,
        to_currency=to_currency,
        source_amount=source_amount,
        destination_amount=destination_amount,
        exchange_rate=routing.effective_rate,
        routing_path=json.dumps(routing.path),
        status=QuoteStatus.PENDING.value,
        stale_rate=routing.stale,
        expires_at=datetime.now(UTC) + timedelta(seconds=QUOTE_TTL_SECONDS),
    )
    db.add(quote)
    db.flush()

    created_at = quote.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    quote.expires_at = created_at + timedelta(seconds=QUOTE_TTL_SECONDS)

    db.commit()
    db.refresh(quote)
    return quote
