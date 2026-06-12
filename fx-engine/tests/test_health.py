"""Health endpoint tests."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

import app.models  # noqa: F401 — register ORM models on metadata
from app.core.config import get_settings
from app.db import session as db_module
from app.db.base import Base
from app.main import create_app
from app.models.exchange_rate import ExchangeRate
from app.services.rate_service import seed_corridor_spreads


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a test client backed by an isolated SQLite database."""
    database_url = f"sqlite:///{tmp_path / 'health-test.db'}"
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


def test_healthz_returns_enriched_payload(client: TestClient) -> None:
    """GET /healthz returns DB and rates status fields."""
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert payload["db"] == "ok"
    assert "rates_age_seconds" in payload
    assert payload["rates_status"] in {"fresh", "stale", "unavailable"}


def test_healthz_fresh_rates_when_recently_fetched(
    client: TestClient,
    db_session: Session,
) -> None:
    """Fresh cached rates report rates_status fresh."""
    fetched_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.add(
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            mid_rate="1.00000000",
            fetched_at=fetched_at,
        )
    )
    db_session.commit()

    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["rates_status"] == "fresh"
    assert payload["rates_age_seconds"] is not None


@pytest.fixture
def db_session(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Provide a database session sharing the health test database."""
    database_url = f"sqlite:///{tmp_path / 'health-test.db'}"
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


def test_healthz_degraded_when_db_check_fails(client: TestClient) -> None:
    """Unreachable DB reports degraded status with db error."""
    with patch("app.services.health_service.check_db", return_value="error"):
        response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["db"] == "error"
