# FX Take-Home — John Mboga

Submission for the [Umba Senior Backend Engineer take-home](ASSIGNMENT.md)
(Parts 1–3).

---

## Time spent

| Metric            | Estimate                                              |
| ----------------- | ----------------------------------------------------- |
| Wall-clock        | ~11 hours (5h day one + 6h day two, including breaks) |
| Active engagement | ~9-10 hours                                           |

Process: wrote `SPEC.md` and module designs first, then implemented incrementally
with Cursor (and other AI tools for Part 3 review). Small, meaningful git commits
per module.

---

## Repository map

| Part            | Deliverable                   | Location                                           |
| --------------- | ----------------------------- | -------------------------------------------------- |
| 1 — FX engine   | Source code                   | [`fx-engine/app/`](fx-engine/app/)                 |
| 1 — FX engine   | Setup, tests, limitations     | [`fx-engine/README.md`](fx-engine/README.md)       |
| 2 — Process     | Technical spec                | [`fx-engine/SPEC.md`](fx-engine/SPEC.md)           |
| 2 — Process     | Agent instructions            | [`fx-engine/AGENTS.md`](fx-engine/AGENTS.md)       |
| 2 — Process     | Trade-offs & AI collaboration | [`fx-engine/DECISIONS.md`](fx-engine/DECISIONS.md) |
| 3 — Code review | Planted-bug review            | [`REVIEW.md`](REVIEW.md)                           |
| 3 — Target code | AI-generated baseline         | [`planted_bugs/`](planted_bugs/)                   |

---

## Quick start

```bash
cd fx-engine
```

Access the fx-engine readme here: [`fx-engine/README.md`](fx-engine/README.md)

---

## Process notes

- **Spec-first:** `SPEC.md` and `designs/` were written before prompting the agent
  on each module.
- **Verification:** I did not trust concurrency, idempotency, or decimal paths
  without running tests — several AI suggestions were overridden (see
  `DECISIONS.md`).
- **Part 3 review:** Code read + `pytest` on `planted_bugs/` + ad-hoc scripts;
  analysis tools: Cursor, Claude.ai, Grok.com (detailed in `REVIEW.md`).

Ambiguities (customer fields, routing, rate fallback, etc.) are recorded in
[`fx-engine/SPEC.md`](fx-engine/SPEC.md) §14.

---

## Assignment brief

Original instructions: [`ASSIGNMENT.md`](ASSIGNMENT.md)
