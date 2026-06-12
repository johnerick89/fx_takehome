"""Exchange rate API routes."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.rate import (
    RateListResponse,
    RateResponse,
    SpreadResponse,
    SpreadUpdateRequest,
)
from app.services.rate_service import get_rate, list_cached_rates, refresh_rates, update_spread

router = APIRouter(prefix="/api/v1/rates", tags=["rates"])


@router.get("", response_model=RateListResponse)
def list_rates_endpoint(db: Session = Depends(get_db)) -> RateListResponse:
    """List all cached direct exchange rates."""
    cached_rates, age_seconds, stale, _blocked = list_cached_rates(db)
    responses: list[RateResponse] = []
    latest_fetched_at = None

    for cached_rate in cached_rates:
        rate = get_rate(db, cached_rate.base_currency, cached_rate.quote_currency)
        responses.append(
            RateResponse(
                base_currency=cached_rate.base_currency,
                quote_currency=cached_rate.quote_currency,
                mid_rate=rate.mid_rate,
                buy_rate=rate.buy_rate,
                sell_rate=rate.sell_rate,
                fetched_at=rate.fetched_at,
            )
        )
        if latest_fetched_at is None or rate.fetched_at > latest_fetched_at:
            latest_fetched_at = rate.fetched_at

    return RateListResponse(
        rates=responses,
        fetched_at=latest_fetched_at,
        age_seconds=age_seconds,
        stale=stale,
    )


@router.post("/refresh")
def refresh_rates_endpoint(db: Session = Depends(get_db)) -> dict[str, str]:
    """Trigger a manual exchange rate refresh."""
    refresh_rates(db)
    return {"status": "ok"}


@router.put("/spreads/{base}/{quote}", response_model=SpreadResponse)
def update_spread_endpoint(
    base: str,
    quote: str,
    payload: SpreadUpdateRequest,
    db: Session = Depends(get_db),
) -> SpreadResponse:
    """Update buy and sell spreads for a currency pair."""
    spread = update_spread(
        db,
        base,
        quote,
        Decimal(payload.buy_spread),
        Decimal(payload.sell_spread),
    )
    return SpreadResponse.model_validate(spread)
