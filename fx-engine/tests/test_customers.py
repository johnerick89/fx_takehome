"""Customer API tests."""

import uuid
from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import create_app
from app.models import Balance, Customer  


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Provide a test client backed by an isolated SQLite database."""
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    db_session.configure_engine(database_url)
    Base.metadata.create_all(db_session.get_engine())
    yield TestClient(create_app())
    get_settings.cache_clear()
    db_session.configure_engine()


def _create_customer(client: TestClient, name: str = "Jane Doe", email: str = "jane@example.com") -> dict:
    """Create a customer and return the response JSON."""
    response = client.post(
        "/api/v1/customers",
        json={"name": name, "email": email},
    )
    assert response.status_code == 201
    return response.json()


def test_create_customer_returns_uuid(client: TestClient) -> None:
    """POST /api/v1/customers returns 201 with a UUID id."""
    payload = _create_customer(client, email="alice@example.com")
    parsed = uuid.UUID(payload["id"], version=4)
    assert str(parsed) == payload["id"]
    assert payload["name"] == "Jane Doe"
    assert payload["email"] == "alice@example.com"


def test_duplicate_email_returns_409(client: TestClient) -> None:
    """Duplicate email on create returns 409."""
    _create_customer(client, email="dup@example.com")
    response = client.post(
        "/api/v1/customers",
        json={"name": "Other", "email": "dup@example.com"},
    )
    assert response.status_code == 409


def test_list_customers_paginated(client: TestClient) -> None:
    """GET /api/v1/customers returns paginated list with skip and limit."""
    _create_customer(client, name="One", email="one@example.com")
    _create_customer(client, name="Two", email="two@example.com")
    _create_customer(client, name="Three", email="three@example.com")

    response = client.get("/api/v1/customers", params={"skip": 1, "limit": 1})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["skip"] == 1
    assert payload["limit"] == 1
    assert len(payload["customers"]) == 1


def test_new_customer_has_four_zero_balances(client: TestClient) -> None:
    """New customer has four zero balances."""
    customer = _create_customer(client, email="balances@example.com")
    response = client.get(f"/api/v1/customers/{customer['id']}/balances")
    assert response.status_code == 200
    balances = response.json()["balances"]
    assert len(balances) == 4
    currencies = {balance["currency"] for balance in balances}
    assert currencies == {"USD", "EUR", "KES", "NGN"}
    assert all(balance["amount"] == "0.00" for balance in balances)


def test_get_balances_returns_all_currencies(client: TestClient) -> None:
    """GET /api/v1/customers/{id}/balances returns all four currencies."""
    customer = _create_customer(client, email="all@example.com")
    response = client.get(f"/api/v1/customers/{customer['id']}/balances")
    assert response.status_code == 200
    assert len(response.json()["balances"]) == 4


def test_get_balances_unknown_customer_returns_404(client: TestClient) -> None:
    """GET with unknown customer_id returns 404."""
    response = client.get(f"/api/v1/customers/{uuid.uuid4()}/balances")
    assert response.status_code == 404


def test_credit_balance_increases_amount(client: TestClient) -> None:
    """POST .../balances/credit increases balance correctly."""
    customer = _create_customer(client, email="credit@example.com")
    response = client.post(
        f"/api/v1/customers/{customer['id']}/balances/credit",
        json={"currency": "USD", "amount": "100.50"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["currency"] == "USD"
    assert payload["previous_amount"] == "0.00"
    assert payload["amount"] == "100.50"

    balances = client.get(f"/api/v1/customers/{customer['id']}/balances").json()["balances"]
    usd_balance = next(balance for balance in balances if balance["currency"] == "USD")
    assert usd_balance["amount"] == "100.50"


def test_credit_invalid_amount_returns_422(client: TestClient) -> None:
    """Credit with amount <= 0 returns 422."""
    customer = _create_customer(client, email="invalid-amt@example.com")
    response = client.post(
        f"/api/v1/customers/{customer['id']}/balances/credit",
        json={"currency": "USD", "amount": "0"},
    )
    assert response.status_code == 422


def test_credit_unsupported_currency_returns_422(client: TestClient) -> None:
    """Credit with unsupported currency returns 422."""
    customer = _create_customer(client, email="bad-currency@example.com")
    response = client.post(
        f"/api/v1/customers/{customer['id']}/balances/credit",
        json={"currency": "GBP", "amount": "10"},
    )
    assert response.status_code == 422


def test_credit_unknown_customer_returns_404(client: TestClient) -> None:
    """Credit with unknown customer returns 404."""
    response = client.post(
        f"/api/v1/customers/{uuid.uuid4()}/balances/credit",
        json={"currency": "USD", "amount": "10"},
    )
    assert response.status_code == 404


def test_balance_amounts_are_strings(client: TestClient) -> None:
    """Amounts in JSON responses are strings, not floats."""
    customer = _create_customer(client, email="strings@example.com")
    client.post(
        f"/api/v1/customers/{customer['id']}/balances/credit",
        json={"currency": "KES", "amount": "1000.00"},
    )
    balances = client.get(f"/api/v1/customers/{customer['id']}/balances").json()["balances"]
    kes_balance = next(balance for balance in balances if balance["currency"] == "KES")
    assert isinstance(kes_balance["amount"], str)
