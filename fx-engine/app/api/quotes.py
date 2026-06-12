"""Quote API routes."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.quote import QuoteCreate, QuoteResponse
from app.services.quote_service import create_quote

router = APIRouter(prefix="/api/v1/quotes", tags=["quotes"])


@router.post("", status_code=201, response_model=QuoteResponse)
def create_quote_endpoint(
    payload: QuoteCreate,
    db: Session = Depends(get_db),
) -> QuoteResponse:
    """Generate an FX quote."""
    quote = create_quote(
        db,
        payload.customer_id,
        payload.from_currency,
        payload.to_currency,
        Decimal(payload.amount),
        payload.amount_side,
    )
    return QuoteResponse.from_quote(quote)
