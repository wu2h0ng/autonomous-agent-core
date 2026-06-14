# ADR-0026: C3 idle-productivity de-risk probe — does the endogeny axis carry a directed signal?

- Status: **Accepted (pre-registration; founder-directed 2026-06-14 "接着起 C3 de-risk"). Decision rule §4 frozen before any run. De-risk probe informing ADR-0025/G11, not a verdict gate.**
- Date: 2026-06-14
- Deciders: founder directed the C3 de-risk (2026-06-14). Agent executes per ADR-0003 (de-risk probe, deterministic, no reserved items) and ADR-0025 §4 (C3 runs before C1).
- Scope: route-C de-risk. Reuses `IdleDrives` (built + audited in P2/ADR-0012), `StructuredRegimeEnv`, `IdleWindowEnv`. No new mechanism, no spend, no LLM, no cross-repo. Does not relax C6/C7.
- Predecessor: ADR-0025 (route C, C3 = de-risk before C1), ADR-0024/G10 (subject-side win confirmed), ADR-0012/G3 (idle-gain criterion **not established** in a *structure-free* env).

## 1. Context — why re-open idle gain, and what is different from G3

G3 (ADR-0012, criterion 2) tested whether directed idle activity lowers post-idle work regret and found it **not established**: in a *structure-free* env (`GridlessSurvival`, i.i.d. random regimes) random idle matched directed idle. The whole P4.x arc then showed why cheap ≈ clever there — *there was no structure for direction to exploit* (G5 structure-free NOT MET → G6a structured MET).

Route C's C1 multi-axis signature proposes to include an **endogeny axis** (闲时生产力). Before building C1, this probe asks the cheap question: **in the structured env where route-C mechanisms actually win, does the integrated subject's idle drive carry a *directed* post-idle gain a reactive baseline cannot fake?** If not, C1 must drop or rescope the endogeny axis.

**Fairness (fixing a G3 confound).** All three arms call `Agent.step` on every step (idle included), so `StructuredRegimeEnv.act` draws exactly one noise sample per step and `force_regime_change` is keyed on the loop step — env randomness (regimes *and* noise) is **identical across arms**. The only variable is the idle action policy. No suspend/`tick` arm (which would diverge the rng).

## 2. Design

- Env: `IdleWindowEnv(StructuredRegimeEnv(period=10**9), work_period=40, idle_period=8)`. Internal auto-shift disabled; a regime shift is **forced at the first idle step of every cycle**, so the following work faces a regime the idle window could have learned.
- Metric: **post-idle work regret** — mean `last_regret` over the first `POST_IDLE_K=10` work steps of each cycle `>=1` (those steps run on the regime learned in the immediately preceding idle window). Lower is better.
- Policy held constant (baseline, no G9 gate) across arms, so the endogeny axis is isolated; C1/G11 will combine the gate and idle.

## 3. Arms (only the idle action policy differs)

```text
DIRECTED : idle_drives = IdleDrives        (probe most-uncertain / stalest action)
RANDOM   : idle_drives = _RandomIdleDrives (uniform-random permitted action)
POLICY   : idle_drives = None              (agent runs its normal policy during idle —
                                            the no-endogenous-drive reactive baseline)
```

## 4. Pre-registered decision rule (frozen before run; ENGINEERING.md §4 items 5–6)

- **Seeds 900..929** (30), disjoint from every prior run (0..29, 200..219, 300..319, 500..519, 600..629, 700..719, 800..829).
- **Candidate pre-specified**: DIRECTED. No post-hoc re-nomination.
- **MDE**: a reliable directional reduction in post-idle regret; with 30 paired seeds, one-sided Wilcoxon at α=0.05 has power ≈0.8 for a moderate paired effect. Report **effect size (mean + median paired reduction) and bootstrap 95% CI**, not p alone.

| check | requirement |
|---|---|
| **C3-A** idle drive beats no-drive | DIRECTED < POLICY on ≥21/30 seeds **and** Wilcoxon one-sided p<0.05 **and** bootstrap 95% CI of mean(POLICY−DIRECTED) lower>0 |
| **C3-B** direction beats random | DIRECTED < RANDOM on ≥21/30 seeds **and** Wilcoxon one-sided p<0.05 |
| C3-C6/C7 | deterministic tests: idle path stays auditable, organs untouched, forbidden/pause dominate |

**Verdict mapping (informs G11/C1, not a MET/NOT-MET gate):**

- **GREEN** (A ✓ & B ✓): endogeny is a directed-cognition win → C1 includes the idle axis with `IdleDrives`.
- **AMBER** (A ✓ & B ✗): idle activity helps but direction does not (G3 pattern persists in structure) → C1 may use "idle activity" but must not claim a directed advantage.
- **RED** (A ✗): idle yields no post-work gain even in structure → **drop the endogeny axis from C1's signature**; rely on reframe / survival / robustness.

## 5. Implementation

| file | role |
|---|---|
| `experiments/idle_productivity_c3.py` | arms DIRECTED/RANDOM/POLICY on the forced-shift idle schedule; effect size + bootstrap CI |
| `tests/test_idle_productivity_c3.py` | determinism + C6/C7 guards (idle audited, no organ surface, forbidden dominates) |

## 6. Disposition

A de-risk is informative in every outcome; **no arm is retuned after seeing results** (ENGINEERING.md §4 item 3). The verdict (§4) feeds ADR-0025/G11's C1 scope and is recorded in §7 + ROADMAP after the run.
