# 00 — App Scaffolding

## Goal

Create the bare-bones directory structure, entry point, dependency manifest,
and test infrastructure. No business logic. The app should start and return
a 200 from `/healthz`. Tests should run and pass.

---

## Directory Structure to Create

```
fx-engine/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   └── __init__.py
│   ├── core/
│   │   └── __init__.py
│   ├── models/
│   │   └── __init__.py
│   ├── schemas/
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   └── db/
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   └── test_health.py
├── requirements.txt
├── .env.example
└── pytest.ini
```

---

## Tasks

### 1. `requirements.txt`

Add the following dependencies:

```
fastapi[standard]
sqlalchemy
alembic
pydantic
pydantic-settings
pytest
pytest-asyncio
pytest-cov
httpx
hypothesis
python-dotenv
```

### 2. `app/main.py`

- Create a FastAPI app instance.
- Mount a `/healthz` GET endpoint that returns `{"status": "ok"}` with HTTP 200.
- No database connection yet — keep it minimal.

### 3. `pytest.ini`

Configure pytest with:

- `testpaths = tests`
- `asyncio_mode = auto`
- Coverage reporting via `pytest-cov` pointing at `app/`

### 4. `tests/test_health.py`

Write one test:

- `GET /healthz` returns `200` with body `{"status": "ok"}`.
- Use `httpx.TestClient`.

### 5. `.env.example`

```
APP_ENV=development
```

---

## Acceptance Criteria

- [ ] `pip install -r requirements.txt` completes without errors
- [ ] `uvicorn app.main:app --reload` starts on port 8000 without errors
- [ ] `GET /healthz` returns `200 OK`
- [ ] `pytest tests/ -v --cov=app` runs and the one health test passes
- [ ] Coverage report is generated

---

## Out of Scope for This Step

- Database setup
- Alembic migrations
- Any business logic
- Environment-specific config loading
- Routers beyond `/healthz`
