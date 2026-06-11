# 06 — Observability

## Goal

Complete the observability layer: enrich `/healthz` with DB and rates status,
add `/metrics`, unify error responses with `trace_id`, and register global
exception handlers. After this step the system meets SPEC §10 and §11 in full.

---

## Prerequisites

- `00 — App Scaffolding` complete (basic `/healthz`)
- `00_1 — Middleware` complete (trace ID + request logging)
- `01 — Database` complete
- `03 — Rates` complete
- `04 — Quotes` complete
- `05 — Execute` complete

---

## Error Response Envelope

All API errors must follow SPEC §10 shape:

```json
{
  "error_code": "QUOTE_EXPIRED",
  "message": "The quote expired at 2024-01-15T12:01:00Z",
  "trace_id": "uuid"
}
```

### `app/schemas/error.py`

```python
class ErrorResponse(BaseModel):
    error_code: str
    message: str
    trace_id: str
```

### `app/core/exceptions.py` (extend)

Add a base `AppError` with `error_code`, `message`, `http_status` attributes.
Map every SPEC §10 error code to a concrete subclass.

### Exception Handlers (`app/core/exception_handlers.py`)

Register in `create_app()`:

```python
@app.exception_handler(AppError)
async def app_error_handler(request, exc): ...

@app.exception_handler(Exception)
async def unhandled_error_handler(request, exc): ...
```

- Read `trace_id` from `request.state.trace_id`.
- Return `ErrorResponse` JSON with appropriate HTTP status.
- Unhandled exceptions → `500 INTERNAL_ERROR`; log full traceback, never
  expose internals in `message`.

Remove any per-router `HTTPException` usage added in earlier steps — route
all domain errors through `AppError` subclasses.

---

## Enhanced Health Check (`GET /healthz`)

Replace the stub response from `00` with SPEC §11 format:

```json
{
  "status": "ok",
  "db": "ok",
  "rates_age_seconds": 142,
  "rates_status": "fresh"
}
```

### `app/services/health_service.py`

```python
def get_health(db: Session) -> HealthResult:
    db_status = check_db(db)           # "ok" or "error"
    rates_age = get_rates_age_seconds(db)
    rates_status = classify_rates(rates_age)  # "fresh" | "stale" | "unavailable"
    overall = "ok" if db_status == "ok" and rates_status != "unavailable" else "degraded"
```

| `rates_age_seconds` | `rates_status` |
| ------------------- | -------------- |
| `None`              | `unavailable`  |
| < 600 (10 min)      | `fresh`        |
| 600–3600            | `stale`        |
| > 3600              | `unavailable`  |

Return `200` even when `status` is `degraded` (service is up but impaired).
Return `503` only if the process cannot serve any request (e.g. DB entirely
unreachable and check raises).

Move `/healthz` handler to `app/api/health.py` or keep inline in
`main.py` — either is acceptable; prefer a dedicated router for consistency.

---

## Metrics Endpoint (`GET /metrics`)

### `app/services/metrics_service.py`

Query DB for:

| Metric                        | Source                                                     |
| ----------------------------- | ---------------------------------------------------------- |
| `quotes_generated_total`      | `COUNT(*)` on `quotes`                                     |
| `executions_successful_total` | `COUNT(*)` on `transactions`                               |
| `executions_failed_total`     | In-memory counter or `execution_failures` log              |
| `rates_last_updated`          | `MAX(fetched_at)` from `exchange_rates`                    |
| `active_quotes_count`         | `COUNT(*)` where `status=PENDING` and `expires_at > now()` |

### `app/schemas/metrics.py`

```python
class MetricsResponse(BaseModel):
    quotes_generated_total: int
    executions_successful_total: int
    executions_failed_total: int
    rates_last_updated: datetime | None
    active_quotes_count: int
```

### Router (`app/api/metrics.py`)

| Method | Path       | Status | Description    |
| ------ | ---------- | ------ | -------------- |
| `GET`  | `/metrics` | `200`  | System metrics |

---

## Structured Logging Completeness

Audit all services and ensure domain events log with required fields:

| Path / Service | Required log fields                             |
| -------------- | ----------------------------------------------- |
| Execute        | `trace_id`, `quote_id`, `customer_id`, `action` |
| Quote creation | `trace_id`, `quote_id`, `customer_id`, `event`  |
| Rate refresh   | `trace_id`, `event`, `duration_ms`              |
| Errors         | `trace_id`, `error_code`, `event`               |

Extend `JsonFormatter` / dev formatter if new extra keys are needed.

### README log example

Add a sample log output block to `fx-engine/README.md` showing a real
`execute.success` line in both dev and JSON formats.

---

## Files to Create / Modify

| File                              | Action                               |
| --------------------------------- | ------------------------------------ |
| `app/schemas/error.py`            | Create                               |
| `app/schemas/health.py`           | Create                               |
| `app/schemas/metrics.py`          | Create                               |
| `app/core/exceptions.py`          | Modify — `AppError` base + all codes |
| `app/core/exception_handlers.py`  | Create                               |
| `app/services/health_service.py`  | Create                               |
| `app/services/metrics_service.py` | Create                               |
| `app/api/health.py`               | Create — enhanced `/healthz`         |
| `app/api/metrics.py`              | Create — `/metrics`                  |
| `app/main.py`                     | Modify — register handlers + routers |
| `fx-engine/README.md`             | Modify — add example log output      |
| `tests/test_health.py`            | Modify — assert new health fields    |

---

## Tests to Add

### `tests/test_health.py` (update)

- `GET /healthz` returns `db`, `rates_age_seconds`, `rates_status`.
- When rates are fresh, `rates_status` is `fresh`.
- When DB is unreachable, `db` is `error` and `status` is `degraded`.

### `tests/test_metrics.py`

- `GET /metrics` returns all five metric fields.
- After creating a quote, `quotes_generated_total` increments.
- After executing, `executions_successful_total` increments.
- `active_quotes_count` excludes expired and executed quotes.

### `tests/test_errors.py`

- Domain errors return `{error_code, message, trace_id}` shape.
- `trace_id` in error body matches `X-Trace-ID` response header.
- Unhandled exception returns `500 INTERNAL_ERROR` without leaking details.
- Every SPEC §10 error code is reachable and returns correct HTTP status.

---

## Acceptance Criteria

- [ ] `/healthz` reports DB and rates freshness per SPEC §11
- [ ] `/metrics` returns all required counters
- [ ] Every error response includes `error_code`, `message`, `trace_id`
- [ ] `trace_id` in error body matches `X-Trace-ID` header
- [ ] Execute-path logs include all required fields
- [ ] README contains example log output
- [ ] All existing tests still pass
- [ ] New observability tests pass
- [ ] `pytest tests/ -v --cov=app` passes with no regressions

---

## Out of Scope for This Step

- Prometheus `/metrics` text format (JSON only per SPEC)
- Sentry / Datadog / external APM integrations
- Auth on `/metrics` or `/healthz`
- Rate limiting
- Request/response body logging
- Distributed tracing (OpenTelemetry)
