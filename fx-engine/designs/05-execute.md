# 05 — Execute

## Goal

Implement the FX execution critical path: atomic two-leg balance transfer,
quote state transition, concurrency safety, and idempotent retries. This is
the highest-risk module — every invariant in SPEC §6 and §8 must be enforced
and tested.

---

## Prerequisites

- `01 — Database` complete
- `02 — Customers` complete
- `03 — Rates` complete
- `04 — Quotes` complete

### SQLite concurrency prerequisite (critical)

`BEGIN IMMEDIATE` acquires a write lock, but SQLite's default behaviour when a
second connection tries to acquire that lock is to immediately raise
`SQLITE_BUSY`, not wait. Without `PRAGMA busy_timeout = 5000` on every
connection (set in `app/db/session.py`'s `connect` listener — see
`01-database.md`), the concurrency test will not produce clean `409`s. Losing
requests will raise raw `OperationalError: database is locked` exceptions,
likely surfacing as `500 INTERNAL_ERROR`.

Verify `busy_timeout` is configured before implementing execute. If the
database step predates this pragma, add it to `session.py` as part of this
step.

---

## Models

### `app/models/transaction.py`

```python
class Transaction(BaseModel):
    __tablename__ = "transactions"

    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), unique=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3))
    debited_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    credited_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

### `app/models/idempotency_log.py`

```python
class IdempotencyLog(BaseModel):
    __tablename__ = "idempotency_log"

    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    quote_id: Mapped[str] = mapped_column(String(36))
    transaction_id: Mapped[str] = mapped_column(String(36))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)   # serialised JSON
```

---

## Alembic Migration

`alembic/versions/<rev>_add_transactions_and_idempotency.py`

---

## Transaction Helper (`app/db/transaction.py`)

```python
@contextmanager
def immediate_transaction(db: Session) -> Generator[Session, None, None]:
    """BEGIN IMMEDIATE wrapper for SQLite concurrency safety."""
    db.execute(text("BEGIN IMMEDIATE"))
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
```

All execute-path DB work runs inside this context manager.

---

## Execute Service (`app/services/execute_service.py`)

### `execute_quote(db, quote_id, idempotency_key) -> ExecuteResult`

Full algorithm inside `immediate_transaction`:

```
0. Validate idempotency_key: non-empty and `len(idempotency_key) <= 128`.
   Empty/missing → `422 MISSING_IDEMPOTENCY_KEY`. Oversized → `422` before
   any DB write (do not rely on the `String(128)` column to reject it).
1. Check idempotency_log for existing key:
   - If found with same quote_id → return stored response (HTTP 200).
   - If found with different quote_id → raise IdempotencyKeyConflictError.
2. SELECT quote WHERE id = quote_id FOR UPDATE (SQLite: row locked via IMMEDIATE).
3. If quote not found → raise QuoteNotFoundError.
4. If quote.status == EXECUTED → raise QuoteAlreadyExecutedError.
5. If quote.expires_at < now() → raise QuoteExpiredError.
6. SELECT source balance FOR UPDATE.
7. If source balance < quote.source_amount → raise InsufficientBalanceError.
8. Debit source balance.
9. Credit destination balance.
10. Set quote.status = EXECUTED.
11. Insert Transaction record.
12. Insert IdempotencyLog with serialised response body.
13. COMMIT (via context manager).
```

On any failure from step 3 onward: `ROLLBACK`. Quote remains `PENDING`.

### Return type

```python
@dataclass
class ExecuteResult:
    transaction: Transaction
    is_replay: bool          # True when serving cached idempotency response
    http_status: int         # 201 for new, 200 for replay
