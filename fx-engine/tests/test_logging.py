"""Logging configuration tests."""

import json
import logging
from collections.abc import Iterator

import pytest

import app.core.logging as logging_module
from app.core.logging import JsonFormatter, get_logger, trace_id_var


@pytest.fixture
def reset_logging_state() -> Iterator[None]:
    """Reset application logging configuration between tests."""
    logging_module._configured = False
    app_logger = logging.getLogger("app")
    for handler in app_logger.handlers[:]:
        app_logger.removeHandler(handler)
        handler.close()
    yield
    logging_module._configured = False
    for handler in app_logger.handlers[:]:
        app_logger.removeHandler(handler)
        handler.close()


def test_json_log_format_in_production(
    monkeypatch: pytest.MonkeyPatch,
    reset_logging_state: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-development APP_ENV emits structured JSON log lines."""
    monkeypatch.setenv("APP_ENV", "production")
    trace_id_var.set("abc123")

    logger = get_logger("app.test")
    logger.info(
        "request received",
        extra={
            "event": "request.received",
            "method": "GET",
            "path": "/healthz",
        },
    )

    output = capsys.readouterr().err.strip()
    payload = json.loads(output)

    assert payload["level"] == "INFO"
    assert payload["trace_id"] == "abc123"
    assert payload["event"] == "request.received"
    assert payload["method"] == "GET"
    assert payload["path"] == "/healthz"
    assert "timestamp" in payload


def test_json_formatter_includes_optional_fields() -> None:
    """JsonFormatter serialises all supported extra fields."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="done",
        args=(),
        exc_info=None,
    )
    record.trace_id = "trace-1"
    record.event = "request.completed"
    record.method = "POST"
    record.path = "/quotes"
    record.status_code = 201
    record.duration_ms = 12

    payload = json.loads(formatter.format(record))

    assert payload["trace_id"] == "trace-1"
    assert payload["event"] == "request.completed"
    assert payload["method"] == "POST"
    assert payload["path"] == "/quotes"
    assert payload["status_code"] == 201
    assert payload["duration_ms"] == 12


def test_get_logger_configures_only_once(
    monkeypatch: pytest.MonkeyPatch,
    reset_logging_state: None,
) -> None:
    """Repeated get_logger calls do not register duplicate handlers."""
    monkeypatch.setenv("APP_ENV", "development")

    first_logger = get_logger("app.first")
    handler_count_after_first = len(logging.getLogger("app").handlers)

    second_logger = get_logger("app.second")
    handler_count_after_second = len(logging.getLogger("app").handlers)

    assert handler_count_after_first == 1
    assert handler_count_after_second == 1
    assert first_logger.name == "app.first"
    assert second_logger.name == "app.second"
