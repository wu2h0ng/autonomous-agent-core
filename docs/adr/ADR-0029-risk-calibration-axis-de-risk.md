# ADR-0029: Third axis candidate — risk calibration in a stationary env (de-risk)

- Status: **Accepted (pre-registration; founder-directed 2026-06-14 "继续设计新收益轴"). Decision rule §3 frozen before any run. De-risk probe; gate freeze remains founder-reserved.**
- Date: 2026-06-14
- Deciders: founder directed continued hunting for an independent system-level axis. Agent drafts per ADR-0003 + ADR-0027 §4.3.
- Scope: route-C third-axis de-risk. Reuses the frozen G9 gate + `ViabilityCore`; a small stationary risk env is defined in the experiment (probe-local; promote to `src/envs/` only if it graduates to a gate). No new mechanism, no spend, no LLM, no cross-repo. C6/C7 intact.
- Predecessors: ADR-0024/G10 (reframe win), ADR-0026/C3 (endogeny RED), ADR-0028 (survival RED — a shadow of reframe).

## 1. Why this axis, and the mechanism hypothesis it tests

C3 and the survival axis both returned RED because they were **shadows of adaptation speed** — anything measured in a *shifting* env correlates with how fast the gate re-commits after a shift. To find a genuinely independent axis, remove adaptation entirely: a **stationary** env (no regime shifts). The only thing left for a mechanism to exploit is **risk calibration** — committing in proportion to certainty when actions differ in *variance*, not in when-the-world-changes.

**Mechanism hypothesis (pre-registered, predicting the likely outcome):** the G9 gate computes confidence as `gap/(kappa·u)` on the *leader's separation*. This is confidence-calibrated commitment **on a clear leader**, not variance-aversion. So the gate is predicted to provide **no independent risk-aversion**: with equal-mean actions it cannot form a confident leader (gap≈0 → stays exploratory → exposed to variance like a coin-flip); with a higher-mean "trap" it down-weights the trap only by *learning its mean drops* after catastrophes — which is adaptation/learning speed again. If this holds, the verdict is RED and it is the **third convergent confirmation that the gate is one lever**.

The probe exists to *empirically* confirm or refute this, not to assume it.

## 2. Design

- Env (stationary, no shifts): 8 actions. Seven "safe" actions ~ `N(2.0, 0.3)`. One "trap" action: normally `N(2.6, 0.5)` (highest apparent mean → tempting to a greedy agent) but with probability `p_cat=0.05` returns a **catastrophe** `-30.0`. The trap's true expected value (≈ 2.6·0.95 − 30·0.05 = +0.97) is the worst, but its catastrophe-free early samples look best.
- Tight `ViabilityCore` (calibrated so a few catastrophes can kill); reward feeds budget, metabolize drains; death at budget ≤ 0.
- Arms (same temperature regimes as ADR-0028): GATED (gate on), EXPLOITER (greedy, base_temp 0.05), EXPLORER (broad, base_temp 2.0).
- Metric: **survival steps** (capped at STEPS) and catastrophe count. No regret axis (stationary → post-shift regret undefined); survival here is driven purely by risk calibration, not adaptation.

## 3. Pre-registered decision rule (frozen; ENGINEERING.md §4 items 5–6)

- Fresh seeds `1100..1129` (30), disjoint from all prior runs. Candidate pre-specified: GATED.
- Env-validity `{B0, m, p_cat}` may be calibrated on disjoint seeds `1090..1099` (mechanisms untouched); report effect size + bootstrap CI.

| check | requirement |
|---|---|
| **R-1** gate survives a stationary risk env better than the best cheap arm | GATED survival > max(EXPLOITER, EXPLORER) survival on ≥21/30 & Wilcoxon p<0.05 |
| validity | EXPLOITER (greedy) must actually suffer the trap (lower survival than a safe-committer would) — else the env has no risk to calibrate |
| C6/C7 | gate reads only the subject's model; forbidden/pause dominate |

**Verdict:** GREEN (R-1 holds) → a genuine **independent** second axis (risk calibration, no adaptation) → recommend founder consider reviving a 2-axis G11. RED (R-1 fails) → the gate has no independent risk-aversion → **third confirmation of the single-lever finding**; close the multi-axis hunt, G10 stands.

## 4. Implementation

| file | role |
|---|---|
| `experiments/risk_calibration_c1.py` | stationary risk env (probe-local) + arms GATED/EXPLOITER/EXPLORER; survival + catastrophe count, effect size + bootstrap CI |
| `tests/test_risk_calibration_c1.py` | determinism + C6/C7 guards + env catastrophe behaviour |

## 5. Disposition

Informative either way; **no arm retuned after results** (only env-validity `{B0,m,p_cat}` pre-r-final). Result recorded in §6 + ROADMAP after the run.
