"""Health check business logic."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rates import STALE_BLOCK_SECONDS, STALE_WARN_SECONDS
from app.services.rate_service import get_rates_age_seconds


@dataclass
class HealthResult:
    """Computed health status."""

    status: str
    db: str
    rates_age_seconds: int | None
    rates_status: str


def check_db(db: Session) -> str:
    """Return database connectivity status."""
    try:
        db.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def classify_rates(age_seconds: int | None) -> str:
    """Map rate age to a health status label."""
    if age_seconds is None:
        return "unavailable"
    if age_seconds < STALE_WARN_SECONDS:
        return "fresh"
    if age_seconds <= STALE_BLOCK_SECONDS:
        return "stale"
    return "unavailable"


def get_health(db: Session) -> HealthResult:
    """Compute overall application health."""
    db_status = check_db(db)
    rates_age = get_rates_age_seconds(db)
    rates_status = classify_rates(rates_age)
    overall = "ok" if db_status == "ok" and rates_status != "unavailable" else "degraded"
    return HealthResult(
        status=overall,
        db=db_status,
        rates_age_seconds=rates_age,
        rates_status=rates_status,
    )
