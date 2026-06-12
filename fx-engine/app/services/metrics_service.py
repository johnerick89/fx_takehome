"""System metrics business logic."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.exchange_rate import ExchangeRate
from app.models.quote import Quote, QuoteStatus
from app.models.transaction import Transaction
from app.schemas.metrics import MetricsResponse

_executions_failed_total = 0


def increment_executions_failed() -> None:
    """Record a failed execute attempt."""
    global _executions_failed_total
    _executions_failed_total += 1


def reset_executions_failed_counter() -> None:
    """Reset the failed-execution counter (for tests)."""
    global _executions_failed_total
    _executions_failed_total = 0


def get_executions_failed_total() -> int:
    """Return the in-memory failed-execution counter."""
    return _executions_failed_total


def get_metrics(db: Session) -> MetricsResponse:
    """Aggregate system metrics from the database."""
    now = datetime.now(UTC)
    quotes_generated_total = db.scalar(select(func.count()).select_from(Quote)) or 0
    executions_successful_total = (
        db.scalar(select(func.count()).select_from(Transaction)) or 0
    )
    rates_last_updated = db.scalar(select(func.max(ExchangeRate.fetched_at)))
    active_quotes_count = db.scalar(
        select(func.count())
        .select_from(Quote)
        .where(
            Quote.status == QuoteStatus.PENDING.value,
            Quote.expires_at > now,
        )
    ) or 0

    return MetricsResponse(
        quotes_generated_total=quotes_generated_total,
        executions_successful_total=executions_successful_total,
        executions_failed_total=get_executions_failed_total(),
        rates_last_updated=rates_last_updated,
        active_quotes_count=active_quotes_count,
    )
