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
cp .env.example .env            # adjust if needed
alembic upgrade head            # create / migrate SQLite database
pytest tests/ -v --cov=app
uvicorn app.main:app --reload --port 8000
```

The app verifies database connectivity on startup. Migrations are **not** run
automatically — run `alembic upgrade head` manually after pulling schema changes.

---

## Environment variables

| Variable        | Default                  | Description                                      |
| --------------- | ------------------------ | ------------------------------------------------ |
| `APP_ENV`       | `development`            | `development` → human-readable logs; else JSON   |
| `DATABASE_URL`  | `sqlite:///./fx.db`      | SQLAlchemy database URL (SQLite in development)  |

---

## API documentation

FastAPI serves interactive docs out of the box (only available while the app is running):

| URL                 | Description              |
| ------------------- | ------------------------ |
| `/docs`             | Swagger UI               |
| `/redoc`            | ReDoc                    |
| `/openapi.json`     | OpenAPI 3 schema (JSON)  |

---

## Endpoints

### Implemented

| Method | Path        | Description                                      |
| ------ | ----------- | ------------------------------------------------ |
| `GET`  | `/healthz`  | Health check — returns `{"status": "ok"}`        |

Every response includes an `X-Trace-ID` header (generated or client-supplied).

### Planned (see `SPEC.md` and `designs/`)

| Method | Path                                        | Description                    |
| ------ | ------------------------------------------- | ------------------------------ |
| `POST` | `/api/v1/customers`                         | Create customer                |
| `GET`  | `/api/v1/customers/{id}/balances`           | View balances                  |
| `POST` | `/api/v1/customers/{id}/balances/credit`    | Credit balance (test fixture)  |
| `GET`  | `/api/v1/rates`                             | List cached exchange rates     |
| `POST` | `/api/v1/rates/refresh`                     | Trigger rate refresh           |
| `POST` | `/api/v1/quotes`                            | Generate FX quote              |
| `POST` | `/api/v1/quotes/{quote_id}/execute`          | Execute quote (`Idempotency-Key` header required) |
| `GET`  | `/metrics`                                  | System metrics (JSON)          |

---

## Middleware

Registered in `app/main.py` (outermost → innermost):

1. **RequestLoggingMiddleware** — logs method, path, status, duration, trace ID
2. **TraceIDMiddleware** — sets `X-Trace-ID` on every request/response
3. **CORSMiddleware** — allows all origins (tighten in production)

### Example log output (development)

```
INFO  [trace_id=abc123] → GET /healthz
INFO  [trace_id=abc123] ← 200 GET /healthz 4ms
```

---

## Database

- **Engine:** SQLAlchemy 2.x, sync sessions
- **Database:** SQLite (`fx.db` by default)
- **WAL mode:** enabled on every connection (`PRAGMA journal_mode=WAL`)
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

Test suites: health, middleware, logging, database.

---

## Implementation status

| Step | Module        | Status      |
| ---- | ------------- | ----------- |
| 00   | Scaffolding   | Done        |
| 00_1 | Middleware    | Done        |
| 01   | Database      | Done        |
| 02   | Customers     | Not started |
| 03   | Rates         | Not started |
| 04   | Quotes        | Complete    |
| 05   | Execute       | Not started |
| 06   | Observability | Not started |
