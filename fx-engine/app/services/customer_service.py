"""Customer and balance business logic."""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.currency import SUPPORTED_CURRENCIES
from app.core.exceptions import (
    CustomerNotFoundError,
    DuplicateEmailError,
    InvalidAmountError,
    UnsupportedCurrencyError,
)
from app.models.balance import Balance
from app.models.customer import Customer

MAX_PAGE_LIMIT = 100


def create_customer(db: Session, name: str, email: str) -> Customer:
    """Create a customer and zero balances for all supported currencies."""
    customer = Customer(name=name, email=email)
    db.add(customer)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateEmailError(f"Customer with email {email} already exists") from exc

    for currency in sorted(SUPPORTED_CURRENCIES):
        db.add(Balance(customer_id=customer.id, currency=currency, amount=Decimal("0")))

    db.commit()
    db.refresh(customer)
    return customer


def list_customers(
    db: Session,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Customer], int]:
    """Return a paginated list of customers and the total count."""
    bounded_limit = min(max(limit, 1), MAX_PAGE_LIMIT)
    bounded_skip = max(skip, 0)

    total = db.scalar(select(func.count()).select_from(Customer)) or 0
    customers = list(
        db.scalars(
            select(Customer)
            .order_by(Customer.created_at.desc())
            .offset(bounded_skip)
            .limit(bounded_limit)
        )
    )
    return customers, total


def get_balances(db: Session, customer_id: str) -> list[Balance]:
    """Return all balances for a customer."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFoundError(f"Customer {customer_id} not found")

    return list(
        db.scalars(
            select(Balance)
            .where(Balance.customer_id == customer_id)
            .order_by(Balance.currency)
        )
    )


def credit_balance(
    db: Session,
    customer_id: str,
    currency: str,
    amount: Decimal,
) -> tuple[Balance, Decimal]:
    """Credit a customer balance and return the updated row and previous amount."""
    currency = currency.upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(f"Unsupported currency: {currency}")
    if amount <= 0:
        raise InvalidAmountError("Amount must be greater than zero")

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise CustomerNotFoundError(f"Customer {customer_id} not found")

    balance = db.scalar(
        select(Balance).where(
            Balance.customer_id == customer_id,
            Balance.currency == currency,
        )
    )
    if balance is None:
        raise CustomerNotFoundError(f"Balance for customer {customer_id} not found")

    previous_amount = balance.amount
    balance.amount = previous_amount + amount
    db.commit()
    db.refresh(balance)
    return balance, previous_amount
