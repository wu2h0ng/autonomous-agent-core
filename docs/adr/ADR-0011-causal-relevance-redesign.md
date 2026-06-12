# ADR-0011: Causal Relevance Redesign for Claim 2

- Status: Accepted and implemented (G2 NOT MET, 2026-06-12)
- Date: 2026-06-12
- Deciders: founder (requested one more redesign after ADR-0010 D5), agent under ADR-0003
- Relates: ADR-0002, ADR-0004, ADR-0005, ADR-0007, ADR-0010

## Context

Claim 2 has failed four honest gates: G0, G1, G1-r, and G1'. ADR-0010 showed that the contextual organ is real and used, and that adaptive attention can track the drifting relevant set S, but the pre-registered gate still did not clear.

The latest diagnosis is not "the component is broken"; it is that the current framing still lets two artifacts dominate the result:

1. Fixed attention can win by luck. If a fixed subset happens to cover the relevant cues for a regime, it learns a stable contextual key faster than the adaptive mechanism.
2. The recovery metric is too sparse. In a lethal environment, many variants die before a 20-step success window can be observed, so recovery becomes a weak discriminator.
3. Per-cue information power is too shallow. It estimates marginal cue value, but relevance in the environment is a latent set relation: a cue can be individually weak while the set is jointly decisive.
4. ContextualActionModel currently keys exact attended cue patterns. This makes action learning depend on the selected attention subset and can fragment evidence across equivalent supersets.

The founder has chosen to redesign once more. This ADR treats that as a new mechanism proposal, not as permission to tune ADR-0010 until it passes.

## Options Considered

### Option A: Retune ADR-0010

Examples: change budget, regime period, recovery window, reward_miss, attention cost, or ContextualActionModel margin.

- Benefit: least work.
- Cost: high moving-the-goal risk after four NOT MET results.
- C1-C7 compatibility: technically compatible, but weak research discipline.
- Verdict: rejected.

### Option B: Replace the task with an easier relevance task

Examples: make S stable longer, reduce K, increase m, or make relevant cues have strong independent marginal signal.

- Benefit: likely to produce a clean pass.
- Cost: tests a weaker claim than RR-0001 intends. It would show feature selection, not relevance realization under reframing pressure.
- C1-C7 compatibility: compatible but scientifically weak.
- Verdict: rejected.

### Option C: Causal relevance search + anti-luck evaluation

Add a mechanism that treats relevance as a latent causal explanation and measures it in a schedule designed to remove fixed-attention luck.

- Benefit: directly targets the remaining failure mode: discovering a jointly relevant set after drift and converting it into action.
- Cost: more implementation work; may still fail, in which case claim 2 should be downgraded without another redesign.
- C1-C7 compatibility: compatible. The mechanism remains deterministic, stdlib-only, domain-free, non-LLM, and inside Ring 1.
- Verdict: selected for proposal.

## Decision

Propose a final redesign named **Causal Relevance Protocol (CRP)**.

### D1: Add `CausalRelevanceField`

New module: `src/aac/causal_relevance.py`.

The field maintains a posterior over candidate relevant cue sets S of size `k_rel`.

Minimum interface:

```text
CausalRelevanceField(K, k_rel, m)
  .select_attention(pressure, rng) -> list[int]
  .update(cues, attended, action, reward, prediction_before) -> None
  .on_surprise(surprise) -> None
  .best_hypothesis() -> tuple[int, ...] | None
  .entropy() -> float
  .confidence() -> float
```

Mechanism rules:

- After surprise, enter a reframing epoch.
- During reframing, choose attention by expected information gain over candidate S, not by marginal per-cue reward gap alone.
- Maintain evidence for candidate sets using how well their observed cue patterns explain action reward prediction error.
- Pressure may shrink attention budget, but must not directly force exploitation.
- Stop reframing only when posterior entropy is low and the contextual action model has a confident winner for the hypothesized relevant pattern.

