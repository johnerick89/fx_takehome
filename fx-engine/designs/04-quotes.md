# 04 — Quotes

## Goal

Implement quote generation with 60-second expiry, cross-pair routing, spread-
inclusive rate calculation, and staleness handling. After this step clients
can request FX quotes. No execution, idempotency, or balance debits.

---

## Prerequisites

- `01 — Database` complete
- `02 — Customers` complete
- `03 — Rates` complete

---

## Model (`app/models/quote.py`)

```python
class QuoteStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"

class Quote(BaseModel):
    __tablename__ = "quotes"

    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3))
    source_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    destination_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    routing_path: Mapped[str] = mapped_column(String(64))   # JSON: ["KES","USD"]
    status: Mapped[str] = mapped_column(String(16), default=QuoteStatus.PENDING)
    stale_rate: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

`routing_path` stored as JSON string; deserialised in schemas.

---

## Alembic Migration

`alembic/versions/<rev>_add_quotes.py` — create `quotes` table.

---

## Routing (`app/services/routing_service.py`)

Resolve a conversion path for `(from_currency, to_currency)`:

1. If `from == to` → error (`INVALID_AMOUNT` or dedicated code).
2. If direct rate exists in cache → path `[from, to]`.
3. Else try `from → USD → to`.
4. Else try `from → EUR → to`.
5. Else raise `RouteUnavailableError`.

Return `RoutingResult`:

```python
@dataclass
class RoutingResult:
    path: list[str]              # e.g. ["KES", "USD", "EUR"]
    legs: list[RateLeg]          # one RateLeg per hop
    effective_rate: Decimal      # compounded rate for the full path
```

### Cross-pair rate compounding

For each leg, apply the appropriate spread:

- Customer **sells** `from_currency` → use `sell_rate` on first leg.
- Intermediate legs use sell/buy as direction dictates.
- Final leg delivers `to_currency` → use `buy_rate`.

Each leg applies its own spread independently (additive spread per SPEC §2).
Maintain full `Decimal` precision until final rounding.

### Effective rate

For direct pairs: `effective_rate = exchange_rate` used in calculation.

For cross pairs: compound leg rates, expose as `effective_rate` in response.

---

## Quote Service (`app/services/quote_service.py`)

### `create_quote(db, customer_id, from_currency, to_currency, amount, amount_side) -> Quote`

1. Validate customer exists.
2. Validate currencies are supported and distinct.
3. Validate `amount > 0`.
4. Resolve routing via `routing_service`.
5. Check rate staleness via `rate_service.get_rate()`:
   - If `blocked` → raise `RatesStaleError` (`503`).
6. Calculate `source_amount` and `destination_amount` based on `amount_side`:
   - `source`: fix source, compute destination.
   - `destination`: fix destination, back-solve source.
7. Round **final** amounts to destination/source currency decimal places
   (`ROUND_HALF_UP`).
8. Verify invariant: `source_amount × exchange_rate ≈ destination_amount`
   after rounding (direct pairs must hold exactly).
9. Set `expires_at = created_at + 60 seconds`.
10. Persist quote with `status = PENDING`.
11. Return quote.

**Does not** check customer balance. **Does not** lock funds.

---

## Schemas (`app/schemas/quote.py`)

| Schema           | Fields                                                                 |
| ---------------- | ---------------------------------------------------------------------- |
| `QuoteCreate`    | `customer_id`, `from_currency`, `to_currency`, `amount`, `amount_side` |
| `QuoteResponse`  | All output fields from SPEC §5; amounts/rates as strings               |

`amount_side`: `Literal["source", "destination"]`.

Response includes: `quote_id`, `routing_path`, `stale`, `expires_at`,
`created_at`, `rate_includes_spread: true`.

---

## API Router (`app/api/routers/quotes.py`)

Prefix: `/api/v1/quotes`, tag: `quotes`.

| Method | Path              | Status | Description      |
| ------ | ----------------- | ------ | ---------------- |
| `POST` | `/api/v1/quotes`  | `201`  | Generate a quote |

Register in `app/main.py`. No execute route in this step.

---

## Files to Create / Modify

| File                            | Action                              |
| ------------------------------- | ----------------------------------- |
| `app/models/quote.py`           | Create                              |
| `app/schemas/quote.py`          | Create                              |
| `app/services/routing_service.py` | Create                            |
| `app/services/quote_service.py` | Create                              |
| `app/api/routers/quotes.py`     | Create                              |
| `app/core/exceptions.py`        | Modify — `RouteUnavailableError`, `RatesStaleError` |
| `app/main.py`                   | Modify — include quotes router        |
| `alembic/versions/`             | Modify — add quotes migration         |

---

## Tests to Add (`tests/test_quotes.py`)

### Integration tests

- `POST /api/v1/quotes` direct pair (e.g. KES→USD) returns `201` with all
  required fields.
- Quote `expires_at` is exactly 60 seconds after `created_at`.
- Cross-pair (e.g. KES→EUR) returns `routing_path` with intermediate currency.
- Unknown customer → `404 CUSTOMER_NOT_FOUND`.
- Unsupported pair (no route) → `422 ROUTE_UNAVAILABLE`.
- Stale blocked rates → `503 RATES_STALE`.
- Stale warning rates (10–60 min) → `201` with `stale: true`.
- `amount <= 0` → `422 INVALID_AMOUNT`.
- Amounts in response are JSON strings.

### Rounding test (SPEC §3 example)

- `1000 KES → USD` at rate `0.00775432` → destination `7.75`.

### Hypothesis property tests (`tests/test_quotes_properties.py`)

- For random valid amounts and direct pairs, `source × rate` rounds to
  `destination` within currency precision.
- Routing never returns a path for identical currencies.

---

## Acceptance Criteria

- [ ] Quotes expire after exactly 60 seconds
- [ ] Quotes do not check or lock customer balance
- [ ] Cross-pair routing tries USD then EUR fallback
- [ ] Spread is applied per leg independently
- [ ] Staleness policy enforced (`stale` flag and `503` block)
- [ ] KES→USD rounding example passes
- [ ] Hypothesis property tests pass
- [ ] All existing tests still pass
- [ ] `pytest tests/ -v --cov=app` passes with no regressions

---

## Out of Scope for This Step

- Quote execution or balance debit/credit
- Idempotency
- `BEGIN IMMEDIATE` / row locking
- Quote status transitions to `EXECUTED` or `EXPIRED` (execute handles EXECUTED;
  optional lazy EXPIRED check deferred to `05`)
- `GET /metrics` quote counters (deferred to `06`)
