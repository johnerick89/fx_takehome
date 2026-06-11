# DECISIONS.md

This document captures architectural and design trade-offs made during the build, distinguishing decisions I owned personally from those delegated to AI tooling.

---

## Decisions I Made Personally

### 1. Execute endpoint path: `POST /api/v1/quotes/{quote_id}/execute`

The AI initially proposed a flat `/api/v1/execute` endpoint with `quote_id` in the request body. I changed this to a nested resource path.

**Reasoning:** A quote is the resource; execution is an action on it. The nested path makes the relationship explicit and follows REST resource hierarchy conventions. It also means the quote context is captured in the URL, making logs and traces immediately readable without inspecting the body.

**Trade-off:** Slightly more complex routing, but the clarity gain is worth it.

---

### 2. Execute returns `HTTP 201 Created`, not `200 OK`

**Reasoning:** Executing a quote creates a new transaction record — a new resource. `201` is semantically correct for resource creation. The response includes a `Location: /api/v1/transactions/{transaction_id}` header pointing to the created resource, following standard HTTP semantics.

**Trade-off:** Idempotent retries return `200 OK` (no new resource created), so the execute handler must branch on whether the idempotency key was already seen. This adds a small amount of conditional logic but is the correct behaviour.

---

### 3. `Idempotency-Key` as an HTTP request header, not a body field

The AI initially placed `idempotency_key` as a field in the JSON request body. I moved it to an HTTP header.

**Reasoning:** The IETF has a formal draft standard (`draft-ietf-httpapi-idempotency-key-header`) specifying `Idempotency-Key` as a request header. This is the pattern followed by Stripe, Adyen, and other serious payment APIs. Headers are the correct place for request metadata that controls processing behaviour rather than describing the resource being acted on. It also means the idempotency key is available to middleware/logging layers without parsing the body.

**Trade-off:** Clients must set a header explicitly rather than including a field in a JSON payload they're already constructing. Minor inconvenience; correct semantics.

### 4. Technology stack choices

#### 1. FastAPI

Chosen over Flask for three reasons: native Pydantic integration means request/response validation is declarative with no boilerplate; automatic OpenAPI/Swagger docs at /docs make the API self-documenting and testable without a separate client; and async support is built-in for future extensibility. For a time-boxed exercise, the productivity gain over Flask is significant.

#### 2. Pydantic v2

The natural pairing with FastAPI. Enforces structured input/output at the boundary layer, catches type errors before they reach the service layer, and serialises Decimal amounts as strings cleanly via field_serializer — which is critical for monetary precision.

#### 3. SQLAlchemy 2.x

Chosen for explicit transaction control — the execute path requires fine-grained BEGIN IMMEDIATE transaction management that an ORM like Tortoise or a query builder like Databases abstracts away too aggressively. SQLAlchemy's session model gives full control over commit/rollback boundaries, which is non-negotiable for atomic two-leg execution.

#### 4. Alembic

The standard migration tool for SQLAlchemy. Chosen over manual schema management because the assignment requires demonstrating atomicity and concurrency — having a clean, versioned schema that can be torn down and rebuilt reliably is essential for the concurrency test suite.

#### 5. SQLite

Permitted by the assignment and sufficient for demonstrating all required invariants. WAL mode + BEGIN IMMEDIATE transactions satisfy the concurrency requirements without the operational overhead of running a Postgres instance. The trade-off is that SQLite's write serialisation means lower write throughput at scale — noted in README as a known limitation.

#### 6. pytest + Hypothesis

pytest for its fixture model, which makes test database isolation clean. Hypothesis for property-based testing over random currency amounts and pairs — the assignment explicitly requires this and Hypothesis is the Python standard for it.

### 5. Three-layer middleware: CORS + TraceID + RequestLogging

The AI initially suggested only CORS middleware. I extended this to three layers.

**Reasoning:**
CORSMiddleware — standard for any API with a frontend client.
TraceIDMiddleware — required by the spec; every response must carry X-Trace-ID and every log line must include the trace ID. Middleware is the correct place for this, not per-endpoint logic.
RequestLoggingMiddleware — the assignment explicitly asks for example log output in the README. A middleware that logs method, path, status code, duration, and trace ID on every request/response satisfies the observability requirement cleanly.

**What I explicitly ruled out:** GZipMiddleware, TrustedHostMiddleware, HTTPSRedirectMiddleware, session middleware, and rate limiting — all either out of scope per the spec or irrelevant without TLS or auth.

**Trade-off:** Two custom middleware classes add a small amount of boilerplate, but both are directly tied to spec commitments already made. Not adding them would mean manually threading trace IDs through every endpoint handler.

### 6. Customer model includes name and email fields

