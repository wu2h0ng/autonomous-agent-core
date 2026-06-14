# ADR-0028: New independent demand axis — metabolic survival under exploration cost (de-risk for a revived G11)

- Status: **Accepted (pre-registration; founder-directed 2026-06-14 "设计新胜轴"). Decision rule §4 frozen before any run. De-risk probe under ADR-0027 §4.3; the formal gate freeze remains founder-reserved.**
- Date: 2026-06-14
- Deciders: founder directed designing a new winning axis (2026-06-14). Agent drafts per ADR-0003 + ADR-0027 §4.3 (new axis → new ADR with MDE/power + a cheap-baseline-win criterion).
- Scope: route-C second-axis de-risk. Reuses the frozen G9 confidence gate, `StructuredRegimeEnv`, `ViabilityCore`. No new mechanism, no spend, no LLM, no cross-repo. Does not relax C6/C7.
- Predecessors: ADR-0024/G10 (reframe axis: gate wins −40%), ADR-0026/C3 (endogeny axis RED), ADR-0027 (parked the 4-axis G11; routed "want a system gate → design a new axis under a new ADR").

## 1. Context — why survival-under-cost is the right second axis

After C3, only **reframe** was a confirmed vs-cheap-baseline win, so the 4-axis G11 was parked (ADR-0027). A revived G11 needs a *second, independent* axis where the **same confirmed mechanism** — the confidence gate's "collapse exploration when confident, re-inflate when surprised" — wins, and where **no single cheap heuristic can win both axes** (the genuine "whole > best assembly of cheap parts" structure).

Exploration is not free in a metabolic agent: every non-greedy action forgoes reward, and reward is budget (claim-1, ablation-validated). This makes survival a demand the gate serves *for free*:

| cheap heuristic | reframe (post-shift regret) | survival (budget) |
|---|---|---|
| **EXPLORER** (high fixed temp) | good — adapts fast | **poor** — wastes reward exploring when already confident |
| **EXPLOITER** (low fixed temp) | **poor** — locks onto stale action after a shift | good — conserves when stable |
| **GATED** (confidence gate) | good — explores only when uncertain | good — commits when confident |

The gate's claim: it gets the best of both. A cheap portfolio picks the best heuristic *per axis*; the gated subject should beat the portfolio's envelope by doing both at once. This is reframe × survival — two axes, one confirmed mechanism, grounded in claims 1 + the G9/G10 coupling.

## 2. Arms (temperature is the only difference; all baseline-policy, no organ)

```text
EXPLORER : gate off, modulate off, base_temperature = 2.0  (broad sampling always)
EXPLOITER: gate off, modulate off, base_temperature = 0.05 (near-greedy always)
GATED    : confidence gate on {gate_kappa=0.5, gate_temp_floor=0.1} (adaptive)
```

Env: `StructuredRegimeEnv(period=P)` (recurring shifts = reframe demand) with the agent on a **tight `ViabilityCore`** so reward intake is load-bearing (survival demand). Reward feeds budget via `Agent.step`; death at `budget ≤ 0`.

## 3. Calibration (frozen before r-final; env-validity only, mechanisms untouched)

Sweep `{budget B0, metabolic_cost m}` on **disjoint seeds 1000..1009** to find an env where the **validity precondition** holds: EXPLORER is genuinely good at regret but dies/survives-poorly, and EXPLOITER is genuinely good at survival but has high post-shift regret. If no such cell exists, the survival axis is not separable here and the probe reports that (env-validity finding, not a mechanism result). Freeze the selected `{B0, m, P}` here before r-final. Env-validity revisions are logged per ENGINEERING.md §4 item 2; mechanisms/criteria are never touched.

## 4. Pre-registered decision rule (frozen; ENGINEERING.md §4 items 5–6)

- **r-final seeds 1010..1039** (30), disjoint from calibration and every prior run.
- **Candidate pre-specified**: GATED. Metrics: post-shift regret area (window=15, survivors only) and survival steps (capped at STEPS).
- Report **effect size + bootstrap 95% CI**, not p alone.

| check | requirement (GATED Pareto-dominates the {EXPLORER, EXPLOITER} portfolio) |
|---|---|
| **D-1** gate conserves better than the explorer | GATED survival > EXPLORER survival on ≥21/30 & Wilcoxon p<0.05 |
| **D-2** gate adapts better than the exploiter | GATED regret < EXPLOITER regret on ≥21/30 & Wilcoxon p<0.05 |
| **D-3** no regression on the other axis | GATED regret not significantly worse than EXPLORER **and** GATED survival not significantly worse than EXPLOITER (bootstrap CI of each gap excludes a material loss) |
| validity | EXPLORER low-regret & EXPLOITER high-survival individually confirmed (else env rigged/uninformative) |
| C6/C7 | deterministic tests: gate reads only the subject's model; forbidden/pause dominate |

**Verdict mapping (informs whether to revive G11; the freeze stays founder-reserved):**

- **GREEN** (D-1 & D-2 & D-3 & validity): survival is a genuine second winning axis served by the gate → recommend founder freeze a 2-axis G11 (reframe × survival).
- **AMBER** (D-1 or D-2 only): partial; the gate wins one extra axis but not jointly → report, founder decides.
- **RED** (neither, or validity fails): no separable second axis here → ADR-0027's consolidation stands.

## 5. Implementation

| file | role |
|---|---|
| `experiments/survival_axis_c1.py` | calibrate (1000..1009) + r-final (1010..1039); arms EXPLORER/EXPLOITER/GATED; regret + survival, effect sizes + bootstrap CI |
| `tests/test_survival_axis_c1.py` | determinism + C6/C7 guards + arm-construction (temperature wiring) |

## 6. Disposition

A de-risk is informative in every outcome; **no arm is retuned after seeing results** (only env-validity `{B0,m,P}` may be calibrated, before r-final). The verdict feeds the G11 revival question and is recorded in §7 + ROADMAP after the run.