This is a structural redesign, not a parameter tweak. It is allowed only because the founder explicitly requested one more redesign after D5.

### D2: Add `FactorizedContextualActionModel`

New module: `src/aac/factorized_contextual.py`.

Problem in ADR-0010: exact attended-pattern keys fragment learning across attention supersets.

The new model keys action values by the hypothesized relevant subset rather than the full attended subset:

```text
key = (hypothesis_S, values_of_S)
```

Minimum interface:

```text
FactorizedContextualActionModel(n_actions)
  .best_action(cues, hypothesis_S) -> int
  .confident(cues, hypothesis_S) -> bool
  .update(cues, hypothesis_S, action, reward) -> None
```

If no confident hypothesis exists, the agent explores. If a hypothesis is wrong, reward error flows back to `CausalRelevanceField`.

### D3: Add an anti-luck evaluation environment/schedule

Do not make the environment easier. Instead, remove the fixed-attention lottery.

New experiment: `experiments/causal_relevance_g2.py`.

Use the existing lethal cue-foraging economics where possible, but control regime schedules:

- `K=12`, `k_rel=2`, `m=3`, `n_actions=4`.
- Seeds 0-9.
- Each seed gets a balanced regime schedule of relevant sets.
- No fixed m-subset may cover more than 25% of regimes in a seed.
- All variants receive the exact same cue stream, reward noise stream, and regime schedule for a seed.
- The schedule is generated before the run and is not conditioned on any variant's behavior.

This is not adversarial remapping against B0. It is a validity guard against accidental B1 wins.

### D4: Replace sparse recovery with post-shift adaptation area

Primary recovery metric becomes **post-shift optimal-action area**.

For every regime shift, measure the first `H=40` post-shift steps:

```text
adaptation_area = mean(correct_action_t for t in shift+1 ... shift+H)
```

If an agent dies before H, missing steps count as 0. This keeps death meaningful and avoids the sparse-window failure from ADR-0010.

Secondary metric, not a gate: first step where a rolling 10-step optimal-action rate is at least 0.6.

### D5: G2 variants

All variants keep ISO-1/ISO-2 shell constraints unchanged.

| Variant | Relevance mechanism | Action model | Purpose |
|---|---|---|---|
| G2-B0 | CausalRelevanceField | FactorizedContextualActionModel | Full redesign |
| G2-B1 | fixed random m cues | FactorizedContextualActionModel | fixed-attention anti-luck baseline |
| G2-B2 | full attention K cues | FactorizedContextualActionModel | metabolic-cost baseline |
| G2-B3 | uniform rotating m cues | FactorizedContextualActionModel | non-adaptive coverage baseline |
| G2-B4 | ADR-0010 AttentionField | ContextualActionModel | previous best mechanism baseline |
| G2-B5 | CausalRelevanceField ablated to random posterior | FactorizedContextualActionModel | guards against model-only explanation |

### D6: Pre-registered G2 gate

Run seeds 0-9, at least 20 regimes per seed, `H=40`.

G2 is **MET** only if all are true:

1. B0 survival steps beat B1, B3, and B4 in at least 7/10 seeds each.
2. B0 post-shift adaptation_area beats B1, B3, and B4 in at least 7/10 seeds each.
3. B0 survival steps beat B2 in at least 7/10 seeds.
4. B0 beats B5 adaptation_area in at least 8/10 seeds.
5. No variant-specific special-case logic outside variant construction.
6. Mechanism parameters are declared at the top of the experiment and not tuned after seeing G2 results.

If G2 is NOT MET, claim 2 must be recorded as:

```text
partially supported but not experimentally established in this prototype line
```

After a G2 NOT MET, no further claim-2 mechanism redesign is allowed without a new founder-level research reset ADR.

## Consequences

