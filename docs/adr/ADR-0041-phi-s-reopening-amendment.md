# ADR-0041: φ_S Reopening Falsifier — Amendment 1 (fair cold-start B*, non-SQ-hard reopen-test, fresh seeds)

- Status: **PREREGISTERED (DRAFT, awaiting Kimi re-review + freeze)**. Amends ADR-0040 per the 2026-06-29 cross-model result adjudication.
- Date: 2026-06-29
- Deciders: founder authorized the run/review loop + this confirmation iteration (2026-06-29).
- Predecessor/parent: ADR-0040 (frozen, sha256 f82834da…); `docs/ADR-0040.result-adjudication-2026-06-29.md`.

## Why amend
ADR-0040's r-final produced a mechanical ALIGNED=H1b that the cross-model adjudicator (Kimi) ruled an **under-budgeting ARTIFACT** (`INVALID_INCONCLUSIVE_RESPEC_NEEDED`): B* was anchored to ORACLE-INITIALIZED BASE-FAIR (warm-started at the answer), which measures weight stabilization on a KNOWN feature — not the fair COLD-START cost of discovering the right monomial among ~40k candidates; and φ*=A1 (parity) is SQ-hard → VACUOUS, not a reopen. This amendment fixes the B* anchor and the φ* selection.

## Deltas from ADR-0040 (everything else unchanged and still frozen)
1. **B* re-spec (the fix):** B* = smallest acquisition budget at which **COLD-START BASE-FAIR** (fresh perceptron, NO oracle init) reaches ≥ 0.95·ORACLE return on calibration seeds, searched over a budget grid up to a cap **B_CAP = 100,000**. The acquisition sweep covers [small … B* … ≫B* = max(8·B*, 4·B*)] and includes B_CAP as the unbounded-fair proxy. If COLD-START BASE-FAIR does NOT reach the target within B_CAP, the φ* is declared **VACUOUS** (empirical SQ-hardness signal), NOT H1b.
2. **ALIGNED reopen-test φ* ∈ {A3, A4}** (non-SQ-hard: A3 = degree-2 polynomial threshold; A4 = 3-gate Boolean). Both have non-degenerate label correlations, so a fair cold-start baseline CAN learn them — making H0/H1a genuinely reachable. Run BOTH A3 and A4 as separate ALIGNED instances.
3. **Parity (A1/A2) is recorded as VACUOUS** (SQ-hard for the kernel-perceptron SQ learner class even with the exact monomial in the kernel; the determination is theoretical, confirmed empirically by non-convergence within B_CAP). Parity is NOT used as an ALIGNED reopen-test.
4. **FRESH seeds:** calibration **3000..3019**, r-final **3100..3129** (disjoint from ADR-0040's 2000.. / 2100..).
5. Per-condition rule, MISALIGNED negative control, INPUT-DENIED + ORACLE-FEATURE diagnostic, δ=0.10, ε=0.05, η=0.05, archive, learner, observability — all UNCHANGED from ADR-0040.

## Decision rule (per ALIGNED φ* ∈ {A3,A4}, frozen final seeds)
- **H0** if adv(ORGAN,BASE-FAIR) ≤ δ at B* (cold-start baseline ties).
- **H1a** if adv ≥ δ at small budget but ≤ δ at B* (sample-efficiency only; not a reopen).
- **H1b (REOPEN)** if adv ≥ δ at ≫B* AND BASE-FAIR φ*-recovery < 0.5+ε at ≫B* AND ORACLE-FEATURE ties (not INPUT-DENIED) AND MISALIGNED control passes AND cold-start BASE-FAIR reached target within B_CAP (else VACUOUS).
- Primary deliverable: the adv-vs-budget curve up to B_CAP for A3 and A4.

## Pre-registered expectation (honest, for calibration against outcome)
For learnable A3/A4 with a fair cold-start baseline and budget up to B_CAP, the expectation is **H0 or H1a** (foreclosure holds under fair acquisition; any ORGAN edge is sample-efficiency that closes by B*). A surprising H1b would be a genuine finding. Parity → VACUOUS.

## Firewall (CLAUDE rule 23)
amendment author: Claude. re-reviewer (cross-model): Kimi. freezer: deterministic hash-lock (independent content review by Kimi). builder: Codex. result adjudicator: Kimi. final verdict cast: founder. No retune after freeze without a new founder ADR + fresh seeds.
