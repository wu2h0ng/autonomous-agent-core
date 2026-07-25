# SELFDEV-3 Envelope-Upgrade Round — Adjudication (FINAL, independent-review amended)

> Prereg: `docs/product/AGENT-OS-SELFDEV-3-envelope-upgrade-prereg-2026-07-25.md`
> (frozen at 4bca981, manifest `.agent_runs/selfdev-3/manifest.json`)
> Round artifacts: `.agent_runs/selfdev-3/round/`. Date: 2026-07-25.
> Operator: kimi-cli. Independent adjudicator: kimi subagent (blind-anchored,
> no builder history) — ADJUDICATION_AMENDED: verdict upheld, counts corrected
> to per-attempt evidence. Envelope E2: 600s timeout both arms + ABAB
> interleaved scheduling; subset byte-identical to SELFDEV-2.

## Verdict: SUPPORTS

Observed difference on this frozen 12-task subset under envelope E2: chain
pass@2 **11/12** > baseline pass@2 **4/12**, strict inequality, no task-level
integrity failure (all 12 main workspaces verified clean at pinned heads
post-round, independently re-verified; solves determined ONLY by the
independent round-level verifier; 48/48 invoked-marker/attempt-record
consistency). **First window-unconfounded measurement of the round series.**

File-verified attempt accounting:

- **Baseline (24)**: 6 solved (4 tasks), 13 DIFF_INVALID, 4 explicit 600s
  timeouts (astropy ×2, matplotlib a2, sympy a2), 1 provider-malformed
  (sympy a1), 0 UNAVAILABLE.
- **Chain (24)**: 19 solved of 20 completed attempts, 2 timeouts-600s
  (sympy ×2), 2 malformed envelopes (requests a1, pylint-6903 a1),
  1 NOT_SOLVED (sklearn a2, f2p exit=4 — replicated from E1).

Caveats: (1) 2/12 solves f2p-only (`p2p_vacuous`, symmetric both arms);
(2) contamination upper bound (Verified likely inside K2's training
distribution); (3) output-contract asymmetry declared ex-ante against the
chain (complete-file vs unified diff) — the chain won under the harder
contract, strengthening the narrow claim within the envelope; (4) NOT
leaderboard comparability, HCW reduction, product superiority, release, or
Autonomy(S,E,O,V,T) evidence.

## Per-task receipts (file-verified)

| Task | Baseline a1 | Baseline a2 | Chain a1 | Chain a2 | Solved (B/C) |
|---|---|---|---|---|---|
| astropy__astropy-13453 (17.7KB) | INVALID (timeout 600s) | INVALID (timeout 600s) | SOLVED | SOLVED | – / ✓ |
| django__django-13670 | SOLVED | DIFF_INVALID | SOLVED | SOLVED | ✓ / ✓ |
| django__django-14089 | DIFF_INVALID | DIFF_INVALID | SOLVED | SOLVED | – / ✓ |
| matplotlib__matplotlib-22719 | DIFF_INVALID | INVALID (timeout 600s) | SOLVED | SOLVED | – / ✓ |
| psf__requests-1766 | DIFF_INVALID | DIFF_INVALID | INVALID (malformed envelope) | SOLVED | – / ✓ |
| pydata__xarray-4075 | SOLVED | SOLVED | SOLVED (f2p-only) | SOLVED (f2p-only) | ✓ / ✓ |
| pylint-dev__pylint-6903 | DIFF_INVALID | DIFF_INVALID | INVALID (malformed envelope) | SOLVED (f2p-only) | – / ✓ |
| pylint-dev__pylint-7080 | DIFF_INVALID | DIFF_INVALID | SOLVED | SOLVED | – / ✓ |
| scikit-learn__scikit-learn-14141 | SOLVED | SOLVED | SOLVED | NOT_SOLVED (f2p exit=4) | ✓ / ✓ |
| sphinx-doc__sphinx-10449 | DIFF_INVALID | DIFF_INVALID | SOLVED | SOLVED | – / ✓ |
| sphinx-doc__sphinx-10466 | SOLVED | DIFF_INVALID | SOLVED | SOLVED | ✓ / ✓ |
| sympy__sympy-13974 (13.6KB) | INVALID (provider malformed) | INVALID (timeout 600s) | INVALID (timeout 600s) | INVALID (timeout 600s) | – / – |

