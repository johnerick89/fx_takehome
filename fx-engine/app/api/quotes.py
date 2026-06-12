"""Quote API routes."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.quote import QuoteCreate, QuoteResponse
from app.services.execute_service import execute_quote
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


@router.post("/{quote_id}/execute")
def execute_quote_endpoint(
    quote_id: str,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    """Execute a quote atomically."""
    result = execute_quote(db, quote_id, idempotency_key)
    headers: dict[str, str] = {}
    if result.http_status == 201:
        headers["Location"] = f"/api/v1/transactions/{result.transaction.id}"
    return JSONResponse(
        status_code=result.http_status,
        content=result.response_body,
        headers=headers,
    )
