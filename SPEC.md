# SPEC.md — FX Engine Technical Specification

**Version:** 1.0  
**Author:** John Mboga  
**Stack:** FastAPI · SQLite · SQLAlchemy 2.x · Pydantic v2

---

## 1. Scope

This system provides a foreign exchange engine with per-customer multi-currency balances. It supports quote generation, quote execution, live rate fetching, and customer balance management.

**In scope:**

- Quote generation with expiry
- Atomic two-leg FX execution
- Idempotent execution with retry safety
- Concurrency-safe balance updates
- Rate fetching with spread application and staleness handling
- Customer creation and balance management
- Observability: health check, structured logs, trace IDs, metrics endpoint

**Out of scope:**

- Authentication and authorisation
- KYC / compliance checks
- Multi-tenancy
- Webhooks or async notifications
- Production deployment / TLS
- Currency pairs beyond the 9 specified pairs and their inverses

---

## 2. Supported Currencies and Pairs

### Currencies

| Code | Name            | Minor Units | Max Decimal Places |
| ---- | --------------- | ----------- | ------------------ |
| USD  | US Dollar       | cents       | 2                  |
| EUR  | Euro            | cents       | 2                  |
| KES  | Kenyan Shilling | cents       | 2                  |
| NGN  | Nigerian Naira  | kobo        | 2                  |

### Direct Pairs

USD/KES, USD/NGN, USD/EUR, EUR/KES, EUR/NGN, KES/NGN — plus all inverses (18 pairs total).

### Cross-Pair Routing

Pairs without a direct rate are routed through USD first, then EUR as fallback.

**Routing rule:** For pair A→C with no direct rate, resolve as A→USD→C. If A→USD or USD→C is also unavailable, attempt A→EUR→C. If neither route resolves, return `422 Unprocessable Entity` with `error_code: ROUTE_UNAVAILABLE`.

**Spread compounding on cross pairs:** Each leg applies its own spread independently. The effective spread on a cross pair is therefore additive (not multiplicative). This is documented explicitly in responses via `routing_path` and `effective_rate` fields.

---

## 3. Decimal Precision and Rounding

- **Internal representation:** `decimal.Decimal` throughout. `float` is banned.
- **Rounding mode:** `ROUND_HALF_UP` at every rounding point.
- **Intermediate calculations:** Full precision maintained until the final output amount is produced.
- **Storage:** SQLAlchemy `Numeric(precision=20, scale=8)` columns for all monetary values.
- **API serialisation:** Amounts serialised as `string` in JSON responses to prevent IEEE 754 precision loss.
- **Display precision:** Final amounts rounded to the destination currency's minor units (2 d.p. for all supported currencies).
- **Rate precision:** Exchange rates stored and returned at 8 decimal places.

### Rounding example

`1000 KES → USD` at rate `0.00775432`:  
`1000 × 0.00775432 = 7.75432000` → rounded to `7.75 USD`.

---

## 4. Exchange Rates

### Source

