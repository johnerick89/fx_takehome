"""Structured API error response tests."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

import app.models  # noqa: F401 — register ORM models on metadata
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db import session as db_module
from app.db.base import Base
from app.main import create_app
from app.models.exchange_rate import ExchangeRate
from app.models.quote import Quote
from app.services.metrics_service import reset_executions_failed_counter
from app.services.rate_providers import RateProvider
from app.services.rate_service import seed_corridor_spreads


class MockRateProvider(RateProvider):
    """Test double for external rate providers."""

    def fetch_rates(self) -> dict[str, Decimal]:
        """Return stable USD quote rates."""
        return {
            "EUR": Decimal("0.85000000"),
            "KES": Decimal("130.00000000"),
            "NGN": Decimal("1500.00000000"),
        }


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a test client backed by an isolated SQLite database."""
    database_url = f"sqlite:///{tmp_path / 'errors-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_module.configure_engine(database_url)
    Base.metadata.create_all(db_module.get_engine())
    assert db_module.SessionLocal is not None
    with db_module.SessionLocal() as session:
        seed_corridor_spreads(session)
    reset_executions_failed_counter()

    with patch("app.services.rate_scheduler.refresh_rates_sync"):
        yield TestClient(create_app())

    get_settings.cache_clear()
    db_module.configure_engine()


