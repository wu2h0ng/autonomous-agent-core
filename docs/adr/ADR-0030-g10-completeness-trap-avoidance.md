# ADR-0030: G10 completeness check - does the P0 subject-side win survive the empirical traps?

- Status: **Accepted; COMPLETENESS PASS (2026-06-14, see section 8).** P0 survives every
  flip-the-conclusion trap: it beats the strongest fixed-low-temperature baseline (T1),
  transfers to real-stake survival (T3), wins on a structure-free environment (T5b), and
  remains robust across the spectrum (T5a). This is the first trap-complete decisive win
  in the program, corroborating ADR-0024/G10 rather than undercutting it.
- Date: 2026-06-14
- Scope: P6/G10 completeness. Pure measurement plus one additive `base_temperature`
  constructor argument on `Agent` to expose the already existing `PolicySelector`
  temperature knob. The frozen G9 confidence gate is unchanged. No LLM, no spend, no
  dependency, no cross-repo import, no gate-mechanism change.
- Origin: isolated worktree `feat/g10-completeness`, commit `a70dff9`, cherry-picked
  onto current `main` without merging the old branch base.
- Predecessors: ADR-0023/G9 and ADR-0024/G10.

## 1. Why this is not another confirmation

ADR-0024/G10 confirmed that P0 replicates on fresh seeds (40.1% reduction vs A1,
30/30). That rules out seed artifact and keeps the C6/C7 guards intact. It does not
rule out deeper traps that could make the 40% misleading:

- a fixed lower policy temperature might be sufficient;
- the win might be a post-shift window metric artifact;
- the win might disappear when stake is real (finite budget plus metabolic cost);
- the gate might be stealing transferable regime structure rather than fixing policy;
- the result might be a single-point phase accident.

ADR-0030 stress-tests those traps. It does not reopen G10 or move the gate. It asks
whether the already confirmed P0 mechanism is robust enough to keep its interpretation.

## 2. Additive mechanism exposure

`PolicySelector` already has `base_temperature` with default `0.3`. ADR-0030 adds a
matching optional `Agent(..., base_temperature=0.3)` argument and forwards it into the
policy. Default behavior remains unchanged.

This is needed only to construct **B-temp**, the strongest fixed-low-temperature control:

```text
B-temp = confidence_gate=False, no organ, base_temperature=0.03
P0     = confidence_gate=True,  no organ, base_temperature=0.3,
         gate_kappa=0.5, gate_temp_floor=0.1
```

The G9/G10 gate parameters stay frozen.

## 3. Trap matrix

| ID | Trap | Control / Metric | Pass / Interpretation |
|---|---|---|---|
| T1 | Adaptivity is a red herring; fixed low temperature is enough | B-temp, calibrated on disjoint seeds | P0 < B-temp on at least 27/30 seeds and Wilcoxon p < 0.01 |
| T2 | Windowed metric spillover | window area, whole-run mean regret, total reward | P0 best on all directions |
| T3 | Stake decoupling | finite budget plus metabolic cost; survival steps | P0 survives longer than A0 and B-temp, p < 0.05 |
| T5b | Structure theft | `StalenessEnv`, no transferable regime library | P0 win means general policy fix; loss means structure-dependence flag |
| T5a | Single-point result | spectrum over `n_regimes x noise` | phase boundary reported |
| T6 | Greediness erodes corrigibility | tighten high-confidence argmax action | forbidden remains weight-0; pause/tighten dominate |
| T7 | Signal theft | static/interface guard | gate reads only the subject's `ActionOutcomeModel`; no env shift signal |

Completeness requires T1, T2, T3, margin, and C6/C7 to pass. T5a/T5b are
characterisation traps and are recorded as evidence either way.

## 4. Seeds

- B-temp calibration: seeds `970..989`, disjoint from prior runs.
- r-final: seeds `1000..1029`, one shot.
- spectrum: seeds `1000..1009`.

No rerolling, retuning, or seed shopping after results.

## 5. NOT MET disposition

If T1 fails, the honest headline becomes "baseline policy was mistuned"; P0's
adaptivity would be a red herring and ADR-0024's interpretation would need founder
review.

If T3 fails, the 40% proxy win would be a toy-metric artifact and would violate the
stake-first interpretation.

No rescue tuning of P0 or B-temp is allowed.

## 6. Implementation files

| File | Role |
|---|---|
| `src/aac/agent.py` | exposes additive `base_temperature`, default `0.3` |
| `experiments/completeness_g10.py` | calibration, trap matrix, r-final reporting |
| `tests/test_completeness_g10.py` | additive temperature wiring and B-temp guard |
| `docs/adr/ADR-0030-g10-completeness-trap-avoidance.md` | this record |

## 7. Frozen B-temp

Calibration on seeds `970..989` selected:

```text
base_temperature = 0.03
```

This is the strongest fixed-low-temperature arm among the scanned values, so B-temp is
not a straw man.

## 8. Result

Completeness r-final, seeds `1000..1029`:

### Setting A: proxy metrics

| Arm | Window area | Whole-run mean regret | Total reward |
|---|---:|---:|---:|
| A0 baseline | 1329.2 | 1.6233 | 3657.2 |
| A1 cheap reset | 1272.6 | 1.5305 | 3842.9 |
| B-temp fixed-low | 1292.9 | 1.5216 | 3860.5 |
| **P0 gated** | **739.8** | **0.7122** | **5479.4** |

### Trap verdicts

| Trap | Result |
|---|---|
| Margin vs A1 | 739.8 <= 1018.1 PASS |
| T1 vs B-temp | 30/30, p < 1e-6 PASS |
| T2 metric spillover | P0 best on whole-run mean regret and total reward PASS |
| T3 real-stake survival | P0 mean 1734.8 vs A0 1245.3 (p=0.000839) and B-temp 1482.6 (p=0.023926) PASS |
| T5b StalenessEnv | P0 advantage 36.4%, p < 1e-6; GENERAL FIX, not structure theft |
| T5a spectrum | P0 positive advantage across all 16 scanned conditions |
| T6/T7 | unit guards PASS |

**COMPLETENESS: PASS.**

P0 (confidence-gated policy, no organ, C6-preserving) survives every
flip-the-conclusion trap. It is not merely lower exploration, not a windowed-metric
artifact, not detached from viability/stake, not stealing transferable regime
structure, and not a single-point phase accident.

ADR-0030 therefore strengthens the ADR-0024/G10 interpretation: the real positive
mechanism is subject-side belief-to-action coupling. The P4/G6-G8 organ line improved
belief acquisition/quality; the decisive bottleneck was how the subject routes its own
belief into action.

Reproduce:

```powershell
$env:PYTHONPATH='src'; python -m experiments.completeness_g10
```
