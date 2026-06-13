# ADR-0021: P1 论文加固实验——结构可迁移性谱系扫描 + O4 消融

- Status: Accepted; experiments implemented, results pending full run
- Date: 2026-06-13
- Scope: Paper-strengthening experiments for the G7 result, no new mechanism, no new organ
- Predecessor: ADR-0020 G7 LatentRegimeOrgan MET decisively; reviewers will ask "under what conditions?" and "which component matters most?"

## 1. Context

G7 established that O4 (LatentRegimeOrgan) decisively beats O1 (cheap reset) on StructuredRegimeEnv with default parameters (n_regimes=5, noise=0.3, period=40):

- O4=1194.1 vs O1=1325.6 (-9.9%)
- O4 < O1 on 30/30 seeds, Wilcoxon p < 0.000001

Two questions must be answered before the paper is submittable:

1. **Boundary conditions**: The advantage was demonstrated at one point in parameter space. Reviewers will ask where O4 stops winning.
2. **Component contributions**: O4 has four mechanisms (Bayesian update, continuous injection, info-directed shaping, transition prior). Which contribute, and by how much?

Neither question requires new mechanism design. Both are pure measurement on the existing, frozen O4.

## 2. Decision

### T1: Structure-transferability spectrum scan

Vary two StructuredRegimeEnv parameters while holding O4 and O1 frozen:

| Dimension | Values | Rationale |
|---|---|---|
| n_regimes | 2, 5, 10, 20 | From trivially separable (2) to challenging library size (20) |
| noise | 0.1, 0.3, 0.5, 1.0 | From clean signal to noise-dominated observations |

Grid: 4 x 4 = 16 conditions. 2 arms (O1, O4), 10 seeds (0-9) per condition.

**Metric**: post-shift regret area (window=15), identical to G7.

**Decision rule** (pre-registered, not to be changed after seeing results):

- advantage = 1 - mean(O4) / mean(O1)
- significant = advantage > 0 AND paired one-sided Wilcoxon p < 0.05

**Expected output**: a phase-boundary map showing where O4 wins and where it degenerates to parity with O1.

### T2: O4 ablation study

Five arms, all using O4_FROZEN parameters, varying only which mechanism is disabled:

| Arm | Disabled mechanism | Implementation |
|---|---|---|
| O4-full | none (control) | `LatentRegimeOrgan(**O4_FROZEN)` |
| O4-no-info | information-directed shaping | `info_weight=0.0` |
| O4-no-transition | transition prior | `departed_penalty=0.0` |
| O4-oneshot | continuous injection | `continuous_inject=False` (new flag) |
| O4-no-posterior | Bayesian evidence accumulation | `bayesian_update=False` (new flag) |

30 seeds (0-29), paired with G7 r-final.

**Metric**: post-shift regret area (window=15), identical to G7.

**Statistics**: paired one-sided Wilcoxon, d_i = ablation_i - full_i (positive = full better = ablation hurts). Significance threshold p < 0.05.

**Ablation body definition** (per ENGINEERING.md §4.4): each ablation arm defines "what O4 looks like with this mechanism turned off." The two new boolean flags (`continuous_inject`, `bayesian_update`) default to True and have zero effect on production O4 behaviour.

### Mechanism invariants

Both experiments are **pure measurement** on the existing, frozen O4:

- No new organ is designed.
- No O4 parameter is re-calibrated.
- No gate criteria are adjusted after seeing results.
- C6 (organ-not-subject) and C7 (corrigibility) guards are verified for all ablation variants.

## 3. Stake-first derivation

```
spectrum scan -> boundary map of O4 advantage
             -> answers "when does learning pay off?"
             -> paper claim conditioned on structure transferability

ablation study -> component contribution table
              -> answers "what makes O4 work?"
              -> paper interpretability section (§6)
```

Both terminate at the paper's scientific claims, not at mechanism design changes.

## 4. Implementation

### New files

| File | Role |
|---|---|
| `experiments/_g7_common.py` | Shared utilities (run_area, wilcoxon_one_sided, format_table, constants) |
| `experiments/spectrum_scan.py` | T1 spectrum scan |
| `experiments/ablation_o4.py` | T2 ablation study |
| `tests/test_spectrum_scan.py` | T1 logic tests |
| `tests/test_ablation_o4.py` | T2 ablation flag behaviour + C6/C7 guards |

### Modified files

| File | Change |
|---|---|
| `src/aac/prior_organ_latent.py` | Add `continuous_inject: bool = True` and `bayesian_update: bool = True` ablation flags |
| `experiments/latent_regime_g7.py` | Refactor to import from `_g7_common` (behaviour unchanged) |

## 5. Pre-registration checklist (frozen before first full run)

- [x] Parameter grids frozen: n_regimes=[2,5,10,20], noise=[0.1,0.3,0.5,1.0]
- [x] Seeds frozen: 0-9 (spectrum), 0-29 (ablation)
- [x] Metric frozen: post-shift regret area (window=15)
- [x] Decision rules frozen: advantage > 0 AND Wilcoxon p < 0.05
- [x] 5 ablation arms frozen, no additions
- [x] O4_FROZEN parameters not re-calibrated
- [x] Will not adjust grids/arms/thresholds after seeing results

## 6. Consequences

- **Positive**: Paper can include a phase-boundary heatmap and a component-contribution table, directly answering the two most likely reviewer questions.
- **Negative**: ~5 minutes of compute time for the full spectrum scan + ablation.
- **Risk**: If O4 wins in very few conditions, the paper's scope narrows. This is an honest scientific result and will be reported as-is (per ENGINEERING.md §4.3: negative results are first-class citizens).
