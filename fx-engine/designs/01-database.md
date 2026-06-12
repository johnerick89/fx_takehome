# 01 — Database

## Goal

Wire up SQLAlchemy 2.x, SQLite with WAL mode, Alembic migrations, and a
shared declarative base model. After this step the app can open a DB
connection and run migrations. No domain models, no API routes beyond what
already exists.

---

## Prerequisites

- `00 — App Scaffolding` complete
- `00_1 — Middleware` complete

---

## Configuration (`app/core/config.py`)

Create a `Settings` class using `pydantic-settings`:

```python
class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./fx.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

Load via a module-level `get_settings()` cached with `lru_cache`.

### `.env.example` additions

```
DATABASE_URL=sqlite:///./fx.db
```

---

## Currency Constants (`app/core/currency.py`)

Declare supported currencies and decimal precision only — no conversion logic
yet.

```python
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"USD", "EUR", "KES", "NGN"})
DECIMAL_PLACES: dict[str, int] = {"USD": 2, "EUR": 2, "KES": 2, "NGN": 2}
ROUNDING_MODE = ROUND_HALF_UP
```

---

## SQLAlchemy Setup

### `app/db/base.py`

- Define `Base(DeclarativeBase)`.
- Define `TimestampMixin` with `created_at` and `updated_at` columns
  (`DateTime(timezone=True)`). SQLite's `server_default` only fires on raw SQL
  inserts — SQLAlchemy ORM inserts bypass it. Both columns must set
  `server_default` **and** `default` so ORM inserts populate timestamps:

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    default=func.now(),
)
updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    default=func.now(),
    onupdate=func.now(),
)
```

- Define `UUIDPrimaryKeyMixin` with `id: Mapped[str]` as `String(36)` primary
  key (UUID stored as string per AGENTS.md). UUIDs must be generated
  **Python-side** — SQLite has no `gen_random_uuid()` equivalent:

```python
import uuid

id: Mapped[str] = mapped_column(
    String(36), primary_key=True, default=lambda: str(uuid.uuid4())
)
```

### `app/db/session.py`

- Create sync `engine` from `settings.database_url` with
  `connect_args={"check_same_thread": False}` for SQLite.
- Register a `@event.listens_for(Engine, "connect")` listener that executes:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

`busy_timeout` makes connections wait up to 5 seconds for a write lock instead
of immediately raising `SQLITE_BUSY`. Required for execute-path concurrency
(see `05-execute.md`) — without it, losing parallel requests surface raw
`OperationalError: database is locked` (likely `500`) instead of clean
`409 QUOTE_ALREADY_EXECUTED`.

- Export `SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)`.
- Export `get_db()` generator dependency for FastAPI:

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

### `app/db/__init__.py`

Re-export `Base`, `get_db`, `SessionLocal`, `engine`.

---

## Base Model (`app/models/base.py`)

```python
class BaseModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __abstract__ = True
```

All future domain models inherit from `BaseModel`. Do not create any domain
tables in this step.

---

## Alembic Init

Initialise Alembic at the `fx-engine/` root:

```
alembic/
├── env.py
├── script.py.mako
└── versions/
    └── <initial>_init.py
```

### `alembic/env.py`

- Import `Base` from `app.db.base`.
- Import `settings` from `app.core.config`.
- Set `target_metadata = Base.metadata`.
- Use sync engine (match `session.py`).

### Initial migration

Create an empty initial revision that establishes Alembic version tracking.
No tables yet — domain migrations come in later steps.

### `alembic.ini`

Set `sqlalchemy.url` to read from env or leave blank and override in `env.py`
from `settings.database_url`.

---

## App Startup Hook (`app/main.py`)

Add a lifespan context manager (or startup event) that:

1. Verifies DB connectivity with `SELECT 1`.
2. Logs success or raises on failure.

Do **not** auto-run Alembic migrations on startup — migrations are a manual
step documented in README.

---

## Files to Create / Modify

| File                        | Action                                              |
| --------------------------- | --------------------------------------------------- |
| `app/core/config.py`        | Create — `Settings`, `get_settings()`               |
| `app/core/currency.py`      | Create — currency constants only                    |
| `app/db/base.py`            | Create — `Base`, mixins                             |
| `app/db/session.py`         | Create — engine, WAL pragmas, `get_db()`            |
| `app/models/base.py`        | Create — abstract `BaseModel`                       |
| `alembic/`                  | Create — Alembic scaffold + empty initial migration |
| `alembic.ini`               | Create                                              |
| `app/main.py`               | Modify — lifespan DB connectivity check             |
| `.env.example`              | Modify — add `DATABASE_URL`                         |
| `requirements.txt`          | Modify — add `aiosqlite` if needed for test DB      |

---

## Tests to Add (`tests/test_database.py`)

- Engine connects and `SELECT 1` succeeds.
- `PRAGMA journal_mode` returns `wal` after connection.
- `get_db()` dependency yields a usable session and closes cleanly.
- `BaseModel` subclasses generate UUID string primary keys.

Use an isolated test database (`sqlite:///:memory:` or a temp file) via
`monkeypatch` on `settings.database_url` — never mutate the dev `fx.db`.

---

## Acceptance Criteria

- [ ] `alembic upgrade head` runs without errors
- [ ] `PRAGMA journal_mode` is `wal` on every connection
- [ ] `PRAGMA busy_timeout` is `5000` on every connection
- [ ] `get_db()` works as a FastAPI dependency
- [ ] App starts and passes DB connectivity check on startup
- [ ] All existing tests still pass
- [ ] New database tests pass
- [ ] `pytest tests/ -v --cov=app` passes with no regressions

---

## Out of Scope for This Step

- Customer, balance, quote, rate, or transaction models
- Alembic migrations for domain tables
- API routes beyond `/healthz`
- Exception handlers
- Rate fetching or background tasks
- `BEGIN IMMEDIATE` transaction helpers (added in `05-execute`)
