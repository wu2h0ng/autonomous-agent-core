# R-SRL-1 HCW Scorer Redirect Review

> Status: `APPROVE_READ_ONLY`
> Date: 2026-07-22
> Reviewer: opencode / deepseek-v4-pro
> Scope: read-only diff review
> Target head: `8ee1543` (`codex/rsrl-hcw-scorer-20260722`)
> Base: `origin/codex/canonical-convergence-20260715@6b56539`

## Verdict

`APPROVE_READ_ONLY`.

The previous `NO_APPROVE` findings were re-reviewed and found closed:

1. `compare_srl_to_baselines` now requires SRL to beat every baseline by the frozen margins, not only the best baseline.
2. A RED test covers the case where SRL has fewer verified outcomes than a baseline.
3. A RED test covers the case where SRL is missing a verified outcome count.

## Evidence checked

- `tests/research/r_srl_1/hcw_recorder.py`
- `tests/research/r_srl_1/test_hcw_recorder.py`
- diff from `origin/codex/canonical-convergence-20260715` to `8ee1543`

## Reviewer notes

No new P0/P1/P2 findings were reported. The reviewer confirmed:

- missing SRL/baseline annotations fail closed;
- missing verified outcome counts fail closed;
- zero comparable HCW denominators fail closed;
- `_safe_ratio` is shielded by the higher-level zero-denominator gate;
- `VERIFIED_HCW_REDUCTION` remains a scorer-level comparison verdict, not a product, autonomy or full experiment verdict.

## Boundary

This review approves the isolated scorer implementation for integration consideration only. It is not a result-bearing R-SRL-1 run, not a product release, and not Autonomy(S,E,O,V,T) evidence.
