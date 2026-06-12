"""Application logging configuration."""

import contextvars
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")

_configured = False


class TraceIDFilter(logging.Filter):
    """Inject the current trace ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach trace_id from context to the log record."""
        record.trace_id = trace_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Emit structured JSON log lines for non-development environments."""

    _EXTRA_KEYS = (
        "event",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "quote_id",
        "customer_id",
        "debited_amount",
        "credited_amount",
        "error_code",
        "action",
        "idempotency_key",
    )

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON object."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", "-"),
        }
        for key in self._EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload)


def _configure_logging() -> None:
    """Configure the application logger once."""
    global _configured
    if _configured:
        return

    app_env = os.getenv("APP_ENV", "development")
    handler = logging.StreamHandler()
    handler.addFilter(TraceIDFilter())

    if app_env == "development":
        handler.setFormatter(
            logging.Formatter("%(levelname)s  [trace_id=%(trace_id)s] %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())

    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    app_logger.addHandler(handler)
    app_logger.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured application logger."""
    _configure_logging()
    logger_name = name if name.startswith("app.") else f"app.{name}"
    return logging.getLogger(logger_name)
