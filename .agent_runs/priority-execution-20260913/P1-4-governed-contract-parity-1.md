# Task Packet — GOVERNED-CONTRACT-PARITY-1

> Status: `PARK / FROZEN_AGAINST_CLOSED_RESULT` (2026-09-15, founder decision)
> Track: product / translational
> primary_class: P  secondary_class: E
> Portfolio lane: PRODUCT_SELFDEV
> Authority refs: ADR-0058, ADR-0059 (present in worktrees only), `docs/CURRENT_STATE.yaml` SELFDEV-2/3/4/5/6 ledger

> **PARKED (founder, 2026-09-15).** This packet's F1-F4 are "findings to close", but
> the authoritative SELFDEV-8 verdict is FINAL/NEGATIVE and its negative map
> (`<workspace>/docs/research/negative-map-and-paradigm-learning-SELFDEV-8-E8-2026-08-14.md`)
> §6 **closes the SELFDEV series on this subset**; reopening requires new mechanism
> evidence + a fresh held-out design + a new founder route cast. §3 states the three
> residual hypotheses (model-side envelope skill / governed prompt construction /
> prompt adaptivity) are **not distinguishable** from the existing 21 envelope
> rejections, so G5 (gap explained/converged) cannot be met from current evidence.
> Implementing F1-F4 as fixes would rescue a frozen negative and is forbidden by
> AGENTS.md §11 / the constitution. No code was written. Reopen only via a new route
> cast + fresh prereg (a new experiment, not a rescue). The separable §4 process
> defects (typed machine-consumable `DenialReasonCode`; freeze-receipt recompute) are
> likewise gated behind a new prereg. See workspace negative map §6 and ledger
> `.agent_runs/priority-execution-20260913/messages.jsonl` (2026-09-15 recon blocker).

## 1. Goal Card

**Problem.** SELFDEV is the only real end-to-end product comparison on this project. SELFDEV-2/3 support the governed chain; SELFDEV-4/5/6 are NEGATIVE (chain 1/12 vs bare same-model baseline 4–6/12). Adjudication localizes the fault predominantly to the **governed provider prompt/response contract (~6.5x weather-free solve-rate gap)** plus an apply-gate class whose denial reasons are unlogged (3/12).

**Target U/P.** On a frozen held-out repository task set, under matched provider/model/tools/context/retries/evaluator/budget, the governed chain must not be materially worse than the bare model+tools baseline, with every denial explained by an enumerable reason.

**Non-goals.** No governance removal, no C7/permission weakening, no new autonomy claim, no new environment.

## 2. Context Pack

- `.agent_runs/selfdev-{2,3,4,5,6}/` attempt-level evidence
- `docs/research/negative-map-and-paradigm-learning-SELFDEV-8-E8-2026-08-14.md`
- ADR-0058 (chain diff mode), ADR-0059 (merged capability execution authority)
- governed provider prompt construction and ActionPipeline apply-gate

## 3. Findings to close (from adjudications)

| ID | Finding | Fix |
|---|---|---|
| F1 | apply-gate denial reasons unlogged | enumerable bounded reason code on every denial |
| F2 | governed diff-mode prompt shape differs from baseline | align governed output contract to the baseline's proven shape |
| F3 | chain loses solve rate on the tool-call JSON diff channel | transport/diff-mode parity test |
| F4 | whitelist aborts without enumerable alternatives | whitelist-abort driver with admissible alternatives |

## 4. First failing tests

```
test_denied_apply_always_records_enumerable_reason_code
test_governed_diff_mode_matches_baseline_output_contract
test_governed_chain_not_worse_than_bare_baseline_on_frozen_family
test_whitelist_abort_lists_admissible_alternatives
```

## 5. Gates

| Gate | Exit condition | Class |
|---|---|---|
| G1 denial reasons | every apply denial carries a bounded reason code | P/E |
| G2 prompt parity | governed diff-mode output shape = baseline shape | P/E |
| G3 harness parity | matched provider/model/tools/context/retries/evaluator/budget | E |
| G4 freeze | prereg frozen before any result run | R |
| G5 result | gap explained/converged; losses and constraints reported | R |
| G6 claim discipline | no reduced-supervision/superiority narrative before G5 | A |

**Kill metric:** weather-free solve-rate gap; bypass rate; unexplained denial count.

## 6. Authority boundary

- G4 and any result-bearing run are `FOUNDER_GATE`. This packet does not authorize a run.
- If the gap is intrinsic to governance, escalate to a "thin default path + strict escalation path" redesign discussion; do not weaken C7 as a shortcut.
- Negative results keep their exact verdicts; a new run is a new prereg, not a rescue of SELFDEV-4/5/6.
