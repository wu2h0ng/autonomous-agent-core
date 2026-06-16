# ADR-0036: Bounded Consequence Prior And G13 Scar-Specific Gate

- Status: Completed, NOT MET
- Date: 2026-06-15
- Deciders: founder approval; Codex as autonomous-agent-core single writer

## Context

G12 did not prove the P7 axis; this ADR is not a rescue of G12, but tests a
single-variable B-channel candidate for usefulness only in the scarred regime.

The current ledger is:

```text
G10/P0  = MET and trap-complete; subject-side confidence gate is the robust lever.
ADR-0034 = PARTIAL; RSTAR explains part of the old margin, but a decisive K residue remains.
G12/ADR-0035 = INCONCLUSIVE; P0 nearly wins all four cells, so no distinct
               ecological-irreversible environment axis was isolated.
```

RR-0023 therefore narrows the next admissible question. Do not look for a new broad
autonomy signature, do not retune G12, and do not re-open G11/C1. Test exactly one
candidate mechanism:

```text
Can a bounded consequence prior help P0 only when external consequences can scar the
world, while staying near-null in reversible conditions?
```

The target is not "better organ" in general. The target is a scar-specific B-channel:
a belief-only prior about action consequences under irreversible external damage.

## Non-Goals

- Do not rescue, patch, re-score, or re-run G12.
- Do not weaken G10/P0 or change the frozen confidence-gate parameters.
- Do not import LLMs, tool-use planners, business semantics, or third-party runtime
  dependencies.
- Do not let the organ write actions, policy, shell state, audit state, gate thresholds,
  or environment truth labels.
- Do not model other agents in v1. This is a single-agent consequence prior.
- Do not claim a new system-level autonomy signature from G13 alone.

## Decision

Open ADR-0036/G13 as a narrow pre-registered core gate.

The candidate arm is:

```text
CP = P0 confidence-gated policy + bounded consequence prior
```

The primary baseline is:

```text
P0 = frozen confidence-gated policy, no consequence prior
```

Cheap controls remain in the report for orientation:

```text
A0, A1, BT, RSTAR, and a simple frozen CAUTIOUS control when the scar screen exposes
a meaningful cheap avoidance rule.
```

The scientific null is stronger than "cheap baselines win":

```text
P0-alone is already enough; adding a bounded consequence prior does not create a
scar-specific improvement and may repeat the old gate+organ harm pattern.
```

## Interface Freeze

The bounded consequence prior is an organ only in the C6 sense: it may advise belief,
not act.

Allowed output:

```text
action_id
predicted_scar_delta
predicted_resource_delta
predicted_conflict_delta
uncertainty
```

Meaning:

- `action_id` identifies the action whose consequence is being predicted. It is not an
  action command.
- The deltas are belief-like estimates that may be merged into the subject's existing
  belief/accounting layer.
- `uncertainty` may temper the merge. It must not directly set policy temperature,
  gate threshold, forbidden actions, pause state, or operator decisions.

Forbidden:

- returning a selected action
- mutating `PolicySelector`
- mutating `CorrigibilityShell` or `ShellView`
- writing to `AuditLog`
- changing G10/G13 gate parameters
- reading hidden evaluator-only damage labels during action selection

The subject may ignore every advice record. If ignoring the prior is not behaviorally
possible, C6 fails.

## Scar Validity Screen

Before G13 r-final may run, the environment/harness must pass a validity screen. This
screen is not the gate result; it is an apparatus check.

The scarred condition must satisfy all of the following:

1. Scar is externally irreversible within an episode: the environment must not roll back
   damage, resource loss, or route degradation after a bad action.
2. Scar is foresight-avoidable: an action-consequence prediction can plausibly reduce it
   before the damage occurs.
3. Scar is not label-leaked: policy/coordinator code cannot observe the hidden optimal
   action, hidden hazard bit, or evaluator damage oracle.
4. Scar is not cheap-trivially avoided: a simple frozen CAUTIOUS rule must not capture
   the full CP gain on development seeds. This is an apparatus check, not the r-final
   result. The r-final `cheap_caution_capture` metric in the interpretation table is a
   separate confirmatory guard.
5. Internal reset remains allowed: O1-style belief/policy reset is a mechanism baseline
   and must not be disabled merely because the cell is irreversible.

If this screen fails, the result is `INVALID`, not `NOT MET`.

## G13 Frozen Design

### Cells

G13 reuses the G12 reversible/irreversible distinction as a test family without changing
the G12 verdict:

| Cell | Meaning | Expected CP behavior |
|---|---|---|
| R0 | reversible / no persistent scar | near-null or small sharpener only |
| R1 | irreversible / persistent scar | possible decisive improvement |

If implementation keeps the G12 thin/ecological split, report all four cells:

