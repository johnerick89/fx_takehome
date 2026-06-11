# 03 — Rates

## Goal

Implement exchange rate storage, spread configuration, external rate fetching
with fallback, staleness policy, and a background refresh task. After this
step the system maintains a live rate cache queryable by internal services.
No quote generation or execution.

---

## Prerequisites

- `01 — Database` complete
- `02 — Customers` complete (not a hard dependency, but should be merged first)

---

## Models

### `app/models/exchange_rate.py`

Stores the latest mid-market rate per currency pair.

```python
class ExchangeRate(BaseModel):
    __tablename__ = "exchange_rates"

    base_currency: Mapped[str] = mapped_column(String(3))
    quote_currency: Mapped[str] = mapped_column(String(3))
    mid_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", name="uq_rate_pair"),
    )
```

Only store **direct** pairs from SPEC §2 (9 pairs + inverses = up to 18 rows).
Cross-pair rates are computed at quote time, not stored.

### `app/models/corridor_spread.py`

```python
class CorridorSpread(BaseModel):
    __tablename__ = "corridor_spreads"

    base_currency: Mapped[str] = mapped_column(String(3))
    quote_currency: Mapped[str] = mapped_column(String(3))
    buy_spread: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.005"))
    sell_spread: Mapped[Decimal] = mapped_column(Numeric(10, 8), default=Decimal("0.005"))

    __table_args__ = (
        UniqueConstraint("base_currency", "quote_currency", name="uq_spread_pair"),
    )
```

Default spread: `0.5%` (`0.005`) each side.

---

## Alembic Migration

`alembic/versions/<rev>_add_rates_tables.py`

- Create `exchange_rates` and `corridor_spreads` tables.
- Seed `corridor_spreads` with default `0.005` for all 18 direct pairs.

---

## Rate Provider (`app/services/rate_providers.py`)

Abstract the external API behind a protocol:

```python
class RateProvider(Protocol):
    def fetch_rates(self) -> dict[str, Decimal]: ...  # currency_code → rate vs USD
```

### Implementations

| Class                    | Source                                              |
| ------------------------ | --------------------------------------------------- |
| `OpenExchangeRatesProvider` | Primary — Open Exchange Rates free tier (USD base) |
| `ExchangeRateApiProvider`   | Fallback — ExchangeRate-API free tier              |

- Use `httpx` for HTTP calls.
- API keys loaded from settings (`OPEN_EXCHANGE_RATES_APP_ID`, `EXCHANGE_RATE_API_KEY`).
- Return parsed `Decimal` rates — never `float`.
- Raise `RateProviderError` on HTTP failure or malformed JSON.

### `.env.example` additions

```
OPEN_EXCHANGE_RATES_APP_ID=
EXCHANGE_RATE_API_KEY=
```

---

## Rate Service (`app/services/rate_service.py`)

### `refresh_rates(db: Session) -> None`

1. Try primary provider; on failure, try fallback.
2. On success: upsert all applicable `ExchangeRate` rows, set `fetched_at = now()`.
3. On total failure: log error, retain existing cache (do not delete rates).
4. On malformed data: log error, retain existing cache.
5. Never raise unhandled exceptions — caller (background task) must not crash.

### `get_rate(db: Session, base: str, quote: str) -> RateResult`

Returns a dataclass:

```python
@dataclass
class RateResult:
    mid_rate: Decimal
    buy_rate: Decimal
    sell_rate: Decimal
    fetched_at: datetime
    age_seconds: int
    stale: bool          # True if age 10–60 minutes
    blocked: bool        # True if age > 60 minutes
```

**Spread application** (SPEC §4):

```
buy_rate  = mid_rate × (1 + buy_spread)
sell_rate = mid_rate × (1 - sell_spread)
```

Look up spreads from `corridor_spreads`. If direct pair not found, compute
inverse from the stored inverse pair.

### `get_rates_age_seconds(db: Session) -> int | None`

Return age of the most recently fetched rate, or `None` if no rates exist.

### Staleness policy (SPEC §4)

| Age              | `stale` | `blocked` | Behaviour for callers        |
| ---------------- | ------- | --------- | ---------------------------- |
| < 10 min         | `False` | `False`   | Serve normally               |
| 10–60 min        | `True`  | `False`   | Serve with `stale: true`     |
| > 60 min         | `True`  | `True`    | Callers return `503 RATES_STALE` |
| No rates at all  | —       | `True`    | Callers return `503 RATES_STALE` |