- ADR-0010 remains an honest NOT MET result, not a failure to be patched.
- Existing `AttentionField` and `ContextualActionModel` stay as historical baselines.
- New work is scoped to:
  - `src/aac/causal_relevance.py`
  - `src/aac/factorized_contextual.py`
  - optional schedule support in `src/envs/`
  - `experiments/causal_relevance_g2.py`
  - focused tests for posterior update, anti-luck schedule, factorized keys, and gate accounting.
- Do not touch shell isolation, audit, LLM boundaries, or business-domain code.
- Do not change C1-C7.
- Do not import code from sibling repos.

## Implementation Task Cards

### T1: Balanced Regime Schedule

Implement a deterministic schedule helper that emits relevant-set schedules with no fixed m-subset covering more than 25% of regimes. Unit tests must fail if a schedule lets a fixed subset cover too many regimes.

### T2: CausalRelevanceField

Implement posterior maintenance and attention selection. Tests must cover entropy drop on informative observations, reset on surprise, and no direct pressure-to-exploit coupling.

### T3: FactorizedContextualActionModel

Implement hypothesis-keyed action values. Tests must prove that equivalent attention supersets share action learning when they imply the same hypothesized S values.

### T4: G2 Experiment

Implement `experiments/causal_relevance_g2.py` with variants B0-B5 and the pre-registered gate above. First run result, whether MET or NOT MET, must be written back to this ADR and `docs/PROJECT_PLAN.md`.

## G2 Result (2026-06-12)

Command:

```text
PYTHONPATH=src python experiments/causal_relevance_g2.py
```

Fixed pre-run parameters:

```text
K=12 k_rel=2 m=3 regimes=20 regime_period=60 max_steps=1200
budget=250.0 capacity=300.0 metabolic=0.05 attention_cost=0.08 rewards=(2.0,-1.5)
seeds=0..9
```

Balanced schedule validity:

- Per-seed max fixed m-subset coverage was 4 or 5 regimes out of 20.
- This satisfies the anti-luck bound of at most 25%.

Aggregate result:

| Variant | Mean steps | Mean adaptation area | Mean regret/step |
|---|---:|---:|---:|
| G2-B0 causal relevance | 279.7 | 0.236 | 2.641 |
| G2-B1 fixed attention | 973.2 | 0.405 | 1.945 |
| G2-B2 full attention | 303.1 | 0.398 | 1.893 |
| G2-B3 uniform rotation | 361.8 | 0.261 | 2.442 |
| G2-B4 G1' baseline | 441.2 | 0.300 | 2.377 |
| G2-B5 random posterior | 301.9 | 0.252 | 2.573 |

Pre-registered gate:

| Criterion | Result | Required |
|---|---:|---:|
| B0 steps > B1 | 0/10 | >=7/10 |
| B0 steps > B3 | 2/10 | >=7/10 |
| B0 steps > B4 | 0/10 | >=7/10 |
| B0 adaptation > B1 | 0/10 | >=7/10 |
| B0 adaptation > B3 | 5/10 | >=7/10 |
| B0 adaptation > B4 | 1/10 | >=7/10 |
| B0 steps > B2 | 4/10 | >=7/10 |
| B0 adaptation > B5 | 2/10 | >=8/10 |

**G2: NOT MET.**

## Final Claim-2 Disposition for This Prototype Line

Per the hard stop in this ADR:

```text
Claim 2 is partially supported but not experimentally established in this prototype line.
```

Evidence retained:

- Earlier G1/G1-r/G1' results showed selective attention and contextual organs can be functional.
- G1' showed B0 could beat uniform and full-attention baselines in some axes.

Evidence against establishment:

- Four prior gates plus G2 all failed their pre-registered criteria.
- G2 specifically failed after removing fixed-attention coverage luck and replacing sparse recovery with adaptation area.
- Causal relevance search did not beat the previous G1' baseline, random posterior ablation, or fixed attention.

No further claim-2 mechanism redesign is allowed without a new founder-level research reset ADR.
