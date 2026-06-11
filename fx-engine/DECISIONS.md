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

### 4. Three-layer middleware: CORS + TraceID + RequestLogging

The AI initially suggested only CORS middleware. I extended this to three layers.

**Reasoning:**
CORSMiddleware — standard for any API with a frontend client.
TraceIDMiddleware — required by the spec; every response must carry X-Trace-ID and every log line must include the trace ID. Middleware is the correct place for this, not per-endpoint logic.
RequestLoggingMiddleware — the assignment explicitly asks for example log output in the README. A middleware that logs method, path, status code, duration, and trace ID on every request/response satisfies the observability requirement cleanly.

**What I explicitly ruled out:** GZipMiddleware, TrustedHostMiddleware, HTTPSRedirectMiddleware, session middleware, and rate limiting — all either out of scope per the spec or irrelevant without TLS or auth.

**Trade-off:** Two custom middleware classes add a small amount of boilerplate, but both are directly tied to spec commitments already made. Not adding them would mean manually threading trace IDs through every endpoint handler.

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

_To be updated as implementation progresses._

---

## What I Would Do With Another Day

_To be updated after implementation is complete._
