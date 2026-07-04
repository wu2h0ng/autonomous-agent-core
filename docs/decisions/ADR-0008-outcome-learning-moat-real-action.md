# ADR-0008: Outcome→learning moat, closed to a real governed action (S4)

- Status: Proposed on feature branch `codex/s4-outcome-learning-moat-20260705`.
  Not merged, not pushed, not released.
- Cross-repo authorization: workspace RR-0048 phase-gate Option 2, slice **S4** (founder-authorized
  2026-07-05). Final slice, sequenced after **S1–S3** (ADR-0005/0006/0007).
- No import of `autonomous-agent-core` (Hard Boundary #19).

## Context

The product moat is not "trusted Q&A" — it is **governed action → measured outcome → compounding
per-customer knowledge** (the value-capture channel). The compounding *mechanism* already lives in OS Core
and is unit-tested: recall quality-boost by `outcome_correction_count`/`adoption_correction_count`
(`test_knowledge_recall.py`, `test_http_app.py`), and realized-value knowledge promotion
(`promote_from_adoption`). What S1–S3 added was a **real, disposer-governed, executed** action. S4 closes
the loop by tying the compounding to that real action and pinning the guarantee that keeps the moat honest.

The anti-wirehead architecture is load-bearing here (P5.1a/P5.1b, ADR-0001):

- `record_outcome(...)` is a runtime **self-report** — recorded for audit/trace only; it **cannot** promote
  knowledge or mint realized value.
- Realized external value flows through a separate **operator-exclusive** writer, `AdoptionIngest`. The
  runtime is handed only a read-only `AdoptionLedgerView`; it holds no writer.
- `promote_from_adoption(trace_id)` supersedes a knowledge candidate **only** from operator-attested
  realized value.

## Decision

Add `tests/integration/test_s4_outcome_learning_moat.py`, which wires the S2 local disposer + the
`action_record` connector + an `AdoptionIngest`, and proves end-to-end:

1. **Compounding from a real action.** A real disposer-governed R0-R3 action executes (ALLOW → approval →
   ADR-0005 recheck → `connector.execute` → real ledger write) and sediments a DRAFT KnowledgeAsset
   candidate (v1). When the **operator** attests realized external value (`AdoptionIngest.submit`),
   `promote_from_adoption` supersedes it with a bumped version (v2). Real action → realized value →
   compounded knowledge.
2. **Anti-wirehead.** With the adoption channel wired but the operator NOT attesting, a runtime
   `record_outcome("adopted")` self-report is captured for audit but does **not** promote knowledge
   (`promote_from_adoption` → None; version stays v1). The runtime cannot grow its own moat by declaring
   success.
3. **Defense in depth.** With no value channel wired at all, promotion is structurally impossible.

## Scope / non-goals

- **No new mechanism.** S4 is integration + guarantee, not new runtime logic; it consumes the existing
  knowledge/adoption/feedback machinery through real entry points (`run`, `execute_approved_operation`,
  `record_outcome`, `promote_from_adoption`).
- **No contract change.** R4/R5 stay proposal-only; the seam still only tightens.
- **Honest capability bound.** This compounds **knowledge/recall value** from realized outcomes (value
  capture). It is NOT a claim that the disposer's causal model self-improves from outcomes — that
  (learning the world model online) is a separate axis that the object-layer research has repeatedly found
  does not hold today (RR-0040/0042 passive-discovery closure), and it is not claimed here.

## Consequences

- Positive: the full moat is demonstrated closed to a real governed action, with the anti-self-deception
  guardrail (self-report cannot mint value/knowledge) verified at the integration level. This is the
  value-capture story the product rests on, proven rather than asserted.
- Cost: none beyond the test; the mechanism was already present.

## Tests

- `tests/integration/test_s4_outcome_learning_moat.py` — realized value from a real governed action
  compounds knowledge (v1→v2); self-report cannot promote (anti-wirehead); no-channel makes promotion
  impossible.
