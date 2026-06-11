# 02 — Customers

## Goal

Implement the customer and balance domain models, Alembic migration, service
layer, and REST endpoints for customer creation and balance management. After
this step clients can create customers, view balances, and manually credit
funds. No quotes, rates, or execution logic.

---

## Prerequisites

- `01 — Database` complete

---

## Models

### `app/models/customer.py`

```python
class Customer(BaseModel):
    __tablename__ = "customers"
    # id, created_at, updated_at inherited from BaseModel
```

No extra columns required beyond the base model for now.

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

- Create `customers` table.
- Create `balances` table with FK, unique constraint, and check constraint.

---

## Schemas (`app/schemas/customer.py`)

| Schema                    | Purpose                                      |
| ------------------------- | -------------------------------------------- |
| `CustomerCreate`          | Empty body (no fields required for now)      |
| `CustomerResponse`        | `id`, `created_at`                           |
| `BalanceResponse`         | `currency`, `amount` (serialised as `string`) |
| `BalanceListResponse`     | `customer_id`, `balances: list[BalanceResponse]` |
| `BalanceCreditRequest`    | `currency`, `amount` (string)                |
| `BalanceCreditResponse`   | `currency`, `amount`, `previous_amount`      |

All response schemas: `model_config = ConfigDict(from_attributes=True)`.
Amount fields use `Decimal` internally, serialised as `str` in JSON.

---

## Service Layer (`app/services/customer_service.py`)

### `create_customer(db: Session) -> Customer`

1. Insert `Customer`.
2. Insert four `Balance` rows (USD, EUR, KES, NGN) with `amount = 0`.
3. Commit and return customer.

All in a single transaction.

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

## API Router (`app/api/routers/customers.py`)

Prefix: `/api/v1/customers`, tag: `customers`.

| Method | Path                                     | Status | Description         |
| ------ | ---------------------------------------- | ------ | ------------------- |
| `POST` | `/api/v1/customers`                      | `201`  | Create customer     |
| `GET`  | `/api/v1/customers/{customer_id}/balances` | `200`  | List all balances   |
| `POST` | `/api/v1/customers/{customer_id}/balances/credit` | `200`  | Credit a balance |

Register router in `app/main.py` via `create_app()`.

---

## Exception Stubs (`app/core/exceptions.py`)

Create minimal exception classes needed by this module:

- `CustomerNotFoundError`
- `InvalidAmountError`
- `UnsupportedCurrencyError`

Full exception handler registration comes in `06-observability`. For now,
raise `HTTPException` directly in the router or register bare handlers — keep
handlers minimal so tests can assert status codes.

---

## Files to Create / Modify

| File                              | Action                                |
| --------------------------------- | ------------------------------------- |
| `app/models/customer.py`          | Create                                |
| `app/models/balance.py`           | Create                                |
| `app/models/__init__.py`          | Modify — export models                |
| `app/schemas/customer.py`         | Create                                |
| `app/services/customer_service.py`| Create                                |
| `app/api/routers/customers.py`    | Create                                |
| `app/api/routers/__init__.py`     | Create                                |
| `app/core/exceptions.py`          | Create — stub exception classes       |
| `app/main.py`                     | Modify — include customers router     |
| `alembic/versions/`               | Modify — add customers migration      |

---

## Tests to Add (`tests/test_customers.py`)

- `POST /api/v1/customers` returns `201` with a UUID `id`.
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
- [ ] Balances never go negative
- [ ] All three endpoints work end-to-end
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