```text
C00 thin/reversible
C01 thin/irreversible
C10 ecological/reversible
C11 ecological/irreversible
```

But G13's load-bearing contrast is reversible vs irreversible, not a renewed attempt to
prove the G12 ecological axis.

### Aggregation And Analysis Freeze

If the implementation keeps the four G12-style cells, all G13 gates are computed on the
pre-registered reversibility collapse:

```text
R0(seed) = mean over reversible cells present for that seed
R1(seed) = mean over irreversible cells present for that seed
```

So:

- reversible metrics use the per-seed `R0` collapsed value;
- irreversible metrics use the per-seed `R1` collapsed value;
- paired wins and the `24/30` threshold are computed over 30 collapsed per-seed `R1`
  comparisons, not over 60 cell-seed comparisons;
- the four-cell C00/C01/C10/C11 table is descriptive only unless a later ADR explicitly
  freezes a four-cell gate.

No post-hoc choice between per-cell, pooled-cell, or collapsed-cell aggregation is
allowed after r-final data are visible.

### Seeds

Use fresh seeds that have not been used by G9, G10, ADR-0031, ADR-0034, or G12:

```text
development/calibration: 1750..1769
r-final:                 1800..1829
```

R-final may run once. Do not retune after seeing r-final.

### Frozen P0 Parameters

```text
gate_kappa = 0.5
gate_temp_floor = 0.1
```

RSTAR, when used as a control, stays frozen from ADR-0034:

```text
base_temperature = 0.03
RelevanceField.inertia = 0.25
RelevanceField.surprise_gain = 1.0
```

### Metrics

Report at minimum:

- `damage_weighted_loss`
- `post_shift_regret_area`
- `irreversible_damage`
- `recovery_steps`
- `stale_prior_harm`
- `reversible_spillover`
- `cheap_caution_capture`

Definitions:

- `adv(CP,P0) = (loss(P0) - loss(CP)) / loss(P0)`.
- `damage_adv(CP,P0) = (damage(P0) - damage(CP)) / damage(P0)`.
- `stale_prior_harm = max(0, loss(CP) - loss(P0))`, reported per cell and averaged
  over the first post-shift window.
- `reversible_spillover = max(0, adv(CP,P0))` in reversible cells.
- `cheap_caution_capture` is the fraction of CP's irreversible damage reduction that is
  already achieved by the frozen CAUTIOUS control, when that control exists.

Degenerate denominator rule:

```text
epsilon = 1e-9
if loss(P0) <= epsilon:   adv(CP,P0) = 0.0
if damage(P0) <= epsilon: damage_adv(CP,P0) = 0.0
```

The paired absolute reductions are still reported for diagnostics, but normalized
advantage thresholds cannot be passed from a near-zero denominator. Report the count of
near-zero denominators per cell/collapse so the result cannot hide this case.

## G13 Gate

G13 is `MET` only if all four criteria pass.

### G13-1: Irreversible Benefit

In irreversible/scarred cells, CP must beat P0:

```text
mean adv(CP,P0) >= +0.10
paired wins >= 24/30 seeds
Wilcoxon p < 0.01
bootstrap 95% CI lower bound for mean loss reduction > 0
mean damage_adv(CP,P0) >= +0.10
```

### G13-2: Scar Specificity

The irreversible advantage must be meaningfully larger than the reversible advantage:

This is the sole deliberate exception to the R0/R1 aggregation collapse. To keep the
specificity bar conservative, `max_reversible_adv` is the larger per-cell reversible
advantage over C00 and C10 when both cells exist; if only one reversible cell exists, it
is that cell's advantage. All other G13 metrics use the pre-registered R0/R1 collapse.

```text
mean_irreversible_adv - max_reversible_adv >= +0.10
bootstrap 95% CI lower bound for the contrast > 0
```

If CP helps equally in reversible cells, the result is not scar-specific and G13 is
`NOT MET`.

### G13-3: No Stale-Prior Harm

CP must not degrade frozen P0 in reversible cells or early post-shift windows:

```text
mean reversible adv(CP,P0) >= -0.05
mean stale_prior_harm <= 0.05 * mean loss(P0)
no more than 3/30 seeds show >10% CP harm in a reversible cell
```

This criterion exists because prior organs have repeatedly harmed the gate when their
belief updates were stale.

### G13-4: C6/C7 Invariants

Deterministic tests must prove:

- CP cannot return or execute an action.
- CP cannot mutate policy, shell, audit, forbidden actions, pause state, or gate
  thresholds.
- Paused shell means zero CP-driven action execution.
- Fully forbidden action sets still dominate CP advice.
- The audit chain records the CP advice merge path without letting the organ write audit
  entries directly.

