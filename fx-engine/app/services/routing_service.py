"""Cross-pair routing and spread-inclusive rate compounding."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.currency import ROUNDING_MODE
from app.core.exceptions import InvalidCurrencyPairError, RouteUnavailableError
from app.core.rates import RATE_DECIMAL_PLACES
from app.models.exchange_rate import ExchangeRate
from app.services.rate_service import RateResult, get_rate


@dataclass
class RateLeg:
    """A single hop in a conversion path with spread-inclusive rate."""

    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_result: RateResult


@dataclass
class RoutingResult:
    """Resolved conversion path with compounded effective rate."""

    path: list[str]
    legs: list[RateLeg]
    effective_rate: Decimal
    stale: bool
    blocked: bool


def _quantize_rate(value: Decimal) -> Decimal:
    """Round a rate to the configured storage precision."""
    quantizer = Decimal("1").scaleb(-RATE_DECIMAL_PLACES)
    return value.quantize(quantizer, rounding=ROUNDING_MODE)


def _has_cached_rate(db: Session, base: str, quote: str) -> bool:
    """Return whether a direct or inverse rate exists in the cache."""
    base = base.upper()
    quote = quote.upper()
    row = db.scalar(
        select(ExchangeRate).where(
            ExchangeRate.base_currency == base,
            ExchangeRate.quote_currency == quote,
        )
    )
    if row is not None:
        return True

    inverse = db.scalar(
        select(ExchangeRate).where(
            ExchangeRate.base_currency == quote,
            ExchangeRate.quote_currency == base,
        )
    )
    return inverse is not None


def _candidate_paths(from_currency: str, to_currency: str) -> list[list[str]]:
    """Return routing candidates in priority order."""
    return [
        [from_currency, to_currency],
        [from_currency, "USD", to_currency],
        [from_currency, "EUR", to_currency],
    ]


def _resolve_path(db: Session, from_currency: str, to_currency: str) -> list[str]:
    """Pick the first viable conversion path."""
    for path in _candidate_paths(from_currency, to_currency):
        if all(_has_cached_rate(db, path[index], path[index + 1]) for index in range(len(path) - 1)):
            return path
    raise RouteUnavailableError(
        f"No route available for {from_currency}/{to_currency}"
    )


def _leg_rate(rate_result: RateResult, *, is_last_leg: bool, is_single_leg: bool) -> Decimal:
    """Choose sell or buy rate for a leg based on position in the path."""
    if is_single_leg:
        return rate_result.sell_rate
    if is_last_leg:
        return rate_result.buy_rate
    return rate_result.sell_rate


def resolve_route(db: Session, from_currency: str, to_currency: str) -> RoutingResult:
    """Resolve routing and spread-inclusive leg rates for a conversion."""
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        raise InvalidCurrencyPairError("Source and destination currencies must differ")

    path = _resolve_path(db, from_currency, to_currency)
    legs: list[RateLeg] = []
    stale = False
    blocked = False
    is_single_leg = len(path) == 2

    for index in range(len(path) - 1):
        leg_base = path[index]
        leg_quote = path[index + 1]
        rate_result = get_rate(db, leg_base, leg_quote)
        is_last_leg = index == len(path) - 2
        applied_rate = _leg_rate(
            rate_result,
            is_last_leg=is_last_leg,
            is_single_leg=is_single_leg,
        )
        legs.append(
            RateLeg(
                base_currency=leg_base,
                quote_currency=leg_quote,
                rate=applied_rate,
                rate_result=rate_result,
            )
        )
        stale = stale or rate_result.stale
        blocked = blocked or rate_result.blocked

    effective_rate = legs[0].rate
    for leg in legs[1:]:
        effective_rate *= leg.rate
    effective_rate = _quantize_rate(effective_rate)

    return RoutingResult(
        path=path,
        legs=legs,
        effective_rate=effective_rate,
        stale=stale,
        blocked=blocked,
    )