The AI-generated design had Customer with only the inherited id, created_at, and updated_at fields. I added name and email.
**Reasoning:** A customer identified only by a UUID is unusable in practice — there is no way to look up or identify a customer without an external identifier. email is unique and serves as a natural lookup key. name makes the list endpoint human-readable. Both are the minimum viable identifier set without crossing into KYC territory, which is explicitly out of scope.
**Trade-off:** Adds a unique constraint on email, which means the Alembic migration and create_customer service must handle duplicate email errors gracefully. Small cost for a significant usability gain.

### 7. GET /api/v1/customers list endpoint added

The AI-generated design omitted a list endpoint. I added GET /api/v1/customers with skip/limit pagination.
**Reasoning:** Without a list endpoint there is no way for a client to retrieve a customer ID — making the entire API difficult to use manually and forcing tests to store IDs from creation responses. The list endpoint is a standard REST resource and costs almost nothing to implement.

### 8. Flat app/api/ structure — no routers/ subfolder

I initially accepted the AI's suggestion of an app/api/routers/ subfolder but reversed the decision after reasoning through what else app/api/ would contain.
**Reasoning:** A routers/ subfolder only earns its place if app/api/ contains other things alongside it — shared dependencies, middleware, utilities. Since all of those live in app/core/ and app/db/, app/api/ would contain nothing but routers/, making it a folder inside a folder with no organisational value. Flat is cleaner:
app/api/
├── **init**.py ← aggregates and mounts all routers
├── customers.py
├── quotes.py
├── rates.py
├── transactions.py
**Trade-off:** If app/api/ grows to need shared API-layer dependencies in the future, a routers/ subfolder can be introduced then. No need to add the indirection upfront.

This decision is applied accross all other designs.

---

## Decisions Delegated to AI (and Verified)

### Rate freshness thresholds (10 min warn / 60 min block)

AI proposed these values. I reviewed and accepted them as reasonable defaults for an FX context where rates move frequently but not tick-by-tick. The policy is explicitly documented in `SPEC.md` so it can be adjusted without code changes.

### SQLite WAL mode + `BEGIN IMMEDIATE` for concurrency

AI proposed this approach for concurrency safety on SQLite. I verified this is the correct SQLite mechanism — WAL mode enables concurrent reads, and `BEGIN IMMEDIATE` acquires the write lock upfront, preventing the TOCTOU race on the execute path. Accepted.

### Cross-pair routing through USD first, EUR as fallback

AI proposed the routing rule. I accepted it as pragmatic — USD is the world's primary reserve and intermediary currency, so routing through it minimises spread compounding in most cases. EUR fallback covers EUR-zone pairs that may have a direct rate.

### `Numeric(precision=20, scale=8)` for monetary columns

AI proposed this. I verified: 20 digits of precision with 8 decimal places gives sufficient headroom for large NGN amounts (NGN/USD rates involve large nominal numbers) while preserving sub-cent precision for rate storage. Accepted.

---

## What I Did Not Trust Without Verifying

- **Concurrency model:** Did not accept the SQLite concurrency approach on faith — cross-checked against SQLite WAL documentation and confirmed `BEGIN IMMEDIATE` is the right transaction mode for the execute path.
- **Decimal rounding:** Verified that `ROUND_HALF_UP` with `decimal.Decimal` in Python produces the expected results for the KES→USD example in `SPEC.md` before committing to it in the spec.
- **201 vs 200 on idempotent retry:** AI initially suggested returning `201` on retries too. I overrode this — a retry must return `200` since no new resource is created on subsequent calls.

---

## Things the AI Got Wrong

### 1. UUID generation: Python-side default, not DB-side

The database design doc specifies String(36) primary keys but did not specify where the UUID is generated. I explicitly required Python-side generation using uuid.uuid4() as the column default.
Reasoning: SQLite has no native gen_random_uuid() equivalent unlike Postgres. If the default is left unspecified, SQLAlchemy ORM inserts will produce rows with NULL primary keys — the server default only fires on raw SQL inserts, not ORM-level inserts.

#### Fix applied:

```python
id: Mapped[str] = mapped_column(
    String(36), primary_key=True, default=lambda: str(uuid.uuid4())
)
```

### 2. TimestampMixin: Python-side defaults required alongside server_default

The database design specified server_default=func.now() on created_at and updated_at but omitted Python-side default values.
Reasoning: SQLite's server_default only fires on raw SQL inserts. SQLAlchemy ORM inserts bypass it entirely, meaning created_at and updated_at would be NULL on all ORM-created rows — which is every row in this codebase.

#### Fix applied:

```python
updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    default=func.now(),
    onupdate=func.now(),
)
```

## What I Would Do With Another Day

_To be updated after implementation is complete._
