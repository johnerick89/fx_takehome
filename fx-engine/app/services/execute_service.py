"""FX quote execution business logic."""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AppError,
    IdempotencyKeyConflictError,
    InsufficientBalanceError,
    MissingIdempotencyKeyError,
    QuoteAlreadyExecutedError,
    QuoteExpiredError,
    QuoteNotFoundError,
    TransactionNotFoundError,
)
from app.core.logging import get_logger
from app.db.transaction import immediate_transaction
from app.models.balance import Balance
from app.models.idempotency_log import IdempotencyLog
from app.models.quote import Quote, QuoteStatus
from app.models.transaction import Transaction
from app.schemas.execute import ExecuteResponse
from app.services.metrics_service import increment_executions_failed

logger = get_logger(__name__)

MAX_IDEMPOTENCY_KEY_LENGTH = 128


@dataclass
class ExecuteResult:
    """Result of an execute or idempotent replay."""

    transaction: Transaction
    is_replay: bool
    http_status: int
    response_body: dict[str, object]


def _validate_idempotency_key(idempotency_key: str | None) -> str:
    """Validate the Idempotency-Key header value."""
    if idempotency_key is None or not idempotency_key.strip():
        raise MissingIdempotencyKeyError("Idempotency-Key header is required")
    if len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise MissingIdempotencyKeyError(
            f"Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters"
        )
    return idempotency_key


def _get_balance_for_update(
    db: Session,
    customer_id: str,
    currency: str,
) -> Balance:
    """Load a balance row with a write lock."""
    balance = db.scalar(
        select(Balance)
        .where(
            Balance.customer_id == customer_id,
            Balance.currency == currency,
        )
        .with_for_update()
    )
    if balance is None:
        raise InsufficientBalanceError(
            f"No balance found for customer {customer_id} in {currency}"
        )
    return balance


def _debit_balance(
    db: Session,
    customer_id: str,
    currency: str,
    amount: Decimal,
) -> None:
    """Debit a customer balance."""
    balance = _get_balance_for_update(db, customer_id, currency)
    if balance.amount < amount:
        raise InsufficientBalanceError(
            f"Insufficient {currency} balance for customer {customer_id}"
        )
    balance.amount -= amount


def _credit_balance(
    db: Session,
    customer_id: str,
    currency: str,
    amount: Decimal,
) -> None:
    """Credit a customer balance."""
    balance = _get_balance_for_update(db, customer_id, currency)
    balance.amount += amount


def _build_response_body(transaction: Transaction) -> dict[str, object]:
    """Serialise a transaction as an API response body."""
    return ExecuteResponse.from_transaction(transaction).model_dump(mode="json")


def _load_idempotency_replay(
    db: Session,
    idempotency_key: str,
    quote_id: str,
) -> ExecuteResult | None:
    """Return a cached idempotent response when the key already exists."""
    existing = db.scalar(
        select(IdempotencyLog).where(IdempotencyLog.idempotency_key == idempotency_key)
    )
    if existing is None:
        return None
    if existing.quote_id != quote_id:
        raise IdempotencyKeyConflictError(
            f"Idempotency key already used for quote {existing.quote_id}"
        )

    transaction = db.get(Transaction, existing.transaction_id)
    if transaction is None:
        raise QuoteNotFoundError(
            f"Transaction {existing.transaction_id} for idempotency replay not found"
        )

    logger.info(
        "execute.idempotent_replay",
        extra={
            "event": "execute.idempotent_replay",
            "action": "replay",
            "quote_id": quote_id,
            "idempotency_key": idempotency_key,
        },
    )
    return ExecuteResult(
        transaction=transaction,
        is_replay=True,
        http_status=200,
        response_body=json.loads(existing.response_body),
    )


def get_transaction(db: Session, transaction_id: str) -> Transaction:
    """Return a transaction by ID."""
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise TransactionNotFoundError(f"Transaction {transaction_id} not found")
    return transaction


def execute_quote(db: Session, quote_id: str, idempotency_key: str | None) -> ExecuteResult:
    """Execute a quote with atomic balance transfer and idempotency."""
    validated_key = _validate_idempotency_key(idempotency_key)
    started_at = time.perf_counter()

    replay = _load_idempotency_replay(db, validated_key, quote_id)
    if replay is not None:
        return replay

    try:
        with immediate_transaction(db):
            replay_inside = _load_idempotency_replay(db, validated_key, quote_id)
            if replay_inside is not None:
                return replay_inside

            quote = db.scalar(
                select(Quote).where(Quote.id == quote_id).with_for_update()
            )
            if quote is None:
                raise QuoteNotFoundError(f"Quote {quote_id} not found")
            if quote.status == QuoteStatus.EXECUTED.value:
                raise QuoteAlreadyExecutedError(f"Quote {quote_id} has already been executed")

            now = datetime.now(UTC)
            expires_at = quote.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < now:
                raise QuoteExpiredError(f"Quote {quote_id} expired at {expires_at.isoformat()}")

            logger.info(
                "execute.started",
                extra={
                    "event": "execute.started",
                    "action": "execute",
                    "quote_id": quote_id,
                    "customer_id": quote.customer_id,
                    "idempotency_key": validated_key,
                },
            )

            _debit_balance(db, quote.customer_id, quote.from_currency, quote.source_amount)
            _credit_balance(db, quote.customer_id, quote.to_currency, quote.destination_amount)

            quote.status = QuoteStatus.EXECUTED.value
            executed_at = datetime.now(UTC)
            transaction = Transaction(
                quote_id=quote.id,
                customer_id=quote.customer_id,
                from_currency=quote.from_currency,
                to_currency=quote.to_currency,
                debited_amount=quote.source_amount,
                credited_amount=quote.destination_amount,
                exchange_rate=quote.exchange_rate,
                idempotency_key=validated_key,
                executed_at=executed_at,
            )
            db.add(transaction)
            db.flush()

            response_body = _build_response_body(transaction)
            db.add(
                IdempotencyLog(
                    idempotency_key=validated_key,
                    quote_id=quote.id,
                    transaction_id=transaction.id,
                    response_status=201,
                    response_body=json.dumps(response_body),
                )
            )
            db.flush()
    except IntegrityError as exc:
        db.rollback()
        replay_after_conflict = _load_idempotency_replay(db, validated_key, quote_id)
        if replay_after_conflict is not None:
            return replay_after_conflict
        raise exc
    except AppError as exc:
        increment_executions_failed()
        logger.warning(
            "execute.failed",
            extra={
                "event": "execute.failed",
                "action": "execute",
                "quote_id": quote_id,
                "error_code": exc.error_code,
            },
        )
        raise

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "execute.success",
        extra={
            "event": "execute.success",
            "action": "execute",
            "quote_id": quote_id,
            "customer_id": transaction.customer_id,
            "debited_amount": str(transaction.debited_amount),
            "credited_amount": str(transaction.credited_amount),
            "duration_ms": duration_ms,
        },
    )

    return ExecuteResult(
        transaction=transaction,
        is_replay=False,
        http_status=201,
        response_body=response_body,
    )
