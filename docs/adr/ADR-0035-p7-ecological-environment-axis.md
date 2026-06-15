# ADR-0035: P7 Transferable Ecological-Structure Environment Axis And G12 2x2 Gate

- Status: Accepted (P7 design / pre-registration; implementation ready after ADR-0034 completion)
- Date: 2026-06-15
- Deciders: founder approval; Codex as autonomous-agent-core single writer

## Context

P6 consolidated one decisive positive result:

```text
G10/P0 = subject-side confidence-gated policy, no organ
P0 beats A1 by 40.1% on fresh seeds while preserving C6/C7
```

Subsequent de-risks closed the natural second-axis hunt:

- C3/endogeny returned RED.
- Survival returned RED as an adaptation-speed shadow.
- Stationary risk returned RED.
- G11/C1 is parked until a new independent winning axis exists.

ADR-0034 then froze the next attribution test: before claiming what exactly drives G10,
run a relevance-aware full-Agent test of the amended B/R/K model. ADR-0034 had to run
before any P7 implementation or r-final.

ADR-0034 completed on 2026-06-15: PRED-A' and PRED-C' passed, PRED-B' failed. The
frozen strong control set now includes RSTAR with:

```text
base_temperature = 0.03
RelevanceField.inertia = 0.25
RelevanceField.surprise_gain = 1.0
```

However, the research debate has converged on a separate question: perhaps the next real
variable is not another organ, LLM, world model, VSA, option module, or coordination layer.
The object of study may need to shift to the **environmental ecology** in which autonomy is
tested.

This ADR opens that axis as P7 and freezes the G12 2x2 gate.

## Core Distinction: Two Meanings Of Reset

The gate depends on a distinction that must not be blurred:

| Reset type | Meaning | Allowed where | Why |
|---|---|---|---|
| **Internal state reset** | The subject resets its own beliefs/policy state, e.g. O1 decays `mu` and re-inflates `u` | Allowed in every cell | This is a mechanism/control baseline. Removing it would cripple O1 and confound the experiment. |
| **External world rollback** | The environment undoes action consequences: resource loss, damage, irreversible state change | Allowed only in reversible cells | This is an environmental affordance. Removing it is the point of the irreversible axis. |

So "remove reset" in P7 means:

```text
Do not remove O1/internal reset.
Remove only external-world rollback in irreversible cells.
```

If O1 loses in an irreversible cell while still retaining its internal reset mechanism,
the reading is clean: irreversible external consequence, not mechanism amputation, caused
the loss.

## Options Considered

### Option A: Stay at P6 and publish only

Pros:

- Avoids another environment-design cycle.
- Preserves the clean one-lever P6 result.

Cons:

- Leaves the original autonomy intuition under-tested: real autonomy may only be visible
  when the world has transferable environmental structure and irreversible consequence.
- Risks overfitting the whole program to reversible bandit-style toy worlds.

### Option B: Add a new organ or LLM/world-model mechanism

Pros:

- Technically straightforward; many candidate mechanisms exist.

Cons:

- Repeats the G1-G8 failure mode: clever mechanisms against cheap baselines.
- Violates the current lesson that the primary variable should be environment, not organ
  cleverness.
- Risks re-opening parked routes without a new axis.

### Option C: Open P7 as a transferable ecological-structure environment axis with a 2x2 gate

Pros:

- Moves the independent variable to the environment.
- Separates transferable environmental structure from irreversible consequence.
- Keeps O1/internal reset as a fair baseline while removing only external rollback.
- Pre-registers failure interpretations, including "all four cells fail".

Cons:

- Requires new environment code and instrumentation.
- Could still fail, in which case P7 must be downgraded and P6 boundaries preserved.

## Decision

Choose **Option C**.

P7 is accepted as a research axis. Implementation may proceed now that ADR-0034 has
finished and frozen the strong relevance-aware control set.

## Gate: G12 2x2 Transferable Ecological-Structure Environment Test

### D1. Axes

G12 uses a 2x2 design:

| Cell | Environmental structure | External reversibility | Short name |
|---|---|---|---|
| C00 | Thin | Reversible | thin/reversible |
| C01 | Thin | Irreversible | thin/irreversible |
| C10 | Transferable ecological structure | Reversible | ecological/reversible |
| C11 | Transferable ecological structure | Irreversible | ecological/irreversible |

Definitions:

- **Thin**: actions produce immediate reward/regret but do not expose transferable
  environmental structure beyond the current regime. This is closest to the current
  structured bandit family.
- **Transferable ecological structure**: the environment contains stable affordance topology,
  niche/route structure, or reusable state-action relations that can support generalization
  across shifts. This column tests whether autonomy benefits from structure in the world,
  not from a new representation organ.
- **Reversible**: external consequences may be rolled back or cleared by the environment
  at a pre-specified boundary.
- **Irreversible**: external consequences accumulate as external world state and cannot be
  undone by O1/internal reset.

Load-bearing orthogonality rule:

```text
Ecological structure is not resource scarcity, irreversible damage, or external rollback.
Scarcity, damage, and rollback belong to the external-reversibility axis and evaluator
metrics. The column factor must remain transferable environmental structure.
```

