"""Transaction API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.execute import ExecuteResponse
from app.services.execute_service import get_transaction

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


@router.get("/{transaction_id}", response_model=ExecuteResponse)
def get_transaction_endpoint(
    transaction_id: str,
    db: Session = Depends(get_db),
) -> ExecuteResponse:
    """Return a completed transaction."""
    transaction = get_transaction(db, transaction_id)
    return ExecuteResponse.from_transaction(transaction)