@pytest.fixture
def db_session(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Provide a database session for direct row manipulation."""
    database_url = f"sqlite:///{tmp_path / 'errors-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_module.configure_engine(database_url)
    Base.metadata.create_all(db_module.get_engine())
    assert db_module.SessionLocal is not None
    with db_module.SessionLocal() as session:
        seed_corridor_spreads(session)
        yield session
    get_settings.cache_clear()
    db_module.configure_engine()


def _assert_error_envelope(response, *, error_code: str, status_code: int) -> None:
    """Assert a response matches the SPEC §10 error envelope."""
    assert response.status_code == status_code
    payload = response.json()
    assert payload["error_code"] == error_code
    assert payload["message"]
    assert payload["trace_id"] == response.headers["X-Trace-ID"]


def _seed_rates(client: TestClient) -> None:
    """Populate cached exchange rates."""
    with patch(
        "app.services.rate_service.get_rate_providers",
        return_value=[MockRateProvider()],
    ):
        client.post("/api/v1/rates/refresh")


def _create_customer(client: TestClient, email: str) -> str:
    """Create a customer and return its ID."""
    response = client.post(
        "/api/v1/customers",
        json={"name": "Error Test", "email": email},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_customer_not_found_returns_structured_error(client: TestClient) -> None:
    """Unknown customer returns CUSTOMER_NOT_FOUND."""
    response = client.get(f"/api/v1/customers/{uuid.uuid4()}/balances")
    _assert_error_envelope(response, error_code="CUSTOMER_NOT_FOUND", status_code=404)


def test_duplicate_email_returns_structured_error(client: TestClient) -> None:
    """Duplicate email returns DUPLICATE_EMAIL."""
    body = {"name": "Jane", "email": "dup@example.com"}
    client.post("/api/v1/customers", json=body)
    response = client.post("/api/v1/customers", json=body)
    _assert_error_envelope(response, error_code="DUPLICATE_EMAIL", status_code=409)


def test_invalid_currency_pair_returns_structured_error(client: TestClient) -> None:
    """Same source and destination currency returns INVALID_CURRENCY_PAIR."""
    customer_id = _create_customer(client, "pair@example.com")
    _seed_rates(client)

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "KES",
            "amount": "100.00",
            "amount_side": "source",
        },
    )
    _assert_error_envelope(response, error_code="INVALID_CURRENCY_PAIR", status_code=422)


def test_invalid_amount_returns_structured_error(client: TestClient) -> None:
    """Non-positive credit amount returns INVALID_AMOUNT."""
    customer_id = _create_customer(client, "amount@example.com")
    response = client.post(
        f"/api/v1/customers/{customer_id}/balances/credit",
        json={"currency": "USD", "amount": "0"},
    )
    _assert_error_envelope(response, error_code="INVALID_AMOUNT", status_code=422)


def test_unsupported_currency_returns_structured_error(client: TestClient) -> None:
    """Unsupported currency returns UNSUPPORTED_CURRENCY."""
    customer_id = _create_customer(client, "currency@example.com")
    response = client.post(
        f"/api/v1/customers/{customer_id}/balances/credit",
        json={"currency": "GBP", "amount": "10.00"},
    )
    _assert_error_envelope(response, error_code="UNSUPPORTED_CURRENCY", status_code=422)


def test_route_unavailable_returns_structured_error(
    client: TestClient,
    db_session: Session,
) -> None:
    """Missing routing path returns ROUTE_UNAVAILABLE."""
    customer_id = _create_customer(client, "route@example.com")
    db_session.add(
        ExchangeRate(
            base_currency="KES",
            quote_currency="USD",
            mid_rate=Decimal("0.00775432"),
            fetched_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "EUR",
            "amount": "1000.00",
            "amount_side": "source",
        },
    )
    _assert_error_envelope(response, error_code="ROUTE_UNAVAILABLE", status_code=422)


def test_rates_stale_returns_structured_error(
    client: TestClient,
    db_session: Session,
) -> None:
    """Blocked stale rates return RATES_STALE."""
    customer_id = _create_customer(client, "stale@example.com")
    stale_time = datetime.now(UTC) - timedelta(minutes=90)
    db_session.add(
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            mid_rate=Decimal("1.00000000"),
            fetched_at=stale_time,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "USD",
            "to_currency": "EUR",
            "amount": "100.00",
            "amount_side": "source",
        },
    )
    _assert_error_envelope(response, error_code="RATES_STALE", status_code=503)


def test_quote_not_found_returns_structured_error(client: TestClient) -> None:
    """Unknown quote on execute returns QUOTE_NOT_FOUND."""
    response = client.post(
        f"/api/v1/quotes/{uuid.uuid4()}/execute",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    _assert_error_envelope(response, error_code="QUOTE_NOT_FOUND", status_code=404)


def test_quote_expired_returns_structured_error(
    client: TestClient,
    db_session: Session,
) -> None:
    """Expired quote returns QUOTE_EXPIRED."""
    customer_id = _create_customer(client, "expired@example.com")
    _seed_rates(client)
    client.post(
        f"/api/v1/customers/{customer_id}/balances/credit",
        json={"currency": "KES", "amount": "20000.00"},
    )
    quote = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "1000.00",
            "amount_side": "source",
        },
    ).json()

    row = db_session.get(Quote, quote["quote_id"])
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = client.post(
        f"/api/v1/quotes/{quote['quote_id']}/execute",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    _assert_error_envelope(response, error_code="QUOTE_EXPIRED", status_code=422)


def test_quote_already_executed_returns_structured_error(client: TestClient) -> None:
    """Second execute returns QUOTE_ALREADY_EXECUTED."""
    customer_id = _create_customer(client, "executed@example.com")
    _seed_rates(client)
    client.post(
        f"/api/v1/customers/{customer_id}/balances/credit",
        json={"currency": "KES", "amount": "20000.00"},
    )
    quote = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "1000.00",
            "amount_side": "source",
        },
    ).json()
    client.post(
        f"/api/v1/quotes/{quote['quote_id']}/execute",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    response = client.post(
        f"/api/v1/quotes/{quote['quote_id']}/execute",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    _assert_error_envelope(response, error_code="QUOTE_ALREADY_EXECUTED", status_code=409)


def test_insufficient_balance_returns_structured_error(client: TestClient) -> None:
    """Insufficient balance returns INSUFFICIENT_BALANCE."""
    customer_id = _create_customer(client, "balance@example.com")
    _seed_rates(client)
    quote = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "1000.00",
            "amount_side": "source",
        },
    ).json()

    response = client.post(
        f"/api/v1/quotes/{quote['quote_id']}/execute",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    _assert_error_envelope(response, error_code="INSUFFICIENT_BALANCE", status_code=422)


def test_missing_idempotency_key_returns_structured_error(client: TestClient) -> None:
    """Missing Idempotency-Key returns MISSING_IDEMPOTENCY_KEY."""
    customer_id = _create_customer(client, "no-key@example.com")
    _seed_rates(client)
    client.post(
        f"/api/v1/customers/{customer_id}/balances/credit",
        json={"currency": "KES", "amount": "20000.00"},
    )
    quote = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "1000.00",
            "amount_side": "source",
        },
    ).json()

    response = client.post(f"/api/v1/quotes/{quote['quote_id']}/execute")
    _assert_error_envelope(response, error_code="MISSING_IDEMPOTENCY_KEY", status_code=422)


def test_idempotency_key_conflict_returns_structured_error(client: TestClient) -> None:
    """Reusing a key on another quote returns IDEMPOTENCY_KEY_CONFLICT."""
    customer_id = _create_customer(client, "conflict@example.com")
    _seed_rates(client)
    client.post(
        f"/api/v1/customers/{customer_id}/balances/credit",
        json={"currency": "KES", "amount": "50000.00"},
    )
    quote_one = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "1000.00",
            "amount_side": "source",
        },
    ).json()
    quote_two = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "2000.00",
            "amount_side": "source",
        },
    ).json()
    key = str(uuid.uuid4())
    client.post(
        f"/api/v1/quotes/{quote_one['quote_id']}/execute",
        headers={"Idempotency-Key": key},
    )

    response = client.post(
        f"/api/v1/quotes/{quote_two['quote_id']}/execute",
        headers={"Idempotency-Key": key},
    )
    _assert_error_envelope(response, error_code="IDEMPOTENCY_KEY_CONFLICT", status_code=422)


def test_spread_not_found_returns_structured_error(client: TestClient) -> None:
    """Unknown spread pair returns SPREAD_NOT_FOUND."""
    response = client.put(
        "/api/v1/rates/spreads/USD/GBP",
        json={"buy_spread": "0.005", "sell_spread": "0.005"},
    )
    _assert_error_envelope(response, error_code="SPREAD_NOT_FOUND", status_code=404)


def test_transaction_not_found_returns_structured_error(client: TestClient) -> None:
    """Unknown transaction returns TRANSACTION_NOT_FOUND."""
    response = client.get(f"/api/v1/transactions/{uuid.uuid4()}")
    _assert_error_envelope(response, error_code="TRANSACTION_NOT_FOUND", status_code=404)


def test_unhandled_exception_returns_internal_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unhandled exceptions return INTERNAL_ERROR without leaking details."""
    database_url = f"sqlite:///{tmp_path / 'errors-unhandled.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_module.configure_engine(database_url)
    Base.metadata.create_all(db_module.get_engine())

    with patch("app.services.rate_scheduler.refresh_rates_sync"):
        with patch(
            "app.api.customers.list_customers",
            side_effect=RuntimeError("super secret database password"),
        ):
            error_client = TestClient(create_app(), raise_server_exceptions=False)
            response = error_client.get("/api/v1/customers")

    payload = response.json()
    assert response.status_code == 500
    assert payload["error_code"] == "INTERNAL_ERROR"
    assert payload["message"] == "An unexpected error occurred"
    assert "password" not in payload["message"]
    assert payload["trace_id"] == response.headers["X-Trace-ID"]

    get_settings.cache_clear()
    db_module.configure_engine()
