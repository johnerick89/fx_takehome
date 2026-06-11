"""Customer API routes."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.exceptions import (
    CustomerNotFoundError,
    DuplicateEmailError,
    InvalidAmountError,
    UnsupportedCurrencyError,
)
from app.db.session import get_db
from app.schemas.customer import (
    BalanceCreditRequest,
    BalanceCreditResponse,
    BalanceListResponse,
    BalanceResponse,
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
)
from app.services.customer_service import (
    MAX_PAGE_LIMIT,
    create_customer,
    credit_balance,
    get_balances,
    list_customers,
)

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


@router.post("", status_code=201, response_model=CustomerResponse)
def create_customer_endpoint(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
) -> CustomerResponse:
    """Create a new customer with zero balances."""
    try:
        customer = create_customer(db, payload.name, str(payload.email))
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return CustomerResponse.model_validate(customer)


@router.get("", response_model=CustomerListResponse)
def list_customers_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE_LIMIT),
    db: Session = Depends(get_db),
) -> CustomerListResponse:
    """List customers with pagination."""
    customers, total = list_customers(db, skip=skip, limit=limit)
    return CustomerListResponse(
        customers=[CustomerResponse.model_validate(customer) for customer in customers],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{customer_id}/balances", response_model=BalanceListResponse)
def get_balances_endpoint(
    customer_id: str,
    db: Session = Depends(get_db),
) -> BalanceListResponse:
    """Return all balances for a customer."""
    try:
        balances = get_balances(db, customer_id)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return BalanceListResponse(
        customer_id=customer_id,
        balances=[BalanceResponse.model_validate(balance) for balance in balances],
    )


@router.post("/{customer_id}/balances/credit", response_model=BalanceCreditResponse)
def credit_balance_endpoint(
    customer_id: str,
    payload: BalanceCreditRequest,
    db: Session = Depends(get_db),
) -> BalanceCreditResponse:
    """Credit a customer balance."""
    try:
        balance, previous_amount = credit_balance(
            db,
            customer_id,
            payload.currency,
            Decimal(payload.amount),
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except UnsupportedCurrencyError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except InvalidAmountError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    return BalanceCreditResponse(
        currency=balance.currency,
        amount=balance.amount,
        previous_amount=previous_amount,
    )