Failure of any invariant is an immediate `NOT MET`, regardless of empirical score.

## Interpretation Table

| Result pattern | Interpretation |
|---|---|
| G13 all criteria pass | Bounded consequence prior is provisionally supported as a scar-specific B-channel sharpener over P0. This still does not revive G11/C1 by itself. |
| Irreversible benefit fails | Strong negative: P0-alone remains enough; K/R residue dominates the scar setting. |
| Reversible cells improve similarly | Not scar-specific. The prior is a generic shaping aid, not the hypothesized consequence-scar channel. |
| CP harms P0 or violates stale-prior guard | Repetition of the G9 gate+organ harm pattern; organ line remains suspect. |
| CAUTIOUS captures the damage reduction | Cheap avoidance explains the result; consequence prior is not necessary. |
| Scar validity screen fails | Apparatus invalid; repair the screen before any r-final, without interpreting it as a scientific win/loss. |

## Implementation Plan

Serial only:

```text
T-P7.1a  Scar validity screen and reversible/irreversible harness guards.
T-P7.1b  Consequence-prior interface, belief-only merge path, and C6/C7 tests.
T-P7.1c  Frozen controls: P0, RSTAR, and CAUTIOUS where applicable.
T-P7.1d  G13 experiment harness with development seeds only.
T-P7.1e  R-final on seeds 1800..1829 and ADR-0036 result update.
```

Do not write mechanism code outside this scope. Do not run r-final until the validity
screen, C6/C7 tests, and frozen parameters are committed.

## Implementation Progress

Implemented on 2026-06-15:

```text
src/aac/consequence_prior.py
src/envs/consequence_scar.py
experiments/consequence_prior_g13.py
tests/test_consequence_prior_g13.py
experiments/consequence_prior_g13.development.json
```

Development audit on seeds `1750..1769`:

```text
Scar validity screen: PASS
R0 reversible CP vs P0: adv=-0.274, first-window stale_prior_harm=13.094,
                         any reversible-cell harm seeds=17/20
R1 irreversible CP vs P0: adv=+0.048, wins=14/20, p=0.00604, damage_adv=+0.434
Specificity contrast: +0.264, CI lower +0.125
CAUTIOUS capture: 0.470
Gate preview: NOT MET preview because G13-1 irreversible benefit and
              G13-3 stale-prior guard fail.
```

This was not a r-final result and did not change the G13 gate. The r-final path was
then unlocked by `experiments/consequence_prior_g13.freeze.json` after founder approval.

## Result

R-final executed once on seeds `1800..1829`:

```text
Result artifact: experiments/consequence_prior_g13.result.json
Freeze artifact: experiments/consequence_prior_g13.freeze.json
Scar validity screen: PASS
G13 verdict: NOT MET

R0 reversible CP vs P0:
  adv=-0.255
  first-window stale_prior_harm=12.679
  any reversible-cell harm seeds=21/30

R1 irreversible CP vs P0:
  adv=+0.083
  wins=25/30
  p=0.000001895
  loss-reduction CI=[291.66,589.94]
  damage_adv=+0.463

Specificity:
  contrast=+0.317
  CI lower=+0.150

CAUTIOUS capture:
  0.533
```

Gate status:

```text
G13-1 irreversible benefit: FAIL
  Net R1 advantage is +0.083, below the +0.10 threshold, despite strong
  damage reduction and paired significance.

G13-2 scar specificity: PASS
  Irreversible advantage is meaningfully larger than reversible advantage.

G13-3 no stale-prior harm: FAIL
  R0 advantage is -0.255 and any reversible-cell harm occurs in 21/30 seeds.

G13-4 C6/C7 invariants: PASS
  Covered by tests/test_consequence_prior_g13.py.
```

Interpretation:

G13 is a clean negative, not an invalid experiment. The consequence prior did learn a
real damage-avoidance signal in irreversible cells, but that signal did not produce
enough net loss advantage and it repeated the pre-registered stale-prior harm pattern in
reversible cells. CAUTIOUS captured more than half of the damage reduction, further
weakening the need for this belief-channel organ.

The result strengthens the current program conclusion: frozen P0's subject-side
confidence coupling remains the dominant confirmed lever. A future consequence-prior
attempt must be a new ADR with a theory for escaping the belief-channel ceiling; it must
not retune or rescue this G13 candidate.

## Consequences

- The next core work is no longer "synthesize ADR-0034/0035 and ask for direction";
  founder direction has selected this narrow G13 gate.
- G12 remains inconclusive. ADR-0036 does not modify that record.
- G10 remains the only decisive confirmed positive gate.
- The result is `NOT MET`, acceptable, and informative: it strengthens the conclusion
  that P0's subject-side confidence coupling is the dominant lever even under scarred
  environments.
