# AGENTS.md

This file provides guidance to Cursor when working with code in this repository.

## Project Structure

```
fx-engine/          ← you are here
├── app/
│   ├── main.py
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   └── db/
├── tests/
├── designs/
├── planted_bugs/
├── SPEC.md
├── DECISIONS.md
├── REVIEW.md
└── README.md
```

The `.venv` lives at the **parent directory** level (one level above `fx-engine/`). All commands below assume you activate it before running anything.

## Environment Setup

```bash
# Activate the shared venv from the repo root
source ../.venv/bin/activate   # macOS/Linux
# OR
..\\.venv\\Scripts\\activate   # Windows

# Install dependencies
pip install "fastapi[standard]"
pip install sqlalchemy alembic pydantic
pip install pytest pytest-asyncio httpx
pip install hypothesis
pip install aiosqlite
```

## Development Commands

### Run the app

```bash
uvicorn app.main:app --reload --port 8000
```

Always verify the app starts cleanly after any change before committing.

### Run tests

```bash
pytest tests/ -v
```

Run the full test suite after **every code change** — no exceptions. If tests fail, fix them before proceeding. Do not skip or comment out failing tests.

### After every change — checklist

1. `pytest tests/ -v` — all tests must pass
2. `uvicorn app.main:app --reload` — app must start without errors
3. Hit `/healthz` and confirm `200 OK`
4. Only then proceed to the next task

## Stack

- **Framework**: FastAPI
- **Database**: SQLite via SQLAlchemy (sync, with `check_same_thread=False` for concurrency tests)
- **Validation**: Pydantic v2 models
- **Migrations**: Alembic
- **Testing**: pytest + httpx `TestClient` + Hypothesis for property-based tests

## Coding Standards

### General

- Follow PEP 8. Use 4-space indentation, no tabs.
- All functions and methods must have type annotations.
- All public functions must have a one-line docstring minimum.
- No `# type: ignore` without an explanatory comment.
- No dead code, commented-out blocks, or debug `print()` statements in committed code. Use `logging` instead.

### Decimal Precision — Critical

- **Never use `float` for monetary amounts.** Always use `decimal.Decimal`.
- Declare `DECIMAL_PLACES` per currency in `app/core/currency.py`:
  - USD: 2, EUR: 2, KES: 2, NGN: 2
- Rounding mode: `ROUND_HALF_UP` everywhere.
- SQLAlchemy columns storing amounts must use `Numeric(precision=20, scale=8)`.
- Pydantic schemas must serialize amounts as strings, not floats, to avoid JSON precision loss.

```python
# Correct
from decimal import Decimal, ROUND_HALF_UP
amount = Decimal("100.50")

# Wrong — never do this
amount = 100.50
```

### SQLAlchemy Models

- Define all models in `app/models/`.
- Use `DeclarativeBase` (SQLAlchemy 2.x style).
- Every model must have a `created_at` and `updated_at` timestamp column.
- Use `UUID` primary keys (store as `String(36)`).

### Pydantic Schemas

- Define all schemas in `app/schemas/`.
- Keep request and response schemas separate (e.g. `QuoteCreate`, `QuoteResponse`).
- Use `model_config = ConfigDict(from_attributes=True)` on all response schemas.

### API Layer

- All routes live in `app/api/routers/`.
- Use `APIRouter` with a prefix and tags per module.
- Return structured error responses — never bare strings.
- All endpoints must include a correlation/trace ID in the response headers (`X-Trace-ID`).

### Concurrency and Atomicity

- All balance read-modify-write operations must use `SELECT ... FOR UPDATE` (or SQLite equivalent via explicit transactions with `BEGIN IMMEDIATE`).
- The `execute` endpoint is the most critical path — treat it with extreme care.
- Idempotency keys must be stored in the DB and checked before processing. A retry with the same key must return the original response, not re-execute.

### Error Handling

- Use custom exception classes defined in `app/core/exceptions.py`.
- FastAPI exception handlers must be registered in `app/main.py`.
- Never let SQLAlchemy exceptions bubble up to the API layer — catch and translate them.

### Logging and Observability

- Use Python's `logging` module configured in `app/core/logging.py`.
- Every log line in the execute path must include: `trace_id`, `quote_id`, `customer_id`, `action`.
- Structured logs (JSON format) in production mode, human-readable in dev.

## Design Docs

Before implementing any module, read the corresponding file in `designs/`. If a design doc does not exist for the module you are about to build, stop and ask. Do not infer design from the task description alone.

## Git Discipline

- Small, focused commits. One logical change per commit.
- Commit message format: `<type>(<scope>): <short description>` — e.g. `feat(quotes): add quote expiry validation`
- Never commit directly to `main`. Work in feature branches.
- A single "initial commit" with all code is not acceptable.

## What Cursor Should Not Do

- Do not change `SPEC.md`, `DECISIONS.md`, or `REVIEW.md` — those are human-authored artifacts.
- Do not swap out libraries (e.g. replace SQLAlchemy with Tortoise) without explicit instruction.
- Do not add dependencies to `requirements.txt` without being asked.
- Do not generate placeholder or stub implementations and leave them — either implement fully or raise a question.
- Do not use `float` for any monetary value under any circumstance.
