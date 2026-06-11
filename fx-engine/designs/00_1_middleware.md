# 00_1 — Middleware

## Goal

Add three middleware layers to `app/main.py`. No business logic. After this
step the app should stamp every request with a trace ID, log every
request/response, and handle CORS.

---

## Middleware to Implement

### 1. `CORSMiddleware` (FastAPI built-in)

Allow all origins for now — tighten in production.

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

### 2. `TraceIDMiddleware` — `app/core/middleware.py`

**Behaviour:**

- On every incoming request, generate a `trace_id` (UUID4).
- Store it on `request.state.trace_id` so handlers and services can access it.
- Inject it into the response as `X-Trace-ID` header.
- If the client sends an `X-Trace-ID` request header, honour it instead of
  generating a new one (allows end-to-end tracing from a client).

**Signature:**

```python
class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next): ...
```

---

### 3. `RequestLoggingMiddleware` — `app/core/middleware.py`

**Behaviour:**

- Log one line on request received: `method`, `path`, `trace_id`.
- Log one line on response sent: `method`, `path`, `status_code`,
  `duration_ms`, `trace_id`.
- Use the logger from `app/core/logging.py` (to be created here).
- Do not log request/response bodies.

**Log format (dev — human readable):**

```
INFO  [trace_id=abc123] → GET /healthz
INFO  [trace_id=abc123] ← 200 GET /healthz 4ms
```

**Log format (production — JSON):**

```json
{"timestamp": "...", "level": "INFO", "trace_id": "abc123", "event": "request.received", "method": "GET", "path": "/healthz"}
{"timestamp": "...", "level": "INFO", "trace_id": "abc123", "event": "request.completed", "method": "GET", "path": "/healthz", "status_code": 200, "duration_ms": 4}
```

---

## Files to Create / Modify

| File                     | Action                                                             |
| ------------------------ | ------------------------------------------------------------------ |
| `app/core/middleware.py` | Create — `TraceIDMiddleware` and `RequestLoggingMiddleware`        |
| `app/core/logging.py`    | Create — logger factory, JSON vs human-readable based on `APP_ENV` |
| `app/main.py`            | Modify — register all three middleware                             |
| `.env.example`           | Modify — add `APP_ENV=development` if not already present          |

---

## Logger Setup (`app/core/logging.py`)

- Use Python's standard `logging` module.
- Export a `get_logger(name: str) -> logging.Logger` factory function.
- Format switches on `APP_ENV`:
  - `development` → `%(levelname)s  [trace_id=%(trace_id)s] %(message)s`
  - anything else → JSON with keys: `timestamp`, `level`, `trace_id`, `event`
- `trace_id` is injected via a `logging.Filter` that reads from a
  `contextvars.ContextVar` set by `TraceIDMiddleware`.

---

## Middleware Registration Order in `main.py`

```python
app.add_middleware(RequestLoggingMiddleware)  # outermost — times the full request
app.add_middleware(TraceIDMiddleware)         # sets trace_id before logging reads it
app.add_middleware(CORSMiddleware, ...)       # innermost
```

Order matters: middleware is applied bottom-up (last registered = first to run
in the request direction). `TraceIDMiddleware` must run before
`RequestLoggingMiddleware` so the trace ID is available when the log line is
written.

---

## Tests to Add (`tests/test_middleware.py`)

- `GET /healthz` response includes `X-Trace-ID` header.
- `X-Trace-ID` value is a valid UUID4.
- If client sends `X-Trace-ID` request header, the same value is echoed back
  in the response header.

---

## Acceptance Criteria

- [ ] Every response has an `X-Trace-ID` header
- [ ] Client-supplied `X-Trace-ID` is honoured
- [ ] Request and response log lines are emitted for every request
- [ ] Log format is human-readable when `APP_ENV=development`
- [ ] All existing tests still pass
- [ ] New middleware tests pass
- [ ] `pytest tests/ -v --cov=app` passes with no regressions

---

## Out of Scope for This Step

- Auth headers
- Rate limiting
- Request body logging
- Response body logging
- Sentry / external observability integrations
