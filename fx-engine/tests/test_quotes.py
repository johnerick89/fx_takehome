"""Quote API integration tests."""

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
from app.models.corridor_spread import CorridorSpread
from app.models.exchange_rate import ExchangeRate
from app.services.rate_providers import RateProvider
from app.services.rate_service import refresh_rates, seed_corridor_spreads


class MockRateProvider(RateProvider):
    """Test double for external rate providers."""

    def __init__(self, rates: dict[str, Decimal] | None = None) -> None:
        """Configure mock provider behaviour."""
        self.rates = rates or {
            "EUR": Decimal("0.85000000"),
            "KES": Decimal("130.00000000"),
            "NGN": Decimal("1500.00000000"),
        }

    def fetch_rates(self) -> dict[str, Decimal]:
        """Return configured rates."""
        return self.rates


@pytest.fixture
def database_url(tmp_path) -> str:
    """Shared SQLite database URL for quote tests."""
    return f"sqlite:///{tmp_path / 'quotes-test.db'}"


@pytest.fixture
def db_session(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Provide an isolated database session for service-layer tests."""
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


def _create_customer(client: TestClient, email: str = "quote@example.com") -> dict:
    """Create a customer and return the response JSON."""
    response = client.post(
        "/api/v1/customers",
        json={"name": "Quote User", "email": email},
    )
    assert response.status_code == 201
    return response.json()


def _seed_rates(client: TestClient) -> None:
    """Refresh rates from a mock provider."""
    with patch(
        "app.services.rate_service.get_rate_providers",
        return_value=[MockRateProvider()],
    ):
        response = client.post("/api/v1/rates/refresh")
    assert response.status_code == 200


def _seed_rate_row(
    db: Session,
    base: str,
    quote: str,
    mid_rate: Decimal,
    *,
    fetched_at: datetime | None = None,
    buy_spread: Decimal = Decimal("0"),
    sell_spread: Decimal = Decimal("0"),
) -> None:
    """Insert a single exchange rate and optional zero spreads."""
    when = fetched_at or datetime.now(UTC)
    db.add(
        ExchangeRate(
            base_currency=base,
            quote_currency=quote,
            mid_rate=mid_rate,
            fetched_at=when,
        )
    )
    spread = db.query(CorridorSpread).filter_by(base_currency=base, quote_currency=quote).one_or_none()
    if spread is None:
        db.add(
            CorridorSpread(
                base_currency=base,
                quote_currency=quote,
                buy_spread=buy_spread,
                sell_spread=sell_spread,
            )
        )
    else:
        spread.buy_spread = buy_spread
        spread.sell_spread = sell_spread
    db.commit()


def test_create_quote_direct_pair(client: TestClient) -> None:
    """POST /api/v1/quotes returns 201 with required fields for a direct pair."""
    customer = _create_customer(client)
    _seed_rates(client)

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "10000.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    uuid.UUID(payload["quote_id"], version=4)
    assert payload["customer_id"] == customer["id"]
    assert payload["from_currency"] == "KES"
    assert payload["to_currency"] == "USD"
    assert payload["routing_path"] == ["KES", "USD"]
    assert payload["rate_includes_spread"] is True
    assert isinstance(payload["source_amount"], str)
    assert isinstance(payload["destination_amount"], str)
    assert isinstance(payload["exchange_rate"], str)
    assert "expires_at" in payload
    assert "created_at" in payload


def test_quote_expires_in_60_seconds(client: TestClient) -> None:
    """Quote expires_at is exactly 60 seconds after created_at."""
    customer = _create_customer(client, email="expiry@example.com")
    _seed_rates(client)

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "USD",
            "to_currency": "EUR",
            "amount": "100.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    created_at = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
    assert (expires_at - created_at).total_seconds() == 60


def test_create_quote_cross_pair(
    db_session: Session,
    client: TestClient,
) -> None:
    """Cross-pair quote includes intermediate currency in routing_path."""
    customer = _create_customer(client, email="cross@example.com")
    _seed_rate_row(db_session, "KES", "USD", Decimal("0.00769231"))
    _seed_rate_row(db_session, "USD", "EUR", Decimal("0.85000000"))

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "EUR",
            "amount": "10000.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["routing_path"] == ["KES", "USD", "EUR"]


def test_unknown_customer_returns_404(client: TestClient) -> None:
    """Unknown customer returns 404."""
    _seed_rates(client)
    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": str(uuid.uuid4()),
            "from_currency": "USD",
            "to_currency": "EUR",
            "amount": "100.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 404


def test_route_unavailable_returns_422(db_session: Session, client: TestClient) -> None:
    """Unsupported route returns 422 when no path resolves."""
    customer = _create_customer(client, email="noroute@example.com")
    _seed_rate_row(db_session, "KES", "USD", Decimal("0.00775432"))

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "EUR",
            "amount": "1000.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 422


def test_stale_blocked_rates_return_503(db_session: Session, client: TestClient) -> None:
    """Blocked stale rates return 503."""
    customer = _create_customer(client, email="blocked@example.com")
    stale_time = datetime.now(UTC) - timedelta(minutes=90)
    _seed_rate_row(
        db_session,
        "USD",
        "EUR",
        Decimal("1.00000000"),
        fetched_at=stale_time,
    )

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "USD",
            "to_currency": "EUR",
            "amount": "100.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 503


def test_stale_warning_rates_return_201_with_stale_flag(
    db_session: Session,
    client: TestClient,
) -> None:
    """Warning stale rates return 201 with stale true."""
    customer = _create_customer(client, email="warning@example.com")
    stale_time = datetime.now(UTC) - timedelta(minutes=30)
    _seed_rate_row(
        db_session,
        "USD",
        "EUR",
        Decimal("1.00000000"),
        fetched_at=stale_time,
    )

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "USD",
            "to_currency": "EUR",
            "amount": "100.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 201
    assert response.json()["stale"] is True


def test_invalid_amount_returns_422(client: TestClient) -> None:
    """Non-positive amount returns 422."""
    customer = _create_customer(client, email="invalid@example.com")
    _seed_rates(client)

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "USD",
            "to_currency": "EUR",
            "amount": "0",
            "amount_side": "source",
        },
    )
    assert response.status_code == 422


def test_kes_usd_rounding_example(db_session: Session, client: TestClient) -> None:
    """1000 KES to USD at 0.00775432 yields destination 7.75."""
    customer = _create_customer(client, email="rounding@example.com")
    _seed_rate_row(
        db_session,
        "KES",
        "USD",
        Decimal("0.00775432"),
        buy_spread=Decimal("0"),
        sell_spread=Decimal("0"),
    )

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "USD",
            "amount": "1000",
            "amount_side": "source",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["destination_amount"] == "7.75"
    assert payload["exchange_rate"] == "0.00775432"

def test_invalid_currency_pair_returns_422(client: TestClient) -> None:
    """Invalid currency pair returns 422."""
    customer = _create_customer(client, email="invalid-currency-pair@example.com")
    _seed_rates(client)

    response = client.post(
        "/api/v1/quotes",
        json={
            "customer_id": customer["id"],
            "from_currency": "KES",
            "to_currency": "KES",
            "amount": "100.00",
            "amount_side": "source",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_CURRENCY_PAIR"
