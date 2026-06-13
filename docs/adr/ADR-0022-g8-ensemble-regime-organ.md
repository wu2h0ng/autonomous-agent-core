# ADR-0022: G8 EnsembleRegimeOrgan, non-retuned O2+O4 belief ensemble

- Status: Accepted; **G8 NOT MET** (2026-06-14) — ensemble ties O4, no significant gain (see §7)
- Date: 2026-06-13
- Scope: P4.x structured-regime prior organ, no LLM, no spend, no new runtime dependency
- Predecessor: ADR-0020 corrected G7 is NOT MET. O4 significantly beats O1, but misses O2 seed-dominance by one seed.

## 1. Context

G7 taught a narrower lesson than the original target:

| arm | corrected G7 mean area, seeds 0-29 |
|---|---:|
| O1 cheap reset | 1325.6 |
| O2 one-shot regime library | 1271.6 |
| O4 Bayesian latent regime | 1224.3 |

O4 is clearly better than O1 (29/30, p<0.000001), but G7 fails because O4 beats O2 on 26/30 seeds, one short of the preregistered 27/30 bar. O4 must not be retuned and rerun under G7.

The failure pattern suggests complementarity rather than replacement:

- O2 is aggressive and sometimes wins through a hard one-shot prototype jump.
- O4 is smoother and better on mean through continuous posterior tracking, but its known-mask repair makes it more conservative in sparse-evidence regimes.

G8 tests a new mechanism rather than moving the G7 gate: an ensemble organ that combines the realized belief advice from O2 and O4 while remaining inside the same belief-only `PriorOrgan` contract.

## 2. Decision

Implement:

```text
src/aac/prior_organ_ensemble.py
EnsembleRegimeOrgan
```

O5 contains an internal `RegimeLibraryOrgan` and an internal `LatentRegimeOrgan`. On each step it:

1. calls both organs with the same `situation` and `BeliefSnapshot`;
2. converts each advice into its realized belief contribution by multiplying deltas by that advice's `uncertainty`;
3. adds the contributions channel-wise;
4. clamps belief and uncertainty deltas by `delta_cap`;
5. returns one `OrganAdvice` with `uncertainty=1.0` when any clamped contribution exists.

This preserves the `merge_organ_advice()` semantics: the ensemble has already weighted sub-advice by sub-organ confidence, so the outer advice is a realized belief delta. O5 still emits only `belief_delta` and `uncertainty_delta`; it never returns an action and never imports policy/shell.

## 3. Calibration protocol

Calibration uses fresh seeds `500..519`, disjoint from:

- G6a seeds `0..9`
- G7 calibration seeds `200..219`
- G7 r-final seeds `0..29`
- O5 exploratory viability-check seeds `300..319`
- G8 r-final seeds `600..629`

Command:

```bash
PYTHONPATH=src python experiments/ensemble_regime_g8.py calibrate
```

Finite grid:

| parameter | values |
|---|---|
| `delta_cap` | `1.5, 2.0, 3.0` |
| `o2_weight` | `0.5, 1.0` |
| `o4_weight` | `0.5, 1.0` |

Selection rule:

1. Select the parameter set with the lowest mean O5 post-shift regret area on calibration seeds.
2. If tied within 0.5 area points, choose the lower-gain tuple in lexical order: `(delta_cap, o2_weight, o4_weight)`.
3. Freeze the selected defaults in `EnsembleRegimeOrgan` and `experiments/_g8_common.py` before r-final.

G8-1 margin target:

```text
calib_reduction = 1 - mean_calib(O5) / mean_calib(O1)
delta = 0.20, if calib_reduction >= 0.20
delta = floor(100 * 0.80 * calib_reduction) / 100, otherwise
```

## 4. G8 preregistered gate

Arms:

```text
O1 = ResetScaffoldOrgan
O2 = RegimeLibraryOrgan
O4 = LatentRegimeOrgan
O5 = EnsembleRegimeOrgan
```

Environment and metric:

