"""Hypothesis property tests for quote calculations."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

import app.models  # noqa: F401 — register ORM models on metadata
from app.core.config import get_settings
from app.core.currency import DECIMAL_PLACES, ROUNDING_MODE
from app.core.exceptions import InvalidCurrencyPairError
from app.core.rates import DIRECT_PAIRS
from app.db import session as db_module
from app.db.base import Base
from app.models.corridor_spread import CorridorSpread
from app.models.exchange_rate import ExchangeRate
from app.services.quote_service import create_quote
from app.services.rate_service import seed_corridor_spreads
from app.services.routing_service import resolve_route


@pytest.fixture
def db_session(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Provide an isolated database session for property tests."""
    database_url = f"sqlite:///{tmp_path / 'quotes-prop-test.db'}"
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


def _reset_rates(db: Session) -> None:
    """Remove cached rates so property examples start from a clean slate."""
    db.query(ExchangeRate).delete()
    db.commit()


def _seed_uniform_rates(db: Session, mid_rate: Decimal = Decimal("1.25000000")) -> None:
    """Seed fresh direct-pair rates with zero spread for predictable maths."""
    fetched_at = datetime.now(UTC)
    for base_currency, quote_currency in DIRECT_PAIRS:
        db.add(
            ExchangeRate(
                base_currency=base_currency,
                quote_currency=quote_currency,
                mid_rate=mid_rate,
                fetched_at=fetched_at,
            )
        )
        spread = db.query(CorridorSpread).filter_by(
            base_currency=base_currency,
            quote_currency=quote_currency,
        ).one()
        spread.buy_spread = Decimal("0")
        spread.sell_spread = Decimal("0")
    db.commit()


def _quantize_amount(amount: Decimal, currency: str) -> Decimal:
    """Round an amount to the currency's decimal places."""
    places = DECIMAL_PLACES[currency]
    quantizer = Decimal("1").scaleb(-places)
    return amount.quantize(quantizer, rounding=ROUNDING_MODE)


@given(
    amount=st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("1000000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    pair=st.sampled_from(list(DIRECT_PAIRS)),
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_direct_pair_rounding_invariant(
    db_session: Session,
    amount: Decimal,
    pair: tuple[str, str],
) -> None:
    """For direct pairs, source × rate rounds to destination within precision."""
    from app.models.customer import Customer

    _reset_rates(db_session)
    _seed_uniform_rates(db_session)
    customer = Customer(name="Prop Test", email=f"prop-{uuid.uuid4()}@example.com")
    db_session.add(customer)
    db_session.commit()

    quote = create_quote(
        db_session,
        customer.id,
        pair[0],
        pair[1],
        amount,
        "source",
    )

    expected_destination = _quantize_amount(
        quote.source_amount * quote.exchange_rate,
        pair[1],
    )
    assert quote.destination_amount == expected_destination


@given(currency=st.sampled_from(sorted({"USD", "EUR", "KES", "NGN"})))
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_routing_rejects_identical_currencies(
    db_session: Session,
    currency: str,
) -> None:
    """Routing never returns a path for identical currencies."""
    _reset_rates(db_session)
    _seed_uniform_rates(db_session)
    with pytest.raises(InvalidCurrencyPairError):
        resolve_route(db_session, currency, currency)
