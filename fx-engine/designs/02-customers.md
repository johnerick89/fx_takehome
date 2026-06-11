# 02 — Customers

## Goal

Implement the customer and balance domain models, Alembic migration, service
layer, and REST endpoints for customer creation, listing, and balance
management. After this step clients can create customers, list them, view
balances, and manually credit funds. No quotes, rates, or execution logic.

---

## Prerequisites

- `01 — Database` complete

---

## Models

### `app/models/customer.py`

```python
class Customer(BaseModel):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
```

`id`, `created_at`, and `updated_at` are inherited from `BaseModel`.

**Rationale (see `DECISIONS.md` §6):** A UUID-only customer is unusable in
practice. `email` is a unique natural lookup key; `name` makes list responses
human-readable. Both are minimum viable identifiers without crossing into KYC
territory.

### `app/models/balance.py`

```python
class Balance(BaseModel):
    __tablename__ = "balances"

    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))

    __table_args__ = (
        UniqueConstraint("customer_id", "currency", name="uq_balance_customer_currency"),
        CheckConstraint("amount >= 0", name="ck_balance_non_negative"),
    )
```

**Invariants:**

- One balance row per `(customer_id, currency)` pair.
- `amount` is never negative (DB constraint + service-layer validation).
- All four supported currencies get a zero-balance row on customer creation.

---

## Alembic Migration

`alembic/versions/<rev>_add_customers_and_balances.py`

- Create `customers` table with `name`, `email` (unique), and base columns.
- Create `balances` table with FK, unique constraint, and check constraint.

---

## Schemas (`app/schemas/customer.py`)

| Schema                    | Purpose                                                |
| ------------------------- | ------------------------------------------------------ |
| `CustomerCreate`          | `name`, `email`                                        |
| `CustomerResponse`        | `id`, `name`, `email`, `created_at`                    |
| `CustomerListResponse`    | `customers: list[CustomerResponse]`, `total`, `skip`, `limit` |
| `BalanceResponse`         | `currency`, `amount` (serialised as `string`)           |
| `BalanceListResponse`     | `customer_id`, `balances: list[BalanceResponse]`       |
| `BalanceCreditRequest`    | `currency`, `amount` (string)                          |
| `BalanceCreditResponse`   | `currency`, `amount`, `previous_amount`                |

All response schemas: `model_config = ConfigDict(from_attributes=True)`.
Amount fields use `Decimal` internally, serialised as `str` in JSON.

---

## Service Layer (`app/services/customer_service.py`)

### `create_customer(db: Session, name: str, email: str) -> Customer`

1. Insert `Customer` with `name` and `email`.
2. Insert four `Balance` rows (USD, EUR, KES, NGN) with `amount = 0`.
3. Commit and return customer.

All in a single transaction. On duplicate `email`, raise `DuplicateEmailError`
(map to `409` or `422` in the router — prefer `409 Conflict`).

### `list_customers(db: Session, skip: int = 0, limit: int = 50) -> tuple[list[Customer], int]`

- Return a paginated slice of customers and total count.
- `skip` and `limit` query params with sensible defaults (`limit` max 100).

### `get_balances(db: Session, customer_id: str) -> list[Balance]`

- Return all balance rows for customer.
- Raise `CustomerNotFoundError` if customer does not exist.

### `credit_balance(db: Session, customer_id: str, currency: str, amount: Decimal) -> Balance`

1. Validate `currency` is in `SUPPORTED_CURRENCIES`.
2. Validate `amount > 0` — raise `InvalidAmountError` otherwise.
3. Fetch customer; raise `CustomerNotFoundError` if missing.
4. Fetch balance row for `(customer_id, currency)`.
5. Add `amount` to balance, commit, return updated balance.

No `BEGIN IMMEDIATE` required for credit in this step — single-row update.
Concurrency-safe credit is not required by spec for the test-fixture endpoint.

---

## API Layer (`app/api/customers.py`)

Flat `app/api/` layout — no `routers/` subfolder (see `DECISIONS.md` §8).
Routers live directly under `app/api/`; `app/api/__init__.py` aggregates and
exports them for mounting in `main.py`.

Prefix: `/api/v1/customers`, tag: `customers`.

| Method | Path                                                | Status | Description              |
| ------ | --------------------------------------------------- | ------ | ------------------------ |
| `POST` | `/api/v1/customers`                                 | `201`  | Create customer          |
| `GET`  | `/api/v1/customers`                                 | `200`  | List customers (`skip`, `limit`) |
| `GET`  | `/api/v1/customers/{customer_id}/balances`          | `200`  | List all balances        |
| `POST` | `/api/v1/customers/{customer_id}/balances/credit`   | `200`  | Credit a balance         |

Register via `app/api/__init__.py` and mount in `app/main.py` via `create_app()`.

---

## Exception Stubs (`app/core/exceptions.py`)

Create minimal exception classes needed by this module:

- `CustomerNotFoundError`
- `DuplicateEmailError`
- `InvalidAmountError`
- `UnsupportedCurrencyError`

Full exception handler registration comes in `06-observability`. For now,
raise `HTTPException` directly in the router or register bare handlers — keep
handlers minimal so tests can assert status codes.

---

## Files to Create / Modify

| File                               | Action                                |
| ---------------------------------- | ------------------------------------- |
| `app/models/customer.py`           | Create                                |
| `app/models/balance.py`            | Create                                |
| `app/models/__init__.py`           | Modify — export models                |
| `app/schemas/customer.py`          | Create                                |
| `app/services/customer_service.py` | Create                                |
| `app/api/customers.py`             | Create — customer router              |
| `app/api/__init__.py`              | Modify — aggregate routers            |
| `app/core/exceptions.py`             | Create — stub exception classes       |
| `app/main.py`                      | Modify — include customers router     |
| `alembic/versions/`                | Modify — add customers migration      |

---

## Tests to Add (`tests/test_customers.py`)

- `POST /api/v1/customers` with `name` and `email` returns `201` with a UUID `id`.
- Duplicate `email` on create returns `409`.
- `GET /api/v1/customers` returns paginated list with `skip` and `limit`.
- New customer has four zero balances (verify via `GET .../balances`).
- `GET /api/v1/customers/{id}/balances` returns all four currencies.
- `GET` with unknown `customer_id` returns `404`.
- `POST .../balances/credit` increases balance correctly.
- Credit with `amount <= 0` returns `422`.
- Credit with unsupported currency returns `422`.
- Credit with unknown customer returns `404`.
- Amounts in JSON responses are strings, not floats.

---

## Acceptance Criteria

- [ ] Alembic migration applies cleanly after `01` migration
- [ ] Customer creation atomically creates four zero balances
- [ ] `email` is unique; duplicate create is rejected gracefully
- [ ] Balances never go negative
- [ ] All four endpoints work end-to-end
- [ ] All existing tests still pass
- [ ] New customer tests pass
- [ ] `pytest tests/ -v --cov=app` passes with no regressions

---

## Out of Scope for This Step

- Quote generation or execution
- Rate fetching
- `BEGIN IMMEDIATE` / row locking on balances
- Debit operations
- Structured error response envelope with `trace_id` (deferred to `06`)
- Property-based / Hypothesis tests (deferred to `04` and `05`)