Tier-1 may hold incomplete observation and conflicting utility as background constants if
they are applied identically across all four cells. They must not become hidden extra axes
or post-hoc rescue knobs.

### D2. Mechanisms are frozen

G12 must not introduce a new organ or policy mechanism.

Candidate and controls are frozen as:

| Arm | Role |
|---|---|
| `A0` | baseline policy + no organ |
| `A1` | baseline policy + O1 internal reset |
| `P0` | frozen G10 confidence-gated policy + no organ |
| `BT` | fixed-low-temperature baseline from ADR-0030 |
| `RSTAR` | relevance-aware non-gated control from ADR-0034, if ADR-0034 completes and freezes it |

ADR-0034 did not downgrade G10 to "mostly relevance"; it froze RSTAR as a strong control
with the parameters above. Silent substitution is forbidden.

### D3. Internal reset and external rollback guards

Required invariants:

- O1/internal reset is available in every cell.
- O1/internal reset may change only subject belief state; it must not alter external
  resources, irreversible damage, affordances, or environment history.
- External rollback is enabled only in reversible cells.
- Irreversible cells must expose no API by which the agent or test harness can undo
  accumulated external damage during an episode.

### D4. Metrics

Primary per-seed metrics:

```text
post_shift_regret_area
irreversible_damage
damage_weighted_loss = post_shift_regret_area + irreversible_damage
recovery_steps
```

Secondary diagnostics:

```text
conflict_stability
resource_survival
```

Definitions:

- `irreversible_damage` is an **external-world** quantity: accumulated non-rollbackable
  damage, lost resource, or lost affordance.
- `recovery_steps` is an **internal adaptation** quantity: how quickly the subject returns
  to a low-regret policy after a shift while still being allowed to reset its own internal
  state.
- `conflict_stability` tracks whether the agent avoids oscillation or collapse under the
  shared background conflicting-utility condition, if enabled.
- `resource_survival` tracks resource continuity as a diagnostic, but it is not allowed to
  replace the primary damage-weighted gate unless a later ADR explicitly promotes it.
- The core P7 question is:

```text
With internal reset allowed, does irreversible external damage still accumulate differently
across agents?
```

### D5. Seeds and run shape

ADR-0034 uses seeds through `1500..1529`. G12 therefore uses fresh seeds:

```text
r-final seeds = 1700..1729
steps = 2000
window = 15
n_actions = 8
n_regimes = 5
```

Development/sanity seeds may be used only for deterministic tests and debugging. They must
not determine r-final thresholds or select environment parameters.

### D6. Cell win definition

For each cell, define:

```text
BEST_CHEAP = min(mean_loss(A0), mean_loss(A1), mean_loss(BT), mean_loss(RSTAR if available))
adv(P0, BEST_CHEAP) = 1 - mean_loss(P0) / BEST_CHEAP
```

P0 wins a cell iff all are true:

```text
adv(P0, BEST_CHEAP) >= 0.20
P0 loss < BEST_CHEAP loss in at least 24/30 seeds
Wilcoxon one-sided p < 0.01
bootstrap 95% CI lower bound for paired mean loss reduction > 0
```

For irreversible cells, also require:

```text
P0 irreversible_damage reduction vs BEST_CHEAP >= 0.20
bootstrap 95% CI lower bound for paired damage reduction > 0
```

### D7. Four-cell interpretation table

The following interpretations are pre-registered:

| Pattern | Interpretation | Disposition |
|---|---|---|
| P0 wins only C11, or C11 advantage is at least 0.10 above every other cell | **P7 ecological-irreversible axis supported** | New environment axis is real enough to study; still no G11/C1 revival without a separate ADR |
| P0 wins C01 and C11 but not reversible cells | Irreversibility, not transferable structure, is the active variable | P7 is narrowed to irreversibility; ecological-structure claim downgraded |
| P0 wins C10 and C11 but not thin cells | Transferable structure, not irreversibility, is the active variable | P7 remains environment-axis work, but irreversibility is not necessary |
| P0 wins all four cells | P0 generalizes broadly; 2x2 does not isolate a new axis | Do not call this P7 ecological-structure-axis proof; revise theory |
| P0 wins no cells | P7 environment axis downgraded | Preserve P6 boundaries; do not keep shopping environments |
| Mixed/unstable pattern below thresholds | Inconclusive | Record as such; no retuning to rescue |

The "all four cells fail" row is load-bearing. Without it, P7 would become environment
shopping.

### D8. Guardrails

G12 must not:

- reopen G11/C1,
- retune P0, O1, BT, RSTAR, or any organ,
- introduce LLMs or self-recursive runtime systems,
- weaken C6/C7,
- replace internal reset with external rollback,
- silently select favorable environment parameters after seeing r-final data.

## Consequences

- P7 is now an accepted research axis and the next core implementation queue.
- ADR-0034 resolved the B/R/K attribution enough for G12: P0 keeps a decisive K residue,
  and RSTAR joins the cheap-control set.
- Future RR-0022 can use this ADR as the core gate reference, but RR-0022 is not a core
  implementation authority.
