# ADR-0020: G7 LatentRegimeOrgan, Bayesian regime tracking gate

- Status: Accepted; corrected G7 r-final NOT MET (2026-06-13)
- Date: 2026-06-13
- Scope: P4.x structured-regime prior organ, no LLM, no spend, no new runtime dependency
- Predecessor: ADR-0017 G6a showed that `RegimeLibraryOrgan` beats the cheap reset on a structured recurring-regime environment, but only marginally.

## 1. Context

G6a produced the first positive learned-prior result in this prototype line:

| arm | mean post-shift regret area, seeds 0-9 | result |
|---|---:|---|
| O0 no organ | 1384.8 | baseline |
| O1 cheap reset | 1332.0 | cheap baseline |
| O2 regime library | 1269.3 | -4.7% vs O1, 9/10 wins |

This is real but not yet decisive. O2 leaves most of the available headroom unused because it:

- waits for a small number of distinct observations and then performs a single hard nearest-prototype match;
- injects a recognized prototype only once per regime;
- does not accumulate Bayesian evidence over time;
- does not deliberately shape exploration toward actions that disambiguate plausible regimes.

The new claim is deliberately narrower than "general intelligence": in a fixed recurring latent-regime bandit, a belief-only organ with posterior tracking and information-directed uncertainty shaping should recover after shifts substantially faster than a cheap reset.

## 2. Decision

Implement a new O4 organ:

```text
src/aac/prior_organ_latent.py
LatentRegimeOrgan
```

O4 is a Bayesian latent-regime posterior tracker with information-directed epistemic shaping. It remains a `PriorOrgan`: it reads only `situation` and `BeliefSnapshot`, and returns only `OrganAdvice`. It does not import or call policy, shell, or environment internals. It must not read `regime_index`, even though `StructuredRegimeEnv.situation()` currently exposes it for scoring/debug context.

Per-step mechanism:

1. Shift detection uses the same surprise EMA shape as O1/O2: `warmup`, `ema_lambda`, `spike_k`. Any win must come from identification and post-shift exploitation, not a privileged detector.
2. On detected shift, finalize the just-ended empirical action-reward vector into a learned prototype library and reset the active observation buffer.
3. Maintain a log posterior over learned prototypes using Gaussian observation likelihoods: `log_post[k] += -0.5 * ((reward - proto_k[action]) / sigma)^2`.
4. After a shift, initialize the posterior with a transition prior that down-weights the just-departed prototype. This exploits the environment's learnable fact that a shift moves to a different library regime, without reading the hidden current regime.
5. Every post-shift step, emit confidence-weighted `belief_delta[a] = posterior_mean_reward[a] - mu[a]`, with `uncertainty = inject_weight * confidence`. Unlike O2, injection is continuous rather than one-shot.
6. While confidence is below `probe_confidence`, emit `uncertainty_delta[a]` proportional to posterior-weighted prototype disagreement for action `a`. The policy still chooses actions; O4 only raises epistemic salience on actions that would best distinguish plausible regimes.
7. If no useful library exists, O4 degenerates to a reset-like adviser and should not invent actions or non-belief channels.

Stake-first derivation:

```text
posterior tracking -> faster correct belief over action rewards
-> policy more often selects the current regime's high-reward action
-> lower post-shift regret and higher reward intake
-> ViabilityCore.ingest(reward) protects the budget/survival variable
```

The chain terminates at the essential viability variable, not at prediction cleverness alone.

## 3. Calibration protocol, frozen before r-final

Calibration is allowed only on disjoint seeds `200..219`. The r-final seeds are never used for parameter choice.

The calibration command is:

```bash
PYTHONPATH=src python experiments/latent_regime_g7.py calibrate
```

The scan space is finite and declared in the experiment script before r-final. At minimum it may scan:

- `sigma`
- `inject_weight`
- `info_weight`
- `probe_confidence`
- `departed_penalty`
- `max_belief_delta`

Selection rule:

1. Select the parameter set with the lowest mean O4 post-shift regret area on calibration seeds.
2. If tied within 0.5 area points, select the simpler/lower-gain set in lexical order of the printed parameter tuple.
3. Freeze the selected defaults in `LatentRegimeOrgan` and record them in this ADR before running r-final.

G7-1 margin target:

```text
calib_reduction = 1 - mean_calib(O4) / mean_calib(O1)
delta = 0.20, if calib_reduction >= 0.20
delta = floor(100 * 0.80 * calib_reduction) / 100, otherwise
```

The target can move downward only according to this formula and only before r-final. It cannot be moved upward after seeing calibration and cannot be changed after r-final.

## 4. G7 preregistered gate

Arms share the same subject and environment harness. Only the organ slot differs:

```text
O0 = no organ
O1 = ResetScaffoldOrgan
O2 = RegimeLibraryOrgan
O4 = LatentRegimeOrgan
```

Environment and metric:

- `StructuredRegimeEnv`
- `N_ACTIONS = 8`
- `STEPS = 2000`
- `WINDOW = 15`
- metric: post-shift regret area, identical to `experiments/structured_g6a.py`
- r-final seeds: `0..29`
- r-final is one shot. No rerolling seeds, no environment shopping, no mechanism tuning after r-final.

