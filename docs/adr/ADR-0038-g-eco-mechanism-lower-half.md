# ADR-0038: G-Eco Mechanism Lower Half

- Status: Accepted, lower-half implemented; no calibration/freeze/r-final result.
- Date: 2026-06-22
- Deciders: founder delegated Codex single-writer mechanism lane via parent `docs/research/G-Eco-codex-handoff.md`; Gate-2, R4/halt disposition, r-final verdict, and autonomy narrative remain founder-reserved.
- Predecessors: ADR-0035, ADR-0036, ADR-0037, parent `docs/research/G-Eco-preregistration-spec.md`, parent `docs/research/G-Eco-codex-handoff.md`.

## Context

Route C / G-Eco is queued as the next core ADR after ADR-0036/G13 returned NOT MET. Parent spec v4 freezes the target research shape: a viability-homeostatic subject policy (VH) must share the same observation/predictor/lookahead/H substrate as every fixed-preference battery arm, with value aggregation as the isolated variable.

The lower-half task is deliberately narrower than the full G-Eco route. It may implement the mechanism substrate, environment, arms, calibration-only references, metrics, C6/C7 guards, deterministic replay, and reset-boundary tests. It must not implement or run §6 rate-grid calibration, freeze `g_eco.rates.json`, `g_eco.battery.json`, or `g_eco.thresholds.json`, cross Gate-2, run r-final seeds, or emit a verdict.

## Options Considered

### Option A - Wait for all Gate-2 leaves, then implement everything in one pass

Argument for: fewer intermediate artifacts.

Argument against: keeps Codex idle on uncontroversial mechanism work and increases the risk of coupling implementation with later freeze/verdict decisions.

Disposition: rejected.

### Option B - Implement lower-half mechanism now, with hard refusals for freeze/r-final

Argument for: isolates pure mechanism code from founder-reserved freeze decisions; gives tests for shared substrate, arm inventory, reset boundary, C6/C7, and deterministic replay before any data-generating run; preserves the Route C firewall.

Argument against: creates code that is intentionally not yet a full experiment runner.

Disposition: accepted.

### Option C - Implement a full runner including calibration and r-final behind local flags

Argument for: faster path to a complete script.

Argument against: violates the current task STOP list and makes accidental Gate-2 crossing easier.

Disposition: rejected.

## Decision

Implement the G-Eco lower-half only:

- `src/envs/ecological_4cond.py` defines a deterministic four-condition ecological environment with energy pressure, irreversible integrity loss, incompatible A/B needs under one-action budget, and drifting regimes. It does not implement rate-grid scan order or a divergence-axis detector.
- `src/aac/g_eco.py` defines one shared substrate (`observation`, `predictor`, `lookahead`, `H`) used by VH, `VH_noStake`, and the nine-arm fixed-preference battery: `LIN`, `LEX`, `THR`, `QUOTA`, `MINIMAX`, `P0`, `RSTAR`, `O1`, `BT`.
- `src/aac/g_eco.py` also defines two calibration-only references, `HOMEOSTATIC_ORACLE` and `WCREF`, with `calibration_only=True`; they are not included in future r-final arm names.
- `experiments/g_eco.py` exposes only `smoke` / `mechanism-check`. `freeze`, `r-final`, and `verdict` modes refuse to run while Gate-2 is locked.
- `tests/test_g_eco.py` guards shared-substrate identity, arm inventory, `VH_noStake` ablation surface, deterministic replay, no external rollback, pure environment region metrics, C6/C7 pause/tighten dominance, and Gate-2 refusal.

## Non-Goals

- No §6 rate scan.
- No divergence-axis detector or pre-freeze rate-grid order change.
- No freeze JSON writer.
- No Gate-2 co-sign simulation.
- No r-final run.
- No verdict row.
- No claim that G-Eco supports autonomy, intelligence, or Route C.

## Consequences

- Codex can now iterate on the G-Eco mechanism surface under tests without touching founder-reserved freeze and verdict gates.
- The current engineering verdict remains ADR-0036/G13 NOT MET until a future frozen G-Eco r-final exists and is adjudicated under the parent protocol.
- The next permissible implementation step is §6 calibration/freeze machinery only after the still-held Gate-2 leaves are explicitly resolved in the parent governance records.
