# Code Review: `planted_bugs/` FX Engine

Review of the AI-generated FX engine as a teammate PR per ASSIGNMENT.md Part 3.

**Method**: Full code read (`app.py`, `fx.py`, `db.py`, `rates.py`, tests) + `pytest` (all pass) + ad-hoc concurrency/idempotency/cross-pair/precision scripts. Used Cursor, Claude.ai and Grok.com for analysis.

**Verdict**: **Do not merge**. Existing tests pass but miss required behaviours (balances, concurrency, cross rates, quote contract). The implementation fails several Part 1 required items and gives false confidence.

## Summary (severity order)

| #   | Severity | Issue                                                            |
| --- | -------- | ---------------------------------------------------------------- |
| 1   | Blocker  | No customer balances or atomic two-leg execution                 |
| 2   | Blocker  | Same quote executable multiple times under concurrency           |
| 3   | Blocker  | Cross-pair rate math uses wrong leg orientation                  |
| 4   | Blocker  | Execute reprices live instead of honouring quoted rate           |
| 5   | Major    | Idempotency not scoped to quote + optional header + 500 on races |
| 6   | Major    | Float used in quote final amount calculation                     |
| 7   | Major    | Inverse rates use mid-point (loses spread)                       |
| 8   | Major    | Process-local lock ineffective for production                    |
| 9   | Major    | Missing customer APIs, observability, and rate failure handling  |

## Detailed Issues

### 1. Blocker — No balance ledger (core missing)

**Problem**: `execute_quote` only marks quote as executed and inserts transaction. No customers or balances tables.  
**Impact**: Records trades without moving money or checking funds (Part 1 core op #2 & #4).  
**Proof**: Execute succeeds but there are no customers/balances schema; execute never touches funds.  
**Fix**: Add balance tables. Single DB transaction: check → debit → credit → mark executed.

### 2. Blocker — Concurrency safety broken

**Problem**: Read-check outside lock + per-request connections. All threads see `executed=0`.  
**Impact**: Same quote executes N times under load/retries (Part 1 required concurrency test).  
**Proof**: 5 parallel `execute_quote()` → 5 transactions for one quote.  
**Fix**: `BEGIN IMMEDIATE` + re-check inside transaction. Drop `threading.Lock`.

### 3. Blocker — Cross-pair rate calculation wrong

**Problem**: Always `leg1["sell"] * leg2["sell"]` regardless of pair orientation. No EUR routing.  
**Impact**: Wildly incorrect amounts on KES→NGN etc. (Part 1 currency pairs + spread compounding).  
**Proof**: KES→NGN (100) → ~19M NGN instead of ~1,154.  
**Fix**: Normalise leg direction + correct buy/sell side per trade.

### 4. Blocker — Execute ignores quoted rate

**Problem**: Recomputes rate/final amount instead of using stored quote values.  
**Impact**: Breaks quote contract — customer gets repriced (Part 1 core ops #1 + #2).  
**Proof**: Quote final 13,014.75 KES → executed 14,316 after rate bump.  
**Fix**: Use stored `rate` and `final_amount` at execution.

### 5. Major — Idempotency flaws

**Problem**: Key not scoped to `quote_id`; header optional; check-then-insert → IntegrityError 500 on concurrent retries.  
**Impact**: Wrong responses + unsafe retries (Part 1 required idempotency).  
**Fix**: Composite key + upsert/select-on-conflict inside main transaction. Make header mandatory.

### 6. Major — Float contamination

**Problem**: `float(amount) * float(rate)` in `generate_quote`.  
**Impact**: Precision loss on large amounts (Part 1 required Decimal precision).  
**Proof**: `999999999999999.99 * 1.005` loses cents via float.  
**Fix**: Pure Decimal: `(amount * rate).quantize(...)`.

### 7. Major — Inverse rates use mid-point

**Problem**: Averages buy/sell then inverts.  
**Impact**: Customer gets better-than-market rate on inverses (Part 1 spreads + inverses).  
**Fix**: Invert correct spread side.

### 8. Major — In-process lock useless

**Problem**: `threading.Lock` only works within one process.  
**Impact**: Fails under normal multi-worker deployment (Part 1 required concurrency safety).  
**Fix**: Rely on DB serialisation.

### 9. Major — Missing required surface area

- No customer create/balance view/credit APIs (Part 1 core op #4).
- No `/healthz`, metrics, or correlation ID on success responses (Part 1 observability).
- Rates fully stubbed — no real source, staleness, or failure handling (Part 1 rate ops + required failure behaviour).

**Impact**: Incomplete product and poor operability so ops can’t trace quote→execute without correlation headers; stale/down rates can’t be detected or rejected

**Fix**: Add customer + balance tables and three balance APIs; attach customer_id to quotes. Add /healthz, /metrics, and trace headers on all responses. Integrate a real rate provider with cached fallback, staleness checks, and tested down/stale behaviour.

## What I did **not** flag

- Missing property-based tests (assignment gap).
- Style nits (inner imports, status codes).
- Flask choice (allowed).
- Raw SQL + init_db() instead of Alembic — acceptable for exercise scope; noted as ops gap, not a runtime defect.

## Recommended Merge Gate

Fix all Blockers + Idempotency/Decimal/Concurrency issues. Add the required tests (parallel execute, idempotent retry, cross-pair checks, insufficient funds rollback). Then re-review.
