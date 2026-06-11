"""Background exchange rate refresh scheduler."""

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.rate_service import refresh_rates

logger = get_logger(__name__)


def refresh_rates_sync() -> None:
    """Run a synchronous rate refresh in a worker thread."""
    assert SessionLocal is not None
    with SessionLocal() as db:
        refresh_rates(db)


async def rate_refresh_loop(interval_seconds: int | None = None) -> None:
    """Periodically refresh cached exchange rates."""
    settings = get_settings()
    interval = interval_seconds or settings.rate_refresh_interval_seconds

    while True:
        try:
            await asyncio.to_thread(refresh_rates_sync)
        except Exception:
            logger.exception(
                "rate_refresh.failed",
                extra={"event": "rate_refresh.failed"},
            )
        await asyncio.sleep(interval)