Gate criteria:

| criterion | requirement |
|---|---|
| G7-1 decisive mean margin | `mean(O4) <= (1 - delta) * mean(O1)` |
| G7-2 advance over current learned organ | O4 beats O2 on at least 90% of r-final seeds |
| G7-3 per-seed dominance over cheap reset | O4 beats O1 on at least 29/30 r-final seeds |
| G7-4 statistical significance | paired one-sided Wilcoxon signed-rank test, O4 vs O1, `p < 0.01` |
| G7-C6 organ-not-subject | deterministic tests prove belief-only output and no policy/shell import; boosted forbidden action stays blocked |
| G7-C7 corrigibility undiminished | deterministic tests prove pause prevents organ consultation and action |

G7 is MET only if all six rows pass.

## 5. Wilcoxon implementation contract

The experiment script implements the Wilcoxon signed-rank test using only the Python standard library.

Input differences are paired as:

```text
d_i = O1_area_i - O4_area_i
```

Positive `d_i` means O4 improves over O1. Zero differences are dropped. Absolute differences are ranked with average ranks for ties. The one-sided p-value is the exact probability, under random sign flips, of observing a positive-rank sum at least as large as the measured sum. For `n <= 30`, exact enumeration is acceptable in this repository scale.

## 6. Required tests

Add deterministic unit tests in:

```text
tests/test_prior_organ_latent.py
```

Minimum coverage:

- no action/policy/shell/forbidden field on advice;
- module does not import policy or shell;
- pause prevents organ consultation through `Agent.step`;
- tightened/forbidden action remains blocked even when O4 boosts it;
- deterministic replay yields identical advice/state;
- posterior concentrates on the correct prototype in a synthetic recurring sequence;
- continuous injection moves belief toward the posterior mean after recognition;
- information-directed uncertainty shaping prefers actions with high prototype disagreement while confidence is low;
- `regime_index` in `situation` is ignored.

Do not make stochastic end-to-end G7 pass/fail a unit test.

## 7. Implementation files

| file | change |
|---|---|
| `src/aac/prior_organ_latent.py` | new O4 organ |
| `experiments/latent_regime_g7.py` | new calibration and r-final gate harness |
| `tests/test_prior_organ_latent.py` | new deterministic mechanism and guard tests |
| `docs/adr/ADR-0020-g7-latent-regime-organ.md` | this preregistration plus frozen params/results updates |
| `codebase_index.md` | update after implementation/result |
| `docs/PROJECT_PLAN.md` | update result ledger after r-final |
| `../docs/research/RR-0003-autonomous-agent-prototype-design.md` | add G7 result after r-final |

## 8. NOT MET disposition

If G7-1 or G7-4 fails, record:

```text
Even Bayesian latent-regime tracking with active disambiguation does not significantly beat the cheap reset at this prototype scale.
```

Do not retune O4 and rerun G7. If O4 beats O1 but fails O2 dominance, record that the added posterior machinery was not worth its complexity. If C6 or C7 fails, the experiment is invalid until the boundary violation is fixed; no performance result may be claimed from a boundary-violating organ.

## 9. Status log

- 2026-06-13: ADR created before O4 implementation and before G7 calibration/r-final.
- 2026-06-13: O4 implemented (`src/aac/prior_organ_latent.py`), experiment harness (`experiments/latent_regime_g7.py`), deterministic tests (`tests/test_prior_organ_latent.py`).
- 2026-06-13: Validity repair before corrected r-final: `confidence` now means maximum posterior probability, prototype records keep known-action masks so unknown actions are not treated as strong evidence, and `wilcoxon_one_sided` now ranks by absolute differences with average ranks for ties.
- 2026-06-13: Corrected calibration on seeds 200..219 complete. FROZEN params:
  - `sigma=0.5, inject_weight=0.85, info_weight=0.3, probe_confidence=0.7, departed_penalty=2.0, max_belief_delta=2.0`
  - calib O1=1311.5, calib O4=1194.0, calib_reduction=0.0896, delta=0.07
- 2026-06-13: Corrected r-final gate on seeds 0..29 complete:

| arm | mean post-shift regret area, seeds 0-29 |
|---|---:|
| O0 no organ | 1361.6 |
| O1 cheap reset | 1325.6 |
| O2 regime library | 1271.6 |
| O4 latent regime | 1224.3 |

| criterion | result |
|---|---|
| G7-1 decisive mean margin | 1224.3 <= 1232.8=(1-0.07)*1325.6 PASS |
| G7-2 O4 < O2 | 26/30 (need >=27) FAIL |
| G7-3 O4 < O1 | 29/30 (need >=29) PASS |
| G7-4 Wilcoxon | p<0.000001 PASS |
| G7-C6 organ-not-subject | unit tests PASS |
| G7-C7 corrigibility | unit tests PASS |

**G7: NOT MET.** Bayesian latent-regime posterior tracking with information-directed epistemic shaping significantly beats the cheap reset, but it misses the preregistered 90% dominance bar over the current learned O2 organ by one seed. Per this ADR, O4 is not retuned and rerun under G7.
