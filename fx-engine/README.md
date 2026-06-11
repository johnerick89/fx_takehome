# FX Engine

Foreign exchange engine for USD, EUR, KES, and NGN. See `SPEC.md` for the
full technical specification and `ASSIGNMENT.md` at the repo root for the
take-home brief.

## Running it

The virtual environment lives one level above `fx-engine/` (at the repo
root). Activate it, install dependencies, run tests, then start the app:

```bash
cd fx-engine
source ../.venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
pytest tests/ -v --cov=app
uvicorn app.main:app --reload --port 8000
```

Copy `.env.example` to `.env` if you need local environment variables:

```bash
cp .env.example .env
```

## Endpoints

- `GET /healthz` — returns `{"status": "ok"}`

## Status

Initial scaffolding only: directory layout, dependency manifest, test
infrastructure, and a health check. Business logic (quotes, execution,
rates, balances) is not implemented yet.