- `StructuredRegimeEnv`
- `N_ACTIONS = 8`
- `STEPS = 2000`
- `WINDOW = 15`
- metric: post-shift regret area, identical to G6a/G7
- r-final seeds: `600..629`
- r-final is one shot. No rerolls, no seed shopping, no O5 retuning after r-final.

Gate criteria:

| criterion | requirement |
|---|---|
| G8-1 decisive mean margin over cheap reset | `mean(O5) <= (1 - delta) * mean(O1)` |
| G8-2 dominance over current learned baseline | O5 beats O2 on at least 90% of r-final seeds |
| G8-3 improvement over O4 attempt | O5 mean < O4 mean and Wilcoxon one-sided O5 vs O4 p < 0.05 |
| G8-4 statistical significance vs baselines | Wilcoxon one-sided O5 vs O1 and O5 vs O2 p < 0.01 |
| G8-C6 organ-not-subject | deterministic tests prove belief-only output and no policy/shell import |
| G8-C7 corrigibility undiminished | deterministic tests prove pause/tighten still dominate |

G8 is MET only if all rows pass.

## 5. Required tests

Add:

```text
tests/test_prior_organ_ensemble.py
```

Minimum coverage:

- advice has no action/policy/shell/forbidden field;
- module does not import policy or shell;
- deterministic replay;
- weighted sub-advice is clamped and emitted as realized belief delta;
- `reset()` resets both child organs;
- pause prevents consultation through `Agent.step`;
- tightened action remains blocked even under an extreme O5 boost.

## 6. NOT MET disposition

If G8 fails, record the exact failing criterion. Do not retune O5 and rerun G8. A failure means the O2+O4 complementarity hypothesis is not established under this gate.

## 7. Status log

- 2026-06-13: ADR created before O5 implementation, before G8 calibration, and before G8 r-final.
- 2026-06-14: O5 implemented (`src/aac/prior_organ_ensemble.py`), experiment harness
  (`experiments/ensemble_regime_g8.py`), deterministic tests
  (`tests/test_prior_organ_ensemble.py`, 9 tests). Calibration on disjoint seeds 500..519:
  FROZEN `delta_cap=2.0, o2_weight=0.5, o4_weight=1.0` (calib O1=1247.8, calib O5=1138.0,
  calib_reduction=0.0880, delta=0.07).
- 2026-06-14: G8 r-final gate on seeds 600..629:

| arm | mean post-shift regret area, seeds 600-629 |
|---|---:|
| O1 cheap reset | 1289.6 |
| O2 regime library | 1232.3 |
| O4 latent regime | 1183.7 |
| O5 ensemble | 1180.4 |

| criterion | result |
|---|---|
| G8-1 decisive mean margin over O1 | 1180.4 <= 1199.3=(1-0.07)*1289.6 PASS |
| G8-2 O5 < O2 | 27/30 (need >=27) PASS |
| G8-3 improvement over O4 | mean(O5)<mean(O4) but Wilcoxon O5 vs O4 p=0.306 >= 0.05 **FAIL** |
| G8-4 significance vs O1 and O2 | p<0.000001 both PASS |
| G8-C6 organ-not-subject | unit tests PASS |
| G8-C7 corrigibility | unit tests PASS |

**G8: NOT MET.** O5 significantly beats O1 (30/30) and O2 (27/30), but it does **not**
significantly improve on O4 (O5 1180.4 vs O4 1183.7, O5<O4 only 15/30, Wilcoxon p=0.306).
The O2+O4 complementarity hypothesis is **not established**: a belief-only ensemble of the
two organs is statistically indistinguishable from O4 alone. Per §6, O5 is not retuned and
rerun. This is the third consecutive belief-only result (G7 O4, then G8 O5) that fails to
break the ~8-13% advantage ceiling over the cheap reset on this environment — consistent with
the bounded-advantage finding that most post-shift regret is policy-exploration cost a
belief-only adviser cannot remove (RR-0005 G7/G8 addendum).
