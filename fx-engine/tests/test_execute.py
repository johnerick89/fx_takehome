"""FX execute path tests."""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

import app.models  # noqa: F401 — register ORM models on metadata
from app.core.config import get_settings
from app.db import session as db_module
from app.db.base import Base
from app.main import create_app
from app.models.quote import Quote, QuoteStatus
from app.models.transaction import Transaction
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
def database_url(tmp_path) -> str:
    """Shared SQLite database URL for execute tests."""
    return f"sqlite:///{tmp_path / 'execute-test.db'}"


@pytest.fixture
def client(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a test client backed by an isolated SQLite database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_module.configure_engine(database_url)
    Base.metadata.create_all(db_module.get_engine())
    assert db_module.SessionLocal is not None
    with db_module.SessionLocal() as session:
        seed_corridor_spreads(session)

    with patch("app.services.rate_scheduler.refresh_rates_sync"):
        yield TestClient(create_app())

    get_settings.cache_clear()
    db_module.configure_engine()


@pytest.fixture
def db_session(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Provide a database session for direct row manipulation."""
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


def _create_customer(client: TestClient, email: str) -> dict:
    """Create a customer."""
    response = client.post(
        "/api/v1/customers",
        json={"name": "Execute User", "email": email},
    )
    assert response.status_code == 201
    return response.json()


def _seed_rates(client: TestClient) -> None:
    """Populate cached exchange rates."""
    with patch(
        "app.services.rate_service.get_rate_providers",
        return_value=[MockRateProvider()],
    ):
        response = client.post("/api/v1/rates/refresh")
    assert response.status_code == 200


def _credit(client: TestClient, customer_id: str, currency: str, amount: str) -> None:
    """Credit a customer balance."""
    response = client.post(
        f"/api/v1/customers/{customer_id}/balances/credit",
        json={"currency": currency, "amount": amount},
    )
    assert response.status_code == 200


def _create_quote(
    client: TestClient,
    customer_id: str,
    *,
    from_currency: str = "KES",
    to_currency: str = "USD",
    amount: str = "10000.00",
) -> dict:
    """Create a quote and return the response JSON."""
    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer_id,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "amount": amount,
            "amount_side": "source",
        },
    )
    assert response.status_code == 201
    return response.json()


def _execute(
    client: TestClient,
    quote_id: str,
    idempotency_key: str | None = None,
) -> object:
    """Execute a quote."""
    headers = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return client.post(f"/api/v1/quotes/{quote_id}/execute", headers=headers)


def test_execute_happy_path(client: TestClient) -> None:
    """Execute valid quote updates balances and returns 201 with Location."""
    customer = _create_customer(client, "execute-happy@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "20000.00")
    quote = _create_quote(client, customer["id"])
    idempotency_key = str(uuid.uuid4())

    response = _execute(client, quote["quote_id"], idempotency_key)
    assert response.status_code == 201
    payload = response.json()
    assert payload["quote_id"] == quote["quote_id"]
    assert payload["debited_amount"] == quote["source_amount"]
    assert payload["credited_amount"] == quote["destination_amount"]
    assert payload["idempotency_key"] == idempotency_key
    assert response.headers["Location"] == f"/api/v1/transactions/{payload['transaction_id']}"

    get_response = client.get(f"/api/v1/transactions/{payload['transaction_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["transaction_id"] == payload["transaction_id"]

    balances = client.get(f"/api/v1/customers/{customer['id']}/balances").json()["balances"]
    kes_balance = next(item for item in balances if item["currency"] == "KES")
    usd_balance = next(item for item in balances if item["currency"] == "USD")
    assert kes_balance["amount"] == "10000.00"
    assert usd_balance["amount"] == quote["destination_amount"]


def test_execute_expired_quote_returns_422(
    client: TestClient,
    db_session: Session,
) -> None:
    """Expired quote returns QUOTE_EXPIRED."""
    customer = _create_customer(client, "execute-expired@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "20000.00")
    quote = _create_quote(client, customer["id"])

    row = db_session.get(Quote, quote["quote_id"])
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = _execute(client, quote["quote_id"], str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["error_code"] == "QUOTE_EXPIRED"


def test_execute_already_executed_returns_409(client: TestClient) -> None:
    """Second execute with a new key returns QUOTE_ALREADY_EXECUTED."""
    customer = _create_customer(client, "execute-twice@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "20000.00")
    quote = _create_quote(client, customer["id"])

    first = _execute(client, quote["quote_id"], str(uuid.uuid4()))
    assert first.status_code == 201

    second = _execute(client, quote["quote_id"], str(uuid.uuid4()))
    assert second.status_code == 409
    assert second.json()["error_code"] == "QUOTE_ALREADY_EXECUTED"


def test_execute_unknown_quote_returns_404(client: TestClient) -> None:
    """Unknown quote returns QUOTE_NOT_FOUND."""
    response = _execute(client, str(uuid.uuid4()), str(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["error_code"] == "QUOTE_NOT_FOUND"


def test_execute_insufficient_balance_returns_422(client: TestClient) -> None:
    """Insufficient balance returns INSUFFICIENT_BALANCE."""
    customer = _create_customer(client, "execute-insufficient@example.com")
    _seed_rates(client)
    quote = _create_quote(client, customer["id"])

    response = _execute(client, quote["quote_id"], str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["error_code"] == "INSUFFICIENT_BALANCE"


def test_execute_missing_idempotency_key_returns_422(client: TestClient) -> None:
    """Missing Idempotency-Key returns MISSING_IDEMPOTENCY_KEY."""
    customer = _create_customer(client, "execute-no-key@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "20000.00")
    quote = _create_quote(client, customer["id"])

    response = _execute(client, quote["quote_id"], None)
    assert response.status_code == 422
    assert response.json()["error_code"] == "MISSING_IDEMPOTENCY_KEY"


def test_execute_idempotent_replay_returns_200(client: TestClient) -> None:
    """Retry with same key returns 200 and identical body."""
    customer = _create_customer(client, "execute-replay@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "20000.00")
    quote = _create_quote(client, customer["id"])
    idempotency_key = str(uuid.uuid4())

    first = _execute(client, quote["quote_id"], idempotency_key)
    second = _execute(client, quote["quote_id"], idempotency_key)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()

    balances = client.get(f"/api/v1/customers/{customer['id']}/balances").json()["balances"]
    kes_balance = next(item for item in balances if item["currency"] == "KES")
    assert kes_balance["amount"] == "10000.00"


def test_execute_idempotency_key_conflict_returns_422(client: TestClient) -> None:
    """Same key for different quotes returns IDEMPOTENCY_KEY_CONFLICT."""
    customer = _create_customer(client, "execute-conflict@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "40000.00")
    quote_one = _create_quote(client, customer["id"], amount="10000.00")
    quote_two = _create_quote(client, customer["id"], amount="12000.00")
    idempotency_key = str(uuid.uuid4())

    first = _execute(client, quote_one["quote_id"], idempotency_key)
    assert first.status_code == 201

    conflict = _execute(client, quote_two["quote_id"], idempotency_key)
    assert conflict.status_code == 422
    assert conflict.json()["error_code"] == "IDEMPOTENCY_KEY_CONFLICT"


def test_execute_idempotency_key_too_long_returns_422(client: TestClient) -> None:
    """Oversized Idempotency-Key returns 422 before DB insert."""
    customer = _create_customer(client, "execute-long-key@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "20000.00")
    quote = _create_quote(client, customer["id"])

    response = _execute(client, quote["quote_id"], "x" * 129)
    assert response.status_code == 422
    assert response.json()["error_code"] == "MISSING_IDEMPOTENCY_KEY"


def test_execute_concurrency_only_one_succeeds(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parallel execute requests produce one success and 409s for the rest."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_module.configure_engine(database_url)
    Base.metadata.create_all(db_module.get_engine())
    with db_module.SessionLocal() as session:
        seed_corridor_spreads(session)

    with patch("app.services.rate_scheduler.refresh_rates_sync"):
        setup_client = TestClient(create_app())

    customer = _create_customer(setup_client, "execute-concurrency@example.com")
    _seed_rates(setup_client)
    _credit(setup_client, customer["id"], "KES", "200000.00")
    quote = _create_quote(setup_client, customer["id"], amount="10000.00")

    def _attempt() -> int:
        with patch("app.services.rate_scheduler.refresh_rates_sync"):
            thread_client = TestClient(create_app())
        response = _execute(thread_client, quote["quote_id"], str(uuid.uuid4()))
        return response.status_code

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = [future.result() for future in as_completed(executor.submit(_attempt) for _ in range(8))]

    assert statuses.count(201) == 1
    assert statuses.count(409) == 7

    balances = setup_client.get(f"/api/v1/customers/{customer['id']}/balances").json()["balances"]
    kes_balance = next(item for item in balances if item["currency"] == "KES")
    assert kes_balance["amount"] == "190000.00"


def test_execute_rollback_on_credit_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injected credit failure rolls back debit and leaves quote PENDING."""
    customer = _create_customer(client, "execute-rollback@example.com")
    _seed_rates(client)
    _credit(client, customer["id"], "KES", "20000.00")
    quote = _create_quote(client, customer["id"])

    def _fail_credit(*_args, **_kwargs) -> None:
        raise RuntimeError("injected credit failure")

    monkeypatch.setattr("app.services.execute_service._credit_balance", _fail_credit)

    with patch("app.services.rate_scheduler.refresh_rates_sync"):
        error_client = TestClient(create_app(), raise_server_exceptions=False)
    response = _execute(error_client, quote["quote_id"], str(uuid.uuid4()))
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"

    balances = client.get(f"/api/v1/customers/{customer['id']}/balances").json()["balances"]
    kes_balance = next(item for item in balances if item["currency"] == "KES")
    assert kes_balance["amount"] == "20000.00"

    assert db_module.SessionLocal is not None
    with db_module.SessionLocal() as session:
        quote_row = session.get(Quote, quote["quote_id"])
        assert quote_row is not None
        assert quote_row.status == QuoteStatus.PENDING.value
        assert session.query(Transaction).count() == 0
