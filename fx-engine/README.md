# FX Engine

Foreign exchange engine for USD, EUR, KES, and NGN. See [`SPEC.md`](SPEC.md) for the
full technical specification and [`ASSIGNMENT.md`](../ASSIGNMENT.md) at the repo root
for the take-home brief.

Design docs for each module live in [`designs/`](designs/).

---

## Running it

The virtual environment lives one level above `fx-engine/` (at the repo root).

```bash
cd fx-engine
source ../.venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
pytest tests/ -v --cov=app
uvicorn app.main:app --reload --port 8000
```

The app verifies database connectivity on startup. Migrations are **not** run
automatically — run `alembic upgrade head` manually after pulling schema changes.

---

## Environment variables

| Variable                     | Default             | Description                                     |
| ---------------------------- | ------------------- | ----------------------------------------------- |
| `APP_ENV`                    | `development`       | `development` → human-readable logs; else JSON  |
| `DATABASE_URL`               | `sqlite:///./fx.db` | SQLAlchemy database URL (SQLite in development) |
| `OPEN_EXCHANGE_RATES_APP_ID` | —                   | Primary rate provider (Open Exchange Rates)     |
| `EXCHANGE_RATE_API_KEY`      | —                   | Fallback rate provider (ExchangeRate-API)       |

---

## API documentation

FastAPI serves interactive docs out of the box (only available while the app is running):

| URL             | Description             |
| --------------- | ----------------------- |
| `/docs`         | Swagger UI              |
| `/redoc`        | ReDoc                   |
| `/openapi.json` | OpenAPI 3 schema (JSON) |

---

## Endpoints

All routes below are implemented. See [`SPEC.md`](SPEC.md) for request/response
shapes and error semantics.

| Method | Path                                     | Description                                       |
| ------ | ---------------------------------------- | ------------------------------------------------- |
| `GET`  | `/healthz`                               | Health check (DB connectivity + rates freshness)  |
| `GET`  | `/metrics`                               | System metrics (JSON)                             |
| `POST` | `/api/v1/customers`                      | Create customer                                   |
| `GET`  | `/api/v1/customers`                      | List customers (paginated)                        |
| `GET`  | `/api/v1/customers/{id}/balances`        | View balances                                     |
| `POST` | `/api/v1/customers/{id}/balances/credit` | Credit balance (test fixture)                     |
| `GET`  | `/api/v1/rates`                          | List cached exchange rates                        |
| `POST` | `/api/v1/rates/refresh`                  | Trigger rate refresh                              |
| `PUT`  | `/api/v1/rates/spreads/{base}/{quote}`   | Update corridor spread                            |
| `POST` | `/api/v1/quotes`                         | Generate FX quote                                 |
| `POST` | `/api/v1/quotes/{quote_id}/execute`      | Execute quote (`Idempotency-Key` header required) |
| `GET`  | `/api/v1/transactions/{transaction_id}`  | Fetch completed transaction                       |

Every response includes an `X-Trace-ID` header (generated or client-supplied).
Error responses use the structured envelope in SPEC §10 (`error_code`, `message`,
`trace_id`).

---

## Middleware

Registered in `app/main.py` (outermost → innermost):

1. **RequestLoggingMiddleware** — logs method, path, status, duration, trace ID
2. **TraceIDMiddleware** — sets `X-Trace-ID` on every request/response
3. **CORSMiddleware** — allows all origins

### Example log output

Development (human-readable):

```
INFO  [trace_id=abc123] → GET /healthz
INFO  [trace_id=abc123] ← 200 GET /healthz 4ms
INFO  [trace_id=def456] execute.success
```

Production (`APP_ENV=production`, JSON):

```json
{
  "timestamp": "2024-01-15T12:00:45.123456+00:00",
  "level": "INFO",
  "trace_id": "def456",
  "event": "execute.success",
  "action": "execute",
  "quote_id": "550e8400-e29b-41d4-a716-446655440000",
  "customer_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "debited_amount": "10000.00",
  "credited_amount": "77.54",
  "duration_ms": 12
}
```