---

## Background Task (`app/services/rate_scheduler.py`)

- Use FastAPI `lifespan` to start a background `asyncio` task.
- Fetch rates on startup, then every **5 minutes**.
- Wrap `refresh_rates()` in try/except — log failures, never crash the app.
- Cancel task on shutdown.

```python
async def rate_refresh_loop(interval_seconds: int = 300) -> None:
    while True:
        try:
            await asyncio.to_thread(refresh_rates_sync)
        except Exception:
            logger.exception("rate_refresh.failed")
        await asyncio.sleep(interval_seconds)
```

---

## API Router (`app/api/routers/rates.py`)

Prefix: `/api/v1/rates`, tag: `rates`.

| Method | Path                        | Status | Description                    |
| ------ | --------------------------- | ------ | ------------------------------ |
| `GET`  | `/api/v1/rates`             | `200`  | List all cached direct rates   |
| `POST` | `/api/v1/rates/refresh`     | `200`  | Trigger manual rate refresh    |
| `PUT`  | `/api/v1/rates/spreads/{base}/{quote}` | `200` | Update spread for a pair |

`GET /api/v1/rates` response includes `fetched_at`, `age_seconds`, `stale`
flag per rate or globally.

Register router in `app/main.py`.

---

## Schemas (`app/schemas/rate.py`)

| Schema              | Purpose                                           |
| ------------------- | ------------------------------------------------- |
| `RateResponse`      | `base_currency`, `quote_currency`, `mid_rate`, `buy_rate`, `sell_rate`, `fetched_at` (all rates as strings) |
| `RateListResponse`  | `rates: list[RateResponse]`, `fetched_at`, `age_seconds`, `stale` |
| `SpreadUpdateRequest` | `buy_spread`, `sell_spread` (strings)          |
| `SpreadResponse`    | `base_currency`, `quote_currency`, spreads        |

---

## Files to Create / Modify

| File                              | Action                                |
| --------------------------------- | ------------------------------------- |
| `app/models/exchange_rate.py`     | Create                                |
| `app/models/corridor_spread.py`   | Create                                |
| `app/schemas/rate.py`             | Create                                |
| `app/services/rate_providers.py`  | Create                                |
| `app/services/rate_service.py`    | Create                                |
| `app/services/rate_scheduler.py`  | Create                                |
| `app/api/routers/rates.py`        | Create                                |
| `app/core/config.py`              | Modify — add API key settings         |
| `app/core/exceptions.py`          | Modify — add `RateProviderError`, `RatesStaleError` |
| `app/main.py`                     | Modify — include rates router, lifespan task |
| `alembic/versions/`               | Modify — add rates migration + seed   |
| `.env.example`                    | Modify — add API key placeholders     |

---

## Tests to Add (`tests/test_rates.py`)

- `refresh_rates` upserts rates into DB (mock HTTP responses).
- Primary provider failure falls back to secondary.
- Total provider failure retains existing cache.
- Malformed API response retains existing cache.
- `get_rate` applies buy/sell spreads correctly (known fixture values).
- Staleness: rate < 10 min → `stale=False`, `blocked=False`.
- Staleness: rate 30 min old → `stale=True`, `blocked=False`.
- Staleness: rate 90 min old → `blocked=True`.
- `GET /api/v1/rates` returns cached rates.
- `POST /api/v1/rates/refresh` triggers refresh (mock provider).
- Background task does not crash app when provider fails (mock + lifespan test).

Use `httpx` mocking or `pytest-httpx` / `unittest.mock` for provider tests.

---

## Acceptance Criteria

- [ ] Rates are fetched on startup and every 5 minutes
- [ ] Provider failure does not crash the application
- [ ] Spreads are applied per SPEC formula
- [ ] Staleness policy matches SPEC §4 thresholds
- [ ] All existing tests still pass
- [ ] New rate tests pass
- [ ] `pytest tests/ -v --cov=app` passes with no regressions

---

## Out of Scope for This Step

- Quote generation (uses rates in `04`)
- Cross-pair routing logic (computed in `04`)
- `GET /healthz` rates status enrichment (deferred to `06`)
- `GET /metrics` (deferred to `06`)
- Hypothesis property tests for spread math (deferred to `04`)
