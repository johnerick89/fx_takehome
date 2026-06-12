"""Metrics endpoint tests."""

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
from app.db import session as db_module
from app.db.base import Base
from app.main import create_app
from app.models.quote import Quote, QuoteStatus
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
    database_url = f"sqlite:///{tmp_path / 'metrics-test.db'}"
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
    database_url = f"sqlite:///{tmp_path / 'metrics-test.db'}"
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


def _seed_rates(client: TestClient) -> None:
    """Populate cached exchange rates."""
    with patch(
        "app.services.rate_service.get_rate_providers",
        return_value=[MockRateProvider()],
    ):
        client.post("/api/v1/rates/refresh")


def test_metrics_returns_all_fields(client: TestClient) -> None:
    """GET /metrics returns all required counters."""
    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "quotes_generated_total",
        "executions_successful_total",
        "executions_failed_total",
        "rates_last_updated",
        "active_quotes_count",
    }


def test_metrics_quote_and_execution_counters(client: TestClient) -> None:
    """Metrics increment after quote creation and execution."""
    _seed_rates(client)
    customer = client.post(
        "/api/v1/customers",
        json={"name": "Metrics User", "email": "metrics@example.com"},
    ).json()
    client.post(
        f"/api/v1/customers/{customer['id']}/balances/credit",
        json={"currency": "KES", "amount": "50000.00"},
    )

    before = client.get("/metrics").json()
    quote = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "10000.00",
            "amount_side": "source",
        },
    ).json()
    after_quote = client.get("/metrics").json()
    assert after_quote["quotes_generated_total"] == before["quotes_generated_total"] + 1

    client.post(
        f"/api/v1/quotes/{quote['quote_id']}/execute",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    after_execute = client.get("/metrics").json()
    assert after_execute["executions_successful_total"] == before["executions_successful_total"] + 1


def test_metrics_active_quotes_excludes_expired_and_executed(
    client: TestClient,
    db_session: Session,
) -> None:
    """active_quotes_count excludes expired and executed quotes."""
    _seed_rates(client)
    customer = client.post(
        "/api/v1/customers",
        json={"name": "Active User", "email": "active@example.com"},
    ).json()
    client.post(
        f"/api/v1/customers/{customer['id']}/balances/credit",
        json={"currency": "KES", "amount": "50000.00"},
    )
    quote = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "5000.00",
            "amount_side": "source",
        },
    ).json()

    active_before = client.get("/metrics").json()["active_quotes_count"]
    assert active_before >= 1

    row = db_session.get(Quote, quote["quote_id"])
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=30)
    db_session.commit()

    expired_metrics = client.get("/metrics").json()["active_quotes_count"]
    assert expired_metrics == active_before - 1

    fresh_quote = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "5000.00",
            "amount_side": "source",
        },
    ).json()
    client.post(
        f"/api/v1/quotes/{fresh_quote['quote_id']}/execute",
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    row = db_session.get(Quote, fresh_quote["quote_id"])
    assert row is not None
    assert row.status == QuoteStatus.EXECUTED.value
    executed_metrics = client.get("/metrics").json()["active_quotes_count"]
    assert executed_metrics == expired_metrics