---

## Database

- **Engine:** SQLAlchemy 2.x, sync sessions
- **Database:** SQLite (`fx.db` by default)
- **WAL mode:** enabled on every connection (`PRAGMA journal_mode=WAL`)
- **Busy timeout:** `PRAGMA busy_timeout=5000` for execute-path concurrency
- **Migrations:** Alembic (`alembic/`)
- **Base model:** UUID primary keys (Python-side `uuid.uuid4()`), `created_at` / `updated_at` timestamps

```bash
alembic upgrade head      # apply migrations
alembic revision -m "…"   # create a new migration
```

---

## Project structure

```
fx-engine/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── api/                 # routers (per module)
│   ├── core/                # config, logging, currency constants
│   ├── db/                  # engine, session, base mixins
│   ├── middlewares/         # trace ID, request logging
│   ├── models/              # SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response models
│   └── services/            # business logic
├── alembic/                 # database migrations
├── designs/                 # incremental design docs
├── tests/
├── SPEC.md
├── DECISIONS.md
└── AGENTS.md
```

---

## Testing

```bash
pytest tests/ -v --cov=app
```

Test suites: health, metrics, errors, middleware, logging, database, customers, rates, quotes, execute.

---

## Implementation status

All design modules are **complete**.

| Step | Module        | Status   |
| ---- | ------------- | -------- |
| 00   | Scaffolding   | Complete |
| 00_1 | Middleware    | Complete |
| 01   | Database      | Complete |
| 02   | Customers     | Complete |
| 03   | Rates         | Complete |
| 04   | Quotes        | Complete |
| 05   | Execute       | Complete |
| 06   | Observability | Complete |

### Assignment requirements

| Requirement                                | Status | Evidence                                               |
| ------------------------------------------ | ------ | ------------------------------------------------------ |
| Decimal precision + property tests         | Done   | `SPEC.md` §3, `tests/test_quotes_properties.py`        |
| Concurrency safety on execute              | Done   | `tests/test_execute.py`                                |
| Idempotency on execute                     | Done   | `tests/test_execute.py`                                |
| Atomic two-leg execution + rollback        | Done   | `tests/test_execute.py`                                |
| Rate-source failure handling               | Done   | `SPEC.md` §4, `tests/test_rates.py`                    |
| Observability (health, metrics, trace IDs) | Done   | `/healthz`, `/metrics`, middleware, log examples above |

---

## Known limitations

- **SQLite** serialises writes (`BEGIN IMMEDIATE`). Fine for demonstrating concurrency
  invariants; not suitable for high-throughput production without migrating to Postgres.
- **No auth/authz** — all endpoints are open (explicitly out of scope).
- **No fund reservation at quote time** — balance is checked only at execute; a quote
  can succeed even if the customer cannot afford it until execute is attempted.
- **Blunt validation mapping** — non-amount Pydantic errors also return `INVALID_AMOUNT`.
- **Property tests are narrow** — Hypothesis covers direct-pair rounding invariants;
  cross-pair properties are not exhaustive.
- **Concurrency evidence via pytest only** — no standalone load-test script; see
  `tests/test_execute.py::test_execute_concurrency_only_one_succeeds`.
- **Rate provider keys optional for tests** — live `POST /rates/refresh` needs
  `OPEN_EXCHANGE_RATES_APP_ID` and/or `EXCHANGE_RATE_API_KEY` in `.env`.
- **`/metrics` is JSON-only** — not Prometheus text format.

Assumptions and ambiguities are documented in [`SPEC.md`](SPEC.md) §14.

---

## What I would do with another day

See [`DECISIONS.md`](DECISIONS.md#what-i-would-do-with-another-day) for observability,
security, API completeness, hardening, and Postgres migration plans.