Primary: [Open Exchange Rates](https://openexchangerates.org/) free tier (USD base).  
Fallback: [ExchangeRate-API](https://exchangeratesapi.io/) free tier.

### Spread Model

Each currency pair has a configurable **buy spread** and **sell spread** (default: 0.5% each, stored in DB). Applied as:

```
buy_rate  = mid_rate × (1 + buy_spread)   # customer buys foreign currency (we sell)
sell_rate = mid_rate × (1 - sell_spread)  # customer sells foreign currency (we buy)
```

Spreads are stored per-pair in the `corridor_spread` table and can be updated via admin endpoint.

### Rate Freshness Policy

| Condition                        | Behaviour                                                                       |
| -------------------------------- | ------------------------------------------------------------------------------- |
| Rate age < 10 minutes            | Serve normally                                                                  |
| Rate age 10–60 minutes           | Serve with `stale: true` flag in response                                       |
| Rate age > 60 minutes            | Reject quote requests with `503 Service Unavailable`, `error_code: RATES_STALE` |
| Rates API unreachable            | Use last cached rates if age < 60 min; otherwise return `503`                   |
| Rates API returns malformed data | Log error, retain previous rates, return `503` if no valid cache                |

Rate fetch is attempted on startup and then every 5 minutes via a background task.

---

## 5. Quote Generation

### Endpoint

`POST /api/v1/quotes`

### Input

```json
{
  "customer_id": "uuid",
  "from_currency": "KES",
  "to_currency": "USD",
  "amount": "10000.00",
  "amount_side": "source"
}
```

`amount_side`: `source` (you sell this much) or `destination` (you want to receive this much).

### Output

```json
{
  "quote_id": "uuid",
  "customer_id": "uuid",
  "from_currency": "KES",
  "to_currency": "USD",
  "source_amount": "10000.00",
  "destination_amount": "77.54",
  "exchange_rate": "0.00775432",
  "rate_includes_spread": true,
  "routing_path": ["KES", "USD"],
  "stale": false,
  "expires_at": "2024-01-15T12:01:00Z",
  "created_at": "2024-01-15T12:00:00Z"
}
```

### Invariants

- Quote is valid for exactly **60 seconds** from `created_at`.
- A quote does **not** lock or reserve customer funds at generation time.
- A quote is single-use: once executed or expired it cannot be re-used.
- Generating a quote does not require the customer to have sufficient balance.
- `source_amount × exchange_rate = destination_amount` (after rounding) must hold exactly for direct pairs. For cross pairs, `effective_rate` is the compounded rate.

---

## 6. FX Execution

### Endpoint

`POST /api/v1/quotes/{quote_id}/execute`

### Input

**Path parameter:** `quote_id`

**Required header:** `Idempotency-Key: <client-generated-uuid>`

Request body is empty. All execution parameters are derived from the quote.

```http
POST /api/v1/quotes/{{quoteId}}/execute
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
```

### Output (success — `HTTP 201 Created`)

Response includes `Location: /api/v1/transactions/{transaction_id}` header.

```json
{
  "transaction_id": "uuid",
  "quote_id": "uuid",
  "customer_id": "uuid",
  "from_currency": "KES",
  "to_currency": "USD",
  "debited_amount": "10000.00",
  "credited_amount": "77.54",
  "exchange_rate": "0.00775432",
  "executed_at": "2024-01-15T12:00:45Z",
  "idempotency_key": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Execution Invariants

1. **Expiry check:** Quote must not be expired at time of execution. Return `422`, `error_code: QUOTE_EXPIRED`.
2. **Single-use:** Quote must be in `PENDING` state. If already `EXECUTED`, return `409`, `error_code: QUOTE_ALREADY_EXECUTED`.
3. **Sufficient balance:** Customer must have enough `from_currency` balance. Return `422`, `error_code: INSUFFICIENT_BALANCE`.
4. **Atomicity:** Debit source balance and credit destination balance in a single DB transaction. If the credit leg fails (e.g. would violate a constraint), the debit is rolled back. The quote state is only updated to `EXECUTED` after both legs succeed.
5. **Concurrency safety:** The quote row is locked with `SELECT ... FOR UPDATE` (SQLite: `BEGIN IMMEDIATE`) before state check. Only one concurrent execution of the same quote can proceed; others receive `409`.
6. **Idempotency:** If the `Idempotency-Key` header matches a previous successful execution, return the original response with `HTTP 200`. No re-execution occurs. Keys are stored in the `idempotency_log` table. A missing `Idempotency-Key` header returns `422`, `error_code: MISSING_IDEMPOTENCY_KEY`.

### What happens when the second leg would go negative

If the destination balance credit would cause any invariant violation (or the debit succeeds but the credit raises an exception), the entire transaction is rolled back via SQLAlchemy's `session.rollback()`. The quote remains `PENDING`. This is tested explicitly.

---

## 7. Customer Balances

### Endpoints

| Method | Path                                     | Description                              |
| ------ | ---------------------------------------- | ---------------------------------------- |
| `POST` | `/api/v1/customers`                      | Create customer                          |
| `GET`  | `/api/v1/customers/{id}/balances`        | View all balances                        |
| `POST` | `/api/v1/customers/{id}/balances/credit` | Manually credit a balance (test fixture) |

### Balance Invariants

- A balance record is created with `amount = 0` for each supported currency when a customer is created.
- Balances can never go below zero. Any operation that would result in a negative balance is rejected.
- Balance updates use `BEGIN IMMEDIATE` transactions in SQLite to prevent lost updates under concurrency.

---

## 8. Concurrency Model

SQLite is used with `check_same_thread=False` and WAL mode enabled (`PRAGMA journal_mode=WAL`). This allows concurrent reads with serialised writes.

For the execute path specifically:

1. Open `BEGIN IMMEDIATE` transaction (acquires write lock upfront).
2. Read quote state.
3. Check expiry and single-use invariant.
4. Read customer balance.
5. Check sufficient balance.
6. Debit source balance.
7. Credit destination balance.
8. Mark quote as `EXECUTED`.
9. Write idempotency log entry.
10. `COMMIT`.

If any step from 3 onwards fails, `ROLLBACK` is issued. Steps 1–10 are serialised per-customer by the DB write lock, preventing double-execution.

---

## 9. Idempotency

- `Idempotency-Key` is a client-supplied request header (UUID recommended, max 128 chars).
- The header is **required** on `POST /api/v1/quotes/{quote_id}/execute`. Omitting it returns `422`, `error_code: MISSING_IDEMPOTENCY_KEY`.
- On first request: execute normally, store `{idempotency_key, transaction_id, response_body}` in `idempotency_log`.
- On retry with same key: return stored response with `HTTP 200`, skip all execution logic.
- Idempotency keys do not expire.
- A key used for one `quote_id` cannot be reused for a different `quote_id` — return `422`, `error_code: IDEMPOTENCY_KEY_CONFLICT`.

---

## 10. API Error Semantics

All error responses follow this shape:

```json
{
  "error_code": "QUOTE_EXPIRED",
  "message": "The quote expired at 2024-01-15T12:01:00Z",
  "trace_id": "uuid"
}
```

| Error Code                 | HTTP Status | Meaning                                    |
| -------------------------- | ----------- | ------------------------------------------ |
| `QUOTE_EXPIRED`            | 422         | Quote TTL elapsed                          |
| `QUOTE_ALREADY_EXECUTED`   | 409         | Quote already used                         |
| `QUOTE_NOT_FOUND`          | 404         | Unknown quote ID                           |
| `INSUFFICIENT_BALANCE`     | 422         | Not enough source balance                  |
| `RATES_STALE`              | 503         | Cached rates too old                       |
| `ROUTE_UNAVAILABLE`        | 422         | No routing path for pair                   |
| `CUSTOMER_NOT_FOUND`       | 404         | Unknown customer ID                        |
| `IDEMPOTENCY_KEY_CONFLICT` | 422         | Key reused for different quote             |
| `MISSING_IDEMPOTENCY_KEY`  | 422         | `Idempotency-Key` header absent on execute |
| `INVALID_AMOUNT`           | 422         | Amount ≤ 0 or non-numeric                  |
| `INTERNAL_ERROR`           | 500         | Unexpected server fault                    |

---

## 11. Observability

### Health Check

`GET /healthz` — returns `200 OK` with DB connectivity and rates freshness status:

```json
{
  "status": "ok",
  "db": "ok",
  "rates_age_seconds": 142,
  "rates_status": "fresh"
}
```

### Metrics

`GET /metrics` — returns JSON with:

- Total quotes generated
- Total executions (successful / failed)
- Rates last updated timestamp
- Active (unexpired, unexecuted) quote count

### Trace IDs

Every request receives a `trace_id` (UUID) injected by middleware. It is:

- Returned in `X-Trace-ID` response header on all responses.
- Included in every log line produced during that request.
- Included in all error response bodies.

### Structured Logging

Log format (JSON in production, human-readable in dev):

```json
{
  "timestamp": "2024-01-15T12:00:45.123Z",
  "level": "INFO",
  "trace_id": "uuid",
  "event": "execute.success",
  "quote_id": "uuid",
  "customer_id": "uuid",
  "debited_amount": "10000.00",
  "credited_amount": "77.54",
  "duration_ms": 12
}
```

---

## 12. Rate Fetch Failure Handling (Summary)

Documented fully in Section 4. In brief:

- Stale rates (10–60 min): serve with warning flag.
- Very stale rates (>60 min): block quote generation, return `503`.
- API down: fall back to cache; fail gracefully if cache also stale.
- Malformed API response: retain last good rates, log error, do not crash.

The rates fetch background task must never crash the application on failure — all exceptions are caught, logged, and retried on the next cycle.

---

## 13. Out of Scope (Explicit)

- Auth / JWT / API keys
- Rate limiting
- Webhook callbacks on execution
- Persistent quote history beyond what's in the DB
- Currency pairs outside the 9 specified
- Fiat ↔ crypto conversion
- Batch execution
- Admin UI
