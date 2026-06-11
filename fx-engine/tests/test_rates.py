"""Exchange rate tests."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

import app.models  # noqa: F401 — register ORM models on metadata
from app.core.config import get_settings
from app.core.exceptions import RateProviderError
from app.core.rates import DIRECT_PAIRS
from app.db import session as db_module
from app.db.base import Base
from app.main import create_app
from app.models.exchange_rate import ExchangeRate
from app.services.rate_providers import RateProvider
from app.services.rate_service import (
    build_pair_rates,
    get_rate,
    get_rates_age_seconds,
    refresh_rates,
    seed_corridor_spreads,
)
from app.services.rate_scheduler import refresh_rates_sync


class MockRateProvider(RateProvider):
    """Test double for external rate providers."""

    def __init__(
        self,
        rates: dict[str, Decimal] | None = None,
        *,
        should_fail: bool = False,
    ) -> None:
        """Configure mock provider behaviour."""
        self.rates = rates or {
            "EUR": Decimal("0.85000000"),
            "KES": Decimal("130.00000000"),
            "NGN": Decimal("1500.00000000"),
        }
        self.should_fail = should_fail

    def fetch_rates(self) -> dict[str, Decimal]:
        """Return configured rates or fail."""
        if self.should_fail:
            raise RateProviderError("provider unavailable")
        return self.rates


@pytest.fixture
def db_session(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Provide an isolated database session for service-layer tests."""
    database_url = f"sqlite:///{tmp_path / 'rates-test.db'}"
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


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a test client backed by an isolated SQLite database."""
    database_url = f"sqlite:///{tmp_path / 'rates-api-test.db'}"
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


def test_refresh_rates_upserts_pairs(db_session: Session) -> None:
    """refresh_rates upserts rates into the database."""
    refresh_rates(db_session, providers=[MockRateProvider()])
    rows = db_session.query(ExchangeRate).all()
    assert len(rows) == len(DIRECT_PAIRS)
    assert db_session.query(ExchangeRate).filter_by(base_currency="USD", quote_currency="EUR").one()


def test_refresh_rates_falls_back_to_secondary_provider(db_session: Session) -> None:
    """Primary provider failure falls back to the secondary provider."""
    providers: list[RateProvider] = [
        MockRateProvider(should_fail=True),
        MockRateProvider(),
    ]
    refresh_rates(db_session, providers=providers)
    assert db_session.query(ExchangeRate).count() > 0


def test_refresh_rates_retains_cache_on_total_failure(db_session: Session) -> None:
    """Total provider failure retains the existing cache."""
    refresh_rates(db_session, providers=[MockRateProvider()])
    existing = db_session.query(ExchangeRate).filter_by(base_currency="USD", quote_currency="EUR").one()
    existing_mid = existing.mid_rate

    refresh_rates(
        db_session,
        providers=[MockRateProvider(should_fail=True), MockRateProvider(should_fail=True)],
    )
    retained = db_session.query(ExchangeRate).filter_by(base_currency="USD", quote_currency="EUR").one()
    assert retained.mid_rate == existing_mid


def test_refresh_rates_retains_cache_on_malformed_response(db_session: Session) -> None:
    """Malformed provider data retains the previous cache."""

    class MalformedProvider(RateProvider):
        def fetch_rates(self) -> dict[str, Decimal]:
            return {"EUR": Decimal("1")}

    refresh_rates(db_session, providers=[MockRateProvider()])
    existing_mid = (
        db_session.query(ExchangeRate).filter_by(base_currency="USD", quote_currency="EUR").one().mid_rate
    )

    refresh_rates(db_session, providers=[MalformedProvider()])
    retained = db_session.query(ExchangeRate).filter_by(base_currency="USD", quote_currency="EUR").one()
    assert retained.mid_rate == existing_mid


def test_get_rate_applies_spreads(db_session: Session) -> None:
    """get_rate applies buy and sell spreads."""
    db_session.add(
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            mid_rate=Decimal("1.00000000"),
            fetched_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    result = get_rate(db_session, "USD", "EUR")
    assert result.mid_rate == Decimal("1.00000000")
    assert result.buy_rate == Decimal("1.00500000")
    assert result.sell_rate == Decimal("0.99500000")


def test_staleness_fresh_rate(db_session: Session) -> None:
    """Rate younger than 10 minutes is fresh."""
    db_session.add(
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            mid_rate=Decimal("1.00000000"),
            fetched_at=datetime.now(UTC) - timedelta(minutes=5),
        )
    )
    db_session.commit()
    result = get_rate(db_session, "USD", "EUR")
    assert result.stale is False
    assert result.blocked is False


def test_staleness_warning_rate(db_session: Session) -> None:
    """Rate between 10 and 60 minutes old is stale but not blocked."""
    db_session.add(
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            mid_rate=Decimal("1.00000000"),
            fetched_at=datetime.now(UTC) - timedelta(minutes=30),
        )
    )
    db_session.commit()
    result = get_rate(db_session, "USD", "EUR")
    assert result.stale is True
    assert result.blocked is False


def test_staleness_blocked_rate(db_session: Session) -> None:
    """Rate older than 60 minutes is blocked."""
    db_session.add(
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            mid_rate=Decimal("1.00000000"),
            fetched_at=datetime.now(UTC) - timedelta(minutes=90),
        )
    )
    db_session.commit()
    result = get_rate(db_session, "USD", "EUR")
    assert result.blocked is True


def test_get_rates_age_seconds(db_session: Session) -> None:
    """get_rates_age_seconds returns age of the newest cached rate."""
    fetched_at = datetime.now(UTC) - timedelta(minutes=15)
    db_session.add(
        ExchangeRate(
            base_currency="USD",
            quote_currency="EUR",
            mid_rate=Decimal("1.00000000"),
            fetched_at=fetched_at,
        )
    )
    db_session.commit()
    age = get_rates_age_seconds(db_session)
    assert age is not None
    assert 14 * 60 <= age <= 16 * 60


def test_get_rates_endpoint(client: TestClient) -> None:
    """GET /api/v1/rates returns cached rates."""
    with patch(
        "app.services.rate_service.get_rate_providers",
        return_value=[MockRateProvider()],
    ):
        client.post("/api/v1/rates/refresh")
        response = client.get("/api/v1/rates")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rates"]) > 0
    assert isinstance(payload["rates"][0]["mid_rate"], str)


def test_post_refresh_endpoint(client: TestClient) -> None:
    """POST /api/v1/rates/refresh triggers a refresh."""
    with patch("app.api.rates.refresh_rates") as mock_refresh:
        response = client.post("/api/v1/rates/refresh")
    assert response.status_code == 200
    mock_refresh.assert_called_once()


def test_lifespan_survives_refresh_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Background refresh failures do not crash application startup."""
    database_url = f"sqlite:///{tmp_path / 'lifespan-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_module.configure_engine(database_url)
    Base.metadata.create_all(db_module.get_engine())

    with patch(
        "app.services.rate_scheduler.refresh_rates_sync",
        side_effect=RuntimeError("provider down"),
    ):
        test_client = TestClient(create_app())
        response = test_client.get("/healthz")

    assert response.status_code == 200
    get_settings.cache_clear()
    db_module.configure_engine()


def test_corridor_spreads_seeded_for_all_pairs(db_session: Session) -> None:
    """Default spreads exist for every direct pair."""
    from app.models.corridor_spread import CorridorSpread

    count = db_session.query(CorridorSpread).count()
    assert count == len(DIRECT_PAIRS)
