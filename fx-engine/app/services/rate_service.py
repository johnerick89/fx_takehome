"""Exchange rate caching, spread application, and staleness policy."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.currency import ROUNDING_MODE, SUPPORTED_CURRENCIES
from app.core.exceptions import RateProviderError, RatesStaleError, SpreadNotFoundError
from app.core.logging import get_logger
from app.core.rates import (
    DIRECT_PAIRS,
    RATE_DECIMAL_PLACES,
    STALE_BLOCK_SECONDS,
    STALE_WARN_SECONDS,
)
from app.models.corridor_spread import CorridorSpread
from app.models.exchange_rate import ExchangeRate
from app.services.rate_providers import USD_QUOTE_CURRENCIES, RateProvider, get_rate_providers

logger = get_logger(__name__)


@dataclass
class RateResult:
    """Resolved rate with spread and staleness metadata."""

    mid_rate: Decimal
    buy_rate: Decimal
    sell_rate: Decimal
    fetched_at: datetime
    age_seconds: int
    stale: bool
    blocked: bool


def _quantize_rate(value: Decimal) -> Decimal:
    """Round a rate to the configured storage precision."""
    quantizer = Decimal("1").scaleb(-RATE_DECIMAL_PLACES)
    return value.quantize(quantizer, rounding=ROUNDING_MODE)


def _classify_age(age_seconds: int | None) -> tuple[bool, bool]:
    """Return stale and blocked flags for a rate age."""
    if age_seconds is None:
        return True, True
    if age_seconds > STALE_BLOCK_SECONDS:
        return True, True
    if age_seconds > STALE_WARN_SECONDS:
        return True, False
    return False, False


def build_pair_rates(usd_quotes: dict[str, Decimal]) -> dict[tuple[str, str], Decimal]:
    """Build mid rates for all supported ordered pairs from USD quotes."""
    pair_rates: dict[tuple[str, str], Decimal] = {}

    for quote in usd_quotes:
        pair_rates[("USD", quote)] = _quantize_rate(usd_quotes[quote])
        pair_rates[(quote, "USD")] = _quantize_rate(Decimal("1") / usd_quotes[quote])

    non_usd = sorted(usd_quotes)
    for base in non_usd:
        for quote in non_usd:
            if base == quote:
                continue
            pair_rates[(base, quote)] = _quantize_rate(usd_quotes[quote] / usd_quotes[base])

    return pair_rates


def refresh_rates(db: Session, providers: list[RateProvider] | None = None) -> None:
    """Fetch rates from external providers and upsert the local cache."""
    started_at = time.perf_counter()
    provider_list = providers if providers is not None else get_rate_providers()
    last_error: Exception | None = None

    for provider in provider_list:
        try:
            usd_quotes = provider.fetch_rates()
            missing = [code for code in USD_QUOTE_CURRENCIES if code not in usd_quotes]
            if missing:
                raise RateProviderError(f"Missing currencies in provider response: {missing}")
            pair_rates = build_pair_rates(usd_quotes)
            fetched_at = datetime.now(UTC)
            _upsert_rates(db, pair_rates, fetched_at)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "rates.refresh.success",
                extra={
                    "event": "rates.refresh.success",
                    "pairs": len(pair_rates),
                    "duration_ms": duration_ms,
                },
            )
            return
        except (RateProviderError, Exception) as exc:
            last_error = exc
            logger.warning(
                "rates.refresh.provider_failed",
                extra={"event": "rates.refresh.provider_failed", "error": str(exc)},
            )

    if last_error is not None:
        logger.error(
            "rates.refresh.failed",
            extra={"event": "rates.refresh.failed", "error": str(last_error)},
        )


def _upsert_rates(
    db: Session,
    pair_rates: dict[tuple[str, str], Decimal],
    fetched_at: datetime,
) -> None:
    """Insert or update cached exchange rates."""
    for (base_currency, quote_currency), mid_rate in pair_rates.items():
        existing = db.scalar(
            select(ExchangeRate).where(
                ExchangeRate.base_currency == base_currency,
                ExchangeRate.quote_currency == quote_currency,
            )
        )
        if existing is None:
            db.add(
                ExchangeRate(
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    mid_rate=mid_rate,
                    fetched_at=fetched_at,
                )
            )
        else:
            existing.mid_rate = mid_rate
            existing.fetched_at = fetched_at

    db.commit()


def get_rates_age_seconds(db: Session) -> int | None:
    """Return the age in seconds of the most recently fetched rate."""
    latest = db.scalar(select(func.max(ExchangeRate.fetched_at)))
    if latest is None:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - latest).total_seconds()), 0)


def _get_exchange_rate_row(
    db: Session,
    base: str,
    quote: str,
) -> tuple[ExchangeRate, bool]:
    """Return an exchange rate row, inverting if needed."""
    base = base.upper()
    quote = quote.upper()
    row = db.scalar(
        select(ExchangeRate).where(
            ExchangeRate.base_currency == base,
            ExchangeRate.quote_currency == quote,
        )
    )
    if row is not None:
        return row, False

    inverse = db.scalar(
        select(ExchangeRate).where(
            ExchangeRate.base_currency == quote,
            ExchangeRate.quote_currency == base,
        )
    )
    if inverse is None:
        raise RatesStaleError(f"No cached rate for {base}/{quote}")

    synthetic = ExchangeRate(
        base_currency=base,
        quote_currency=quote,
        mid_rate=_quantize_rate(Decimal("1") / inverse.mid_rate),
        fetched_at=inverse.fetched_at,
    )
    return synthetic, True


def _get_spread_row(db: Session, base: str, quote: str) -> CorridorSpread:
    """Return spread configuration for a pair, using inverse if needed."""
    spread = db.scalar(
        select(CorridorSpread).where(
            CorridorSpread.base_currency == base,
            CorridorSpread.quote_currency == quote,
        )
    )
    if spread is not None:
        return spread

    inverse = db.scalar(
        select(CorridorSpread).where(
            CorridorSpread.base_currency == quote,
            CorridorSpread.quote_currency == base,
        )
    )
    if inverse is None:
        raise SpreadNotFoundError(f"No spread configured for {base}/{quote}")

    return inverse


def get_rate(db: Session, base: str, quote: str) -> RateResult:
    """Return spread-inclusive rates and staleness metadata for a pair."""
    base = base.upper()
    quote = quote.upper()
    if base not in SUPPORTED_CURRENCIES or quote not in SUPPORTED_CURRENCIES:
        raise RatesStaleError(f"Unsupported currency pair {base}/{quote}")

    row, _ = _get_exchange_rate_row(db, base, quote)
    spread = _get_spread_row(db, base, quote)

    fetched_at = row.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    age_seconds = max(int((datetime.now(UTC) - fetched_at).total_seconds()), 0)
    stale, blocked = _classify_age(age_seconds)

    mid_rate = row.mid_rate
    buy_rate = _quantize_rate(mid_rate * (Decimal("1") + spread.buy_spread))
    sell_rate = _quantize_rate(mid_rate * (Decimal("1") - spread.sell_spread))

    return RateResult(
        mid_rate=mid_rate,
        buy_rate=buy_rate,
        sell_rate=sell_rate,
        fetched_at=fetched_at,
        age_seconds=age_seconds,
        stale=stale,
        blocked=blocked,
    )


def list_cached_rates(db: Session) -> tuple[list[ExchangeRate], int | None, bool, bool]:
    """Return cached rates and global staleness metadata."""
    rates = list(
        db.scalars(
            select(ExchangeRate).order_by(
                ExchangeRate.base_currency,
                ExchangeRate.quote_currency,
            )
        )
    )
    age_seconds = get_rates_age_seconds(db)
    stale, blocked = _classify_age(age_seconds)
    return rates, age_seconds, stale, blocked


def update_spread(
    db: Session,
    base: str,
    quote: str,
    buy_spread: Decimal,
    sell_spread: Decimal,
) -> CorridorSpread:
    """Update spread configuration for a currency pair."""
    base = base.upper()
    quote = quote.upper()
    spread = db.scalar(
        select(CorridorSpread).where(
            CorridorSpread.base_currency == base,
            CorridorSpread.quote_currency == quote,
        )
    )
    if spread is None:
        raise SpreadNotFoundError(f"No spread configured for {base}/{quote}")

    spread.buy_spread = buy_spread
    spread.sell_spread = sell_spread
    db.commit()
    db.refresh(spread)
    return spread


def seed_corridor_spreads(db: Session) -> None:
    """Seed default spreads for all direct pairs when missing."""
    default_spread = Decimal("0.005")
    for base_currency, quote_currency in DIRECT_PAIRS:
        existing = db.scalar(
            select(CorridorSpread).where(
                CorridorSpread.base_currency == base_currency,
                CorridorSpread.quote_currency == quote_currency,
            )
        )
        if existing is None:
            db.add(
                CorridorSpread(
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    buy_spread=default_spread,
                    sell_spread=default_spread,
                )
            )
    db.commit()
