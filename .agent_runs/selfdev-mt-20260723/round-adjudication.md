# SELFDEV-MT-20260723 — Round Adjudication

> Prereg: `docs/product/AGENT-OS-SELFDEV-1-prereg-multi-target-2026-07-23.md`
> (frozen, manifest `.agent_runs/selfdev-mt-20260723/manifest.json`)
> Adjudication date: 2026-07-23. Builder/operator: kimi-cli session.

## Verdict: NEGATIVE

Kill criterion 1 fired: T2 and T3 both exhausted their 3-attempt budgets without
VERIFIED. The round stops early per prereg §6; **T1 was not run** under this
prereg. T4's receipt is SELFDEV_HCW_LOWER but the round gate (all 4 VERIFIED +
all 4 SELFDEV_HCW_LOWER) is not met, and a kill criterion fired, so the round is
NEGATIVE — recorded without rescue.

## Receipts

| Target | Baseline | Selfdev outcome | Attempts used | Receipt verdict | Receipt digest |
|--------|----------|-----------------|---------------|-----------------|----------------|
| T1 (carry-over) | VERIFIED 1.5min/1 (frozen 34614e2d) | NOT RUN (round stopped early) | 0 | — | — |
| T2 (duplicate evidence refs) | VERIFIED 1.5min/1 | NOT_MET (final attempt) | 3 | INCOMPARABLE_OUTCOME_NOT_VERIFIED | `00891f6098b113aa07338ce755b56219dc9fce87b027a8a4753e7b6b10d9eda8` |
| T3 (CLI structured failure) | VERIFIED 2.0min/1 | NOT_MET (final attempt) | 3 | INCOMPARABLE_OUTCOME_NOT_VERIFIED | `0bc4942cbfd2b9f60bb6c0340cef408fc9ed8a29da770ad8722f2da24d3f41b4` |
| T4 (recovery one-run-stream) | VERIFIED 1.5min/1 | VERIFIED | 1 | SELFDEV_HCW_LOWER (delta -1.4, int 0) | `83eb41cb23fc907f5d2f418f4c4a5bab8a832db159ba20bbfb054200f82aa8f1` |

## Attempt log (all consumed attempts, none hidden)

| Attempt | Terminal class | Detail |
|---------|----------------|--------|
| T2 a1 | INVALID (provider infra) | provider TIMEOUT at 180s under 3-way parallel load |
| T2 a2 | NOT_MET | fixture passed, but provider renamed the existing T1 blocker `EVIDENCE_REF_OVERLAP` → `EVIDENCE_REFS_OVERLAP`, breaking 2 pre-existing tests |
| T2 a3 | NOT_MET | fixture passed, but provider added an unsupported `control` key to a workflow NodeSpec (pydantic extra_forbidden at self_development.py:679), breaking the sealed-run product test |
| T3 a1 | INVALID (provider infra) | provider TIMEOUT at 180s under 3-way parallel load |
| T3 a2 | NOT_MET | full-file replacement contained unified-diff fragments (`@@ -13,6 +13,7 @@` written literally); SyntaxError at collection, exit 2 |
| T3 a3 | NOT_MET | full-file replacement syntactically invalid (mismatched braces, line 53/19); collection error, exit 2 |
| T4 a1 | VERIFIED | chain clean; pytest 3/3 |

Selfdev-arm telemetry recorded per prereg §5: T2/T3 — 4 interventions
(2 approvals + 2 retry decisions), 0.3 HCW min; T4 — 1 intervention, 0.1 min.
HCW is operator-declared; machine latency excluded.

## Negative map (failure classes, with counts)

1. **Provider envelope/infra under parallel load (2/7)**: two of three
   concurrent 180s-window calls timed out; sequential reruns did not. The
   180s timeout is a frozen parameter; scheduling, not parameters, was the
   lever used. Recorded as INVALID attempts, not retried for free.
2. **Neighbor breakage on self_development.py (2/2 completed T2 attempts)**:
   the provider implemented the requested duplicate-ref rejection both times
   (fixture green) but broke adjacent existing behavior both times (renamed
   T1's blocker string; injected an unsupported NodeSpec key). The red/green
   fixture alone does not protect neighboring contracts — full-file scoped
   pytest caught it, fail-closed compensation restored bytes both times.
3. **Large-file full-replacement syntax failure (2/2 completed T3 attempts)**:
   on `apps/cli/__main__.py` (551+ lines) the provider twice emitted invalid
   Python (diff fragments; mismatched braces). The complete-file-replacement
   output contract is the bottleneck for large targets, not reasoning about
   the requested change.

## Paradigm learning (feeds next round design, no gate movement)

- The execution chain (seal → approve → resume → evaluate → compensate) held
  in 5/5 completed attempts; zero drift/expiry failures since 603ff53. The
  blocker class has moved up one level: from execution semantics to provider
  output fidelity on large files and neighbor preservation.
- Next-round design candidates (require a NEW prereg): smaller/denser target
  files; contracts that additionally pin neighbor-preservation in the
  provider-visible statement (e.g. "do not rename existing blocker strings;
  do not alter workflow node specs"); or a diff-format patch channel instead
  of complete-file replacement (an execution-contract change, ADR-level).
- T1 remains available for a future round with its frozen baseline; it was
  NOT consumed by this round (0 attempts).

## Claim boundary

This round provides no HCW-reduction support. It provides: one single-target
SELFDEV_HCW_LOWER receipt (T4, low-medium tier), a measured provider
envelope-compliance rate under this contract (1 VERIFIED of 5 completed
attempts across 3 targets), and a three-class negative map. Not product
superiority, not release, not Autonomy(S,E,O,V,T) evidence.
