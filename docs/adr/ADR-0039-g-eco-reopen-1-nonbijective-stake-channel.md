# ADR-0039: G-ECO-REOPEN-1 Non-Bijective Stake Channel

Status: Accepted
Date: 2026-07-04
Owner: Founder / Autonomous Core CTO
Layer: Object layer / research supply

## Decision

Reopen G-ECO only as `G-ECO-REOPEN-1`, a fresh founder-authorized Track R route. The reopened mechanism is not a retune, reseed, metric swap, or rescue of the parked 2026-06 G-Eco line. It tests whether a non-bijective stake channel can create a falsifiable separation between active hidden-state disambiguation and fair cheap baselines under shared observation/action budgets.

This ADR authorizes specification, test-first implementation, preregistration review, freeze, and r-final execution for the `G-ECO-REOPEN-1` packet only.

## Prior Negative Mapping

The parked G-Eco result remains negative for its original claim class:

- VH is not autonomy evidence.
- Stake-ablation hitchhiking is not an acceptable success path.
- VH approximating MINIMAX is a prior failure mode, not a baseline to hide.

`G-ECO-REOPEN-1` must therefore distinguish the candidate from `MINIMAX_FAIR`, retain `NO_STAKE`, and make the cheap-baseline result decisive rather than decorative.

## Mechanism Claim

Claim class: task-performance / regret under hidden viability dynamics.

Allowed positive claim, if met:

```text
Under the frozen NBSC environment and seed allocation, the candidate policy reduces preregistered future-viability loss versus fair non-oracle baselines while preserving C6/C7 boundaries.
```

Forbidden claims:

- proof of autonomy;
- proof of intelligence;
- product capability claim;
- rescue or reinterpretation of prior G-Eco/VH results.

## Design Boundary

The environment must expose a non-bijective visible stake signal: different latent viability basins share the same immediate visible stake reading while requiring different future-preserving commitments. The candidate may use active probing or belief-update coupling inside the frozen environment. Baselines must receive the same observation/action interface and horizon budget.

No LLM, business semantics, product runtime import, external framework, runtime self-modification, or C6/C7 gate mutation is allowed.

## Fresh Seeds

Fresh seed ranges are reserved in:

```text
docs/research/G-ECO-REOPEN-1-seed-allocation-2026-07-04.json
```

The r-final allocation is `7500..7529`. These seeds must not be used for support, threshold shaping, calibration, debugging, or exploratory rescue.

## Required Artifacts

- RR-0029 architecture-theory review.
- Formal model spec.
- Algorithm spec.
- Implementation cast before mechanism-file creation.
- Preregistration file with numeric thresholds and exact mechanism-file list.
- Independent builder/reviewer identity split before freeze.
- Machine prereg review and freeze.
- r-final raw result, adjudication, lesson record, and route/product projection update.

## Acceptance Standard

This ADR is accepted as authority to attempt the frozen route. It is not authority to claim success. A failed, invalid, or machine-rejected run must be recorded as such.