## Declared corrections (adjudicated)

1. **Driver abort misfire**: the 3-consecutive-infra abort fired on attempt
   RESULT classes (DIFF_INVALID ×2, INVALID_ENVELOPE ×1) that the baseline
   CLI surfaces as uncaught exceptions and the pre-fix classifier misread as
   infra. Kill-4's precondition (infra collapse) was never met — no
   environment failure occurred; the same attempts completed on resume.
   Ruling (independent adjudicator): lawful bookkeeping — no
   double-consumption (48 invoked markers == 48 result files, one per
   attempt), no result alteration (all relabeled attempts remain consumed
   INVALID failures; only mechanism labels changed), evidence preserved
   (8 files carry `reclassified` markers with original stderrs: 6
   DIFF_INVALID, 1 INVALID_ENVELOPE, 1 provider-malformed). Baseline CLI
   structured-output ergonomics gap recorded for the next package.
2. **Driver manifest deviation (disclosed, adjudicated outcome-neutral)**:
   the mid-round classifier extension changed driver3.py after the freeze
   commit. Kill-2 protects result-determining surfaces (prereg, selection,
   argv, fixtures — all byte-stable, selection cross-pin verified); the edit
   touched only failure labeling and could not alter solves (independent
   verifier) or consumption (marker ledger). Final record binds BOTH driver
   hashes: frozen-at-freeze `d7452452…` (in `.agent_runs/selfdev-3/manifest.json`)
   and frozen-at-completion `1e6077e9…` (classifier-extension-only diff),
   converting silent drift into an adjudicated, evidence-bound deviation.

## Negative map

1. **sympy-13974 chain timeouts (2/2 at 600s)**: content-specific latency
   beyond even the upgraded envelope — astropy at 17.7KB solved 2/2 while
   sympy at 13.6KB went 0/2, so file size alone is not the determinant; the
   residual envelope edge is task-content-specific generation length.
2. **Baseline diff-contract failures (13/24 DIFF_INVALID)**: truncated
   hunks and content-outside-hunk — under E2 the bare model's unified-diff
   reliability is the BASELINE's binding constraint (in E1 it was provider
   health).
3. **sklearn chain a2 (f2p exit=4) — REPLICATED across E1 and E2**: the
   second-sample patch breaks test collection on this task in both rounds;
   first samples solve in both. A stable per-task bimodal outcome.
4. **Chain malformed envelopes (2/24)** and **baseline provider-malformed
   response (1/24)**: prior failure classes persist at low rate under E2.

## E1-vs-E2 secondary analysis (descriptive only, NO gate)

- **Window confound quantified**: baseline E1 2/12 → E2 4/12 — the E1
  arm-window artifact cost the baseline ≈2 tasks (descriptive estimate).
- **Chain lead growth**: E1 9-vs-2 → E2 11-vs-4; chain attempt correctness
  15/16 (93.75%, E1) → 19/20 (95.0%, E2) in clean windows. The E1 caveat-1
  margin doubt is substantially answered — noting E2 changed two variables
  (timeout + scheduling), so the growth is not attributable to scheduling
  alone (astropy's flip is credited to 600s).
- **Failure-class migration**: baseline provider-infra 20/24 (E1) →
  diff-invalid 13/24 (E2); chain timeouts 7/24 (E1) → 2/24 (E2). Both
  migrations are envelope effects, as the E1 negative map predicted.

## Paradigm learning (feeds the NEXT round/envelope; no gate movement)

- The governed chain's correctness (~95% of completed attempts, both
  envelopes) is not the bottleneck anywhere in this series; residual
  constraints are content-specific generation length (sympy) and the
  output contract. The diff-channel ADR (chain emits diffs) would directly
  attack the remaining chain timeouts AND equalize the output contracts —
  it is now the highest-value harness change.
- ABAB eliminated the window confound structurally; keep it as the default
  scheduler for all future rounds.

## Claim boundary (verbatim from the amended adjudication)

SUPPORTS is restricted to: observed difference on this frozen 12-task
subset under envelope E2, with the four declared caveats. NOT: leaderboard
comparability, contamination-free measurement, HCW reduction, product
superiority, release, or Autonomy(S,E,O,V,T) evidence.
