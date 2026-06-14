# ADR-0030: G10 completeness check — does the P0 subject-side win survive the empirical traps?

- Status: **Accepted; COMPLETENESS PASS (2026-06-14, see §8).** P0 survives every flip-the-conclusion
  trap — beats the strongest fixed-low-temperature baseline (T1), transfers to real-stake survival (T3),
  wins on a structure-free env (T5b), robust across the spectrum (T5a). First *trap-complete* decisive
  win; corroborates ADR-0024/G10 rather than undercutting it.
- Date: 2026-06-14
- Scope: P4.x line; **pure measurement + one additive `base_temperature` constructor arg** on the
  frozen G9 confidence gate. No LLM, no spend, no new dependency, no cross-repo, no gate-mechanism change.
- Branch: isolated worktree `feat/g10-completeness`, forked from the G9 tip `bb65121` (does not inherit
  the concurrent `feat/p6-consolidate-g10` line). ADR number 0030 reserved globally (0024–0029 are the
  concurrent line's).
- Predecessor: ADR-0023/G9 (P0 gate-alone decisive discovery) and the concurrent **ADR-0024/G10** which
  judged MET via a **fresh-seed re-confirmation only**.

## 1. Why this is not a re-confirmation

ADR-0024/G10 confirmed P0 replicates on fresh seeds (−40.1%, 30/30). That rules out one trap (**seed
artifact**) and the corrigibility/no-organ guards — but it does **not** rule out the traps that could
make the −40% misleading. The whole research line (ADR-0024→0029, and a P5 landing memo) now rests on
"P0 is a real new mechanism." This ADR stress-tests that foundation: a thin re-confirmation is forbidden
(founder directive); the goal is **completeness** — falsify every alternative explanation, or the win
does not stand.

## 2. One mechanism change (additive, not a gate change)

`Agent` and `PolicySelector` gain a `base_temperature` constructor arg (default 0.3 = current behaviour,
bit-identical). This is required only to build the **B-temp** control arm (a fixed-low-temperature
baseline policy). The G9 confidence gate `{gate_kappa=0.5, gate_temp_floor=0.1}` stays frozen exactly.

## 3. The trap matrix (pre-registered; each row is a falsifiable sub-criterion)

| # | Trap (if true, the P0 win is misleading) | Control / metric | Pass criterion |
|---|---|---|---|
| **T1** | **Adaptivity is a red herring; a fixed low temperature suffices** (the baseline just explores too much) | **B-temp** arm: baseline policy + fixed low `base_temperature` (frozen via calib), no gate, no organ | **P0 < B-temp on ≥27/30 & Wilcoxon p<0.01** |
| **T2** | **Metric spillover**: the gate moves regret out of the 15-step window | report per arm (a) window area, (b) whole-run mean regret, (c) total reward intake | P0 beats A0 & B-temp on all three (directions agree) |
| **T3** | **Stake decoupling (deepest)**: −40% lives only on the `budget=1e9, cost=0` toy metric | real-stake setting: finite budget + positive `metabolic_cost`; metric = **survival steps** | **P0 survives longer than A0 & B-temp, Wilcoxon p<0.05** |
| **T5b** | **Structure theft**: the gate secretly exploits the recurring regime library | run the same arms on **`StalenessEnv` (no transferable structure)** | report P0 vs A0 advantage + p; **P0 winning there ⇒ general policy fix (not theft)**; not winning ⇒ theft flag |
| **T5a** | **Single-point result** | spectrum `n_regimes × noise` (P0 vs A1 vs B-temp) | phase-boundary map reported |
| **T6** | **Greediness erodes corrigibility** | tighten the high-conf argmax action | deterministic guard: forbidden stays weight-0; pause/tighten dominate |
| **T7** | **Signal theft** (reads the env shift) | static assertion | gate reads only the subject's `ActionOutcomeModel`; no `just_shifted/regime_index` |

Margin sanity (carried from G9/G10): `mean(P0) ≤ 0.8·mean(A1)` on the r-final seeds.

## 4. Seeds (disjoint from every prior run, incl. the concurrent line's 800..829)

- B-temp `base_temperature` calibration: **970..989** (pick the fixed temperature with the lowest mean
  area; this gives B-temp its *strongest* config — no straw man).
- r-final (T1/T2/T3/T5b): **1000..1029** (30 seeds), one shot, no rerolls/seed-shopping/retune.
- spectrum (T5a): **1000..1009**.

## 5. Completeness verdict

**P0 stands as a real new algorithm only if ALL of T1, T3, T5b pass** (plus the margin and T6/T7
guards, with T2 directions agreeing). These three are the ones that can flip the conclusion:
- **T1 fail** ⇒ the win is "less exploration", the gate's adaptivity is a red herring → the honest
  headline becomes "the baseline policy was mis-tuned" (a 6th bitter-lesson variant). **This would
  undercut ADR-0024/G10's MET framing and the p6 line built on it.**
- **T3 fail** ⇒ the −40% does not transfer to the essential viability variable; it is a toy-metric
  artifact (violates stake-first, §2.6).
- **T5b**: either direction is information and is recorded as-is.

## 6. NOT MET / partial disposition (pre-committed)

Record the exact failing trap; do not retune the gate or B-temp to rescue it. If T1 or T3 fails, the
honest disposition is escalated to founder because it bears on whether ADR-0024/G10 and the downstream
p6 consolidation rest on a real mechanism. T5a/T5b/T2 are characterisation, not pass/fail blockers.

## 7. Implementation files

| file | change |
|---|---|
| `src/aac/policy.py`, `src/aac/agent.py` | add additive `base_temperature` arg (default 0.3); gate unchanged |
| `experiments/completeness_g10.py` | settings A (proxy + T2 metrics), B (stake survival), C (StalenessEnv), D (spectrum); arms A0/A1/B-temp/P0 |
| `tests/test_completeness_g10.py` | `base_temperature` wiring + B-temp construction + reuse C6/C7 guards |
| `docs/adr/ADR-0030-...md` | this preregistration + frozen B-temp + results |

## 8. Status log

- 2026-06-14: ADR drafted before B-temp calibration and before any r-final. Trap matrix §3 frozen.
- 2026-06-14: `base_temperature` additive arg added (`agent.py`/`policy.py`, default 0.3, gate-off
  bit-identical, 367 suite green). B-temp calibration on disjoint seeds 970..989: FROZEN
  `base_temperature=0.03` (strongest fixed-low-temp config among 0.01..0.3, area 1262.7).
- 2026-06-14: Completeness r-final, seeds 1000..1029 (+ spectrum 1000..1009):

**Setting A (proxy):**

| arm | window-area | whole-run mean regret | total reward |
|---|---:|---:|---:|
| A0 baseline | 1329.2 | 1.6233 | 3657.2 |
| A1 cheap reset | 1272.6 | 1.5305 | 3842.9 |
| B-temp fixed-low (0.03) | 1292.9 | 1.5216 | 3860.5 |
| **P0 gated** | **739.8** | **0.7122** | **5479.4** |

| trap | result |
|---|---|
| margin mean(P0) ≤ 0.8·A1 | 739.8 ≤ 1018.1 PASS |
| **T1 P0 < B-temp** | **30/30, p<1e-6 PASS** (adaptivity is real; fixed-low-temp can't re-explore post-shift) |
| **T2 metric spillover** | P0 best on whole-run mean regret AND total reward PASS |
| sanity | P0<A0 30/30, P0<A1 30/30; effect vs A1 −532.8, bootstrap 95% CI [483.3, 586.2] |
| **T3 real-stake survival** (budget 60, cost 2.0) | P0 survival mean 1734.8 vs A0 1245.3 (p=8e-4) and B-temp 1482.6 (p=0.024) **PASS** |
| **T5b unstructured (StalenessEnv)** | P0 −36.4% vs A0, p<1e-6 → **GENERAL FIX (not structure theft)** |
| T5a spectrum (4×4) | P0 advantage +0.29…+0.70 over A1/B-temp, all 16 conditions, no phase flip |
| T6/T7 corrigibility + no-signal | `tests/test_confidence_gated_policy.py` + `test_completeness_g10.py` PASS |

**COMPLETENESS: PASS.** P0 (confidence-gated policy, no organ, C6-preserving) survives every
flip-the-conclusion trap: it decisively beats the **strongest fixed-low-temperature baseline** (so the
adaptivity is real, not just less exploration), the win shows up on **whole-run regret and total
reward** (not a windowed-metric artifact), it **transfers to real survival under metabolic cost**
(stake-first, §2.6), it **wins on a structure-free environment** (a general policy fix, not regime-
structure theft), and it is **robust across the n_regimes×noise spectrum**. This is the first
*trap-complete* decisive positive in the G0–G10 program, and it **corroborates** the concurrent
ADR-0024/G10 MET rather than undercutting it: the subject-side belief→action coupling is a genuine
mechanism. The deeper lesson stands sharpened — the G6a–G8 belief-only organ line optimised belief
*quality*; the real bottleneck was the belief→action *coupling* in the policy, and a cheap
C6-preserving subject-side fix captures it.

Reproduce: `PYTHONPATH=src python -m experiments.completeness_g10 [calibrate]`.
