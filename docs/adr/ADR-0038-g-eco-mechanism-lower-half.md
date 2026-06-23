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

- `src/envs/ecological_4cond.py` defines a deterministic four-condition ecological environment with energy pressure, irreversible integrity loss, incompatible A/B needs under one-action budget, and de-complete observation (partial, lagged, noisy state estimate). It does not implement rate-grid scan order or a divergence-axis detector.
- `src/aac/g_eco.py` defines one shared substrate (`observation`, `predictor`, `lookahead`, `H`) used by VH, `VH_noStake`, and the nine-arm fixed-preference battery: `LIN`, `LEX`, `THR`, `QUOTA`, `MINIMAX`, `P0`, `RSTAR`, `O1`, `BT`. `lookahead_depth` is active.
- `src/aac/g_eco.py` also defines two calibration-only references, `HOMEOSTATIC_ORACLE` and `WCREF`, with `calibration_only=True`; they are not included in future r-final arm names. These references are truth-state privileged and are not runtime aliases of VH/MINIMAX.
- `experiments/g_eco.py` exposes `smoke` / `mechanism-check` plus pre-Gate-2 candidate writer/verifier surfaces. `freeze`, `r-final`, and `verdict` modes refuse to run while Gate-2 is locked.
- `tests/test_g_eco.py` guards shared-substrate identity, arm inventory, `VH_noStake` ablation surface, deterministic replay, no external rollback, pure environment region metrics, pre-Gate-2 candidate integrity/firewall checks, C6/C7 pause/tighten dominance, and Gate-2 refusal.

## Non-Goals

- No founder/CTO co-signed §6 freeze.
- No divergence-axis detector or pre-freeze rate-grid order change.
- No Gate-2-unlocking freeze verifier.
- No Gate-2 co-sign simulation.
- No r-final run.
- No verdict row.
- No claim that G-Eco supports autonomy, intelligence, or Route C.

## Consequences

- Codex can now iterate on the G-Eco mechanism surface under tests without touching founder-reserved freeze and verdict gates.
- The current engineering verdict remains ADR-0036/G13 NOT MET until a future frozen G-Eco r-final exists and is adjudicated under the parent protocol.
- The next permissible implementation step is §6 calibration/freeze machinery only after the still-held Gate-2 leaves are explicitly resolved in the parent governance records.

## Discipline Fixes & Remaining Boundary (2026-06-23)

An adversarial discipline review (workflow `w4tinneni`) confirmed no falsification gate was moved in executed code, but found that several deferred-gate inputs were stubbed/proxied in a direction that favored VH. The disclosure commit recorded them honestly; Codex then implemented the remediation spec `../docs/research/G-Eco-lowerhalf-discipline-fixes-2026-06-23.md` before any §6 calibration:

- **F1 fixed:** r-final eligibility is guarded through the real arm builder. Tests assert r-final names are disjoint from calibration-only refs and include a negative-control path that turns RED if `HOMEOSTATIC_ORACLE`/`WCREF` are admitted.
- **F2 fixed:** `HOMEOSTATIC_ORACLE` and `WCREF` are truth-state privileged calibration-only controllers. Runtime arms ignore `truth_state`; tests prove cheat refs differ from VH/MINIMAX and `WCREF` is not below runtime `MINIMAX` on calibration-seed enter-rate smoke coverage.
- **F3 fixed with documented adapters:** `P0`, `RSTAR`, `O1`, and `BT` expose source metadata and import their frozen ADR parameters (`GATE_FROZEN`, frozen RSTAR triple, `ResetScaffoldOrgan`, `BTEMP`). They are adapted to the G-Eco shared substrate without silent retuning.
- **F4 fixed:** observations are partial, lagged, and noisy; `truth_state` is separated for cheat refs and tests. The fourth condition is now de-completeness, not drifting regimes.
- **F5 fixed:** `lookahead_depth` performs real multi-step rollout, and VH carries a trajectory/irreversibility pressure term.
- **F6 fixed:** the C7-tighten test now forbids the action VH would otherwise select and asserts the selected action changes.

KEEP/CHECKPOINT status of `c1363fa` is unchanged; the remediation tightens pre-§6 discipline and still does not cross Gate-2, run r-final, or emit a verdict.

## Pre-Gate-2 Candidate Hardening (2026-06-24)

An adversarial freeze-candidate review found two remaining pre-freeze risks and one under-specified Gate-2 leaf:

- VH aggregation constants were still hand-coded without calibration provenance.
- §9 firewalls for region/rate/threshold logic relied on self-reported JSON booleans rather than static source guards; a follow-on review required those guards to follow same-module callees so forbidden reads cannot be moved one helper deeper.
- Gate-2 max-hardening condition C3 required G-Eco-4 bootstrap, battery-best tie-break, and comparison epsilon/rounding to be fixed into the hash-locked threshold object before activation.

Codex implemented the pre-Gate-2 hardening without unlocking Gate-2:

- `GEcoVHParams` and `select_vh_parameters()` select VH parameters from a finite calibration grid on calibration seeds, record grid hash/selected label/objective/provenance in `g_eco.battery.json`, and keep performance values withheld.
- `assert_g_eco_static_firewalls()` adds recursive AST source checks for the region predicate, rate witness, and threshold formula. `pregate2-verify` now runs these checks in addition to content-hash and leak checks. The rate witness now uses a calibration-ref-only runner rather than the generic arm runner, so recursive source checks can prove it does not reach VH or battery arms through a helper.
- `g_eco.thresholds.json` now records the C3 verdict-mechanics leaves: percentile bootstrap with `B=10000` and seed `611038`, deterministic battery-best tie-break order, and comparison `epsilon=1e-12` with no rounding.

This remains candidate-material hardening only. A passing `pregate2-verify` is not founder/CTO Gate-2 co-sign, not r-final authorization, not a halt/R4 disposition, and not a G-Eco verdict.

2026-06-24 verification after recursive-firewall hardening: `PYTHONPATH=src python -m unittest discover -s tests -v` ran 457 tests OK; `pregate2-candidates` followed by `pregate2-verify` returned `gate2_locked=true`, `verified_candidate_bundle=true`, and `static_firewalls_verified=true`.