```

### Idempotent replay and `ExecuteResult.transaction`

On replay, the response body comes from `idempotency_log.response_body`, not a
fresh execute. **`ExecuteResult.transaction` must still be populated** — on
replay, load the row via `db.get(Transaction, idempotency_log.transaction_id)`.
This adds one read query but keeps the return type consistent and lets the
router build `Location` and `ExecuteResponse` the same way for `200` and
`201`. Do not leave `transaction` implicit or optional.

---

## Schemas (`app/schemas/execute.py`)

| Schema            | Purpose                                   |
| ----------------- | ----------------------------------------- |
| `ExecuteResponse` | SPEC §6 output fields; amounts as strings |

No request body schema — `quote_id` from path, `Idempotency-Key` from header.

---

## API Routers

### `app/api/quotes.py` — execute

Add to existing quotes router:

| Method | Path                                | Status      | Description   |
| ------ | ----------------------------------- | ----------- | ------------- |
| `POST` | `/api/v1/quotes/{quote_id}/execute` | `201`/`200` | Execute quote |

**Headers:** `Idempotency-Key` required (non-empty, max 128 characters).

**Response headers on `201`:** `Location: /api/v1/transactions/{transaction_id}`.

Missing or empty `Idempotency-Key` → `422 MISSING_IDEMPOTENCY_KEY`.
Key longer than 128 characters → `422` (validate before DB insert).

### `app/api/transactions.py` — read (new)

Add a trivial read-only endpoint so the `Location` header on `201` is
verifiable in tests (not a dead link until `06`):

| Method | Path                                   | Status | Description        |
| ------ | -------------------------------------- | ------ | ------------------ |
| `GET`  | `/api/v1/transactions/{transaction_id}` | `200`  | Fetch transaction |

Returns `404` for unknown IDs. Register in `app/main.py`.

---

## Structured Logging (execute path)

Log these events via `get_logger` with extra fields:

| Event                       | Level | Extra fields                                                                  |
| --------------------------- | ----- | ----------------------------------------------------------------------------- |
| `execute.started`           | INFO  | `quote_id`, `customer_id`, `idempotency_key`                                  |
| `execute.success`           | INFO  | `quote_id`, `customer_id`, `debited_amount`, `credited_amount`, `duration_ms` |
| `execute.failed`            | WARN  | `quote_id`, `customer_id`, `error_code`                                       |
| `execute.idempotent_replay` | INFO  | `quote_id`, `idempotency_key`                                                 |

`trace_id` is injected automatically by the logging filter.

---

## Files to Create / Modify

| File                              | Action                              |
| --------------------------------- | ----------------------------------- |
| `app/models/transaction.py`       | Create                              |
| `app/models/idempotency_log.py`   | Create                              |
| `app/schemas/execute.py`          | Create                              |
| `app/db/transaction.py`           | Create — `immediate_transaction`    |
| `app/services/execute_service.py` | Create                              |
| `app/api/quotes.py`               | Modify — add execute endpoint       |
| `app/api/transactions.py`         | Create — `GET /transactions/{id}`  |
| `app/db/session.py`               | Modify — add `PRAGMA busy_timeout` if missing |
| `app/core/exceptions.py`          | Modify — all execute error classes  |
| `alembic/versions/`               | Modify — add transactions migration |

---

## Tests to Add (`tests/test_execute.py`)

### Happy path

- Execute valid quote → `201`, balances updated, quote `EXECUTED`.
- Response includes `Location` header pointing to a real transaction.
- `GET /api/v1/transactions/{transaction_id}` returns the created transaction.
- `debited_amount` and `credited_amount` match quote amounts.

### Invariant tests

| Scenario                         | Expected                      |
| -------------------------------- | ----------------------------- |
| Expired quote                    | `422 QUOTE_EXPIRED`           |
| Already executed quote           | `409 QUOTE_ALREADY_EXECUTED`  |
| Unknown quote                    | `404 QUOTE_NOT_FOUND`         |
| Insufficient balance             | `422 INSUFFICIENT_BALANCE`    |
| Missing `Idempotency-Key` header | `422 MISSING_IDEMPOTENCY_KEY` |

### Idempotency tests

- First execute → `201`. Retry with same key → `200`, identical body.
- Balances debited only once.
- Same key, different `quote_id` → `422 IDEMPOTENCY_KEY_CONFLICT`.
- `Idempotency-Key` longer than 128 characters → `422` (not a DB error).

### Concurrency test

- Fire **N** parallel `POST .../execute` requests for the same quote.
- Assert exactly **one** returns `201` (or `200` on its own retry).
- All others return `409 QUOTE_ALREADY_EXECUTED` — **not** `500` from
  `database is locked`.
- Balances reflect a single debit/credit.

Use `concurrent.futures.ThreadPoolExecutor` or `pytest` with threads.

**Requires `PRAGMA busy_timeout = 5000`** on all connections (see
Prerequisites). Without it, losing requests fail with `SQLITE_BUSY` before
they can read the committed quote state.

### Rollback test

Under normal conditions, crediting a balance (increasing it) cannot violate
the `amount >= 0` check constraint — there is no realistic business scenario
where the credit leg fails naturally. This test validates the rollback
**mechanism**, not a production failure mode.

Use an explicit test injection point, for example:

- `monkeypatch` the credit function to raise mid-transaction, or
- temporarily force an invalid state on the destination balance row.

Then assert full rollback: source balance unchanged, quote still `PENDING`,
no transaction row created.

---

## Acceptance Criteria

- [ ] Debit and credit are atomic — both succeed or neither
- [ ] `BEGIN IMMEDIATE` used on every execute call
- [ ] Idempotent retry returns `200` with original body
- [ ] `PRAGMA busy_timeout = 5000` configured on all DB connections
- [ ] Concurrency test: exactly one execution succeeds; losers get `409`
- [ ] Rollback test: injected credit failure leaves quote `PENDING`
- [ ] `GET /api/v1/transactions/{id}` returns created transaction
- [ ] `Idempotency-Key` length validated (max 128) before DB insert
- [ ] All error codes match SPEC §10
- [ ] Execute-path structured logs emitted
- [ ] All existing tests still pass
- [ ] `pytest tests/ -v --cov=app` passes with no regressions

---

## Out of Scope for This Step

- `GET /api/v1/transactions` list endpoint
- `GET /metrics` counters (deferred to `06`)
- Enhanced `GET /healthz` (deferred to `06`)
- Webhooks or async notifications
