"""Structured API error response tests."""

import uuid
from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a test client backed by an isolated SQLite database."""
    database_url = f"sqlite:///{tmp_path / 'errors-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_session.configure_engine(database_url)
    Base.metadata.create_all(db_session.get_engine())
    yield TestClient(create_app())
    get_settings.cache_clear()
    db_session.configure_engine()


def test_customer_not_found_returns_structured_error(client: TestClient) -> None:
    """Unknown customer returns SPEC error envelope."""
    response = client.get(f"/api/v1/customers/{uuid.uuid4()}/balances")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "CUSTOMER_NOT_FOUND"
    assert payload["message"]
    assert payload["trace_id"] == response.headers["X-Trace-ID"]


def test_duplicate_email_returns_structured_error(client: TestClient) -> None:
    """Duplicate email returns SPEC error envelope."""
    body = {"name": "Jane", "email": "dup@example.com"}
    client.post("/api/v1/customers", json=body)
    response = client.post("/api/v1/customers", json=body)
    assert response.status_code == 409
    payload = response.json()
    assert payload["error_code"] == "DUPLICATE_EMAIL"
    assert payload["trace_id"] == response.headers["X-Trace-ID"]


def test_invalid_currency_pair_returns_structured_error(client: TestClient) -> None:
    """Same source and destination currency returns INVALID_CURRENCY_PAIR."""
    create_response = client.post(
        "/api/v1/customers",
        json={"name": "Jane", "email": "pair@example.com"},
    )
    customer_id = create_response.json()["id"]

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
    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "INVALID_CURRENCY_PAIR"
    assert payload["trace_id"] == response.headers["X-Trace-ID"]
