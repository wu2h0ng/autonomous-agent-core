# ADR-0024: G10 — confirm the decisive subject-side win (P0 gate-alone) on fresh seeds

- Status: **Accepted; G10 MET (2026-06-14, see §8) — P0 confirmed on fresh seeds, −40.1% vs cheap reset, 30/30, p<1e-6. Pure confirmatory measurement on the existing frozen confidence gate — no new mechanism.**
- Date: 2026-06-14
- Deciders: founder (sequencing ruling 2026-06-14: lock P0 single-axis first, then generalise to system level via ADR-0025/G11). Agent drafts per ADR-0003 ("按既有 ADR 施工 + 实验有效性").
- Scope: P4.x structured-regime line; **pure measurement** on the already-implemented, gate-off-by-default `PolicySelector` confidence gate from ADR-0023/G9. No LLM, no spend, no new dependency, no cross-repo, no mechanism change.
- Predecessor: ADR-0023/G9 — P0 (gate-alone) = 746.5 vs A0 1361.6 = **−45%, 30/30, p<1e-6**, decisively beating cheap reset A1 (1325.6) and the O4 belief ceiling A4 (1224.3). But G9 NOT MET because the **pre-registered candidate was P4 (gate+organ)**, while the data shows P0 (gate-alone) is the winner and the organ is counterproductive.

## 1. Context — why a fresh-seed confirmation is required, not optional

G9 is a textbook trigger for ENGINEERING.md §4 item 6 (candidate pre-specification / no claiming a post-hoc winner on the same seeds). The decisive P0 result is real in G9's data, but P0 was **not** the pre-registered candidate. Claiming "P0 decisively wins" on the same r-final seeds (0..29) would be HARKing. G10 re-runs the **identical, frozen** mechanism with **P0 as the pre-specified candidate** on **fresh seeds disjoint from every prior run**, so the first decisive win in the program is established cleanly or shown to be a seed artifact.

No mechanism is touched: the confidence gate `{gate_kappa=0.5, gate_temp_floor=0.1}` stays frozen exactly as ADR-0023 §10 fixed it.

## 2. Arms (pre-specified; P0 is THE candidate)

Metric = post-shift regret area on `StructuredRegimeEnv`, identical harness to G7/G9 (`_g7_common`, STEPS=2000, WINDOW=15, N_ACTIONS=8).

```text
A0 = baseline policy + no organ      (bitter-lesson guard)
A1 = baseline policy + O1 cheap reset (the cheap baseline to beat)
P0 = gated policy    + no organ      (THE pre-specified candidate)
```

The organ arms (A4/P4) are **dropped**: G9 established the organ is counterproductive under the gate; re-including it would only re-pose the question G9 already answered. G10 isolates the confirmed subject-side mechanism.

## 3. Statistical pre-registration (ENGINEERING.md §4 items 5–6 — this gate is the norm's first instance)

- **Fresh seeds: `800..829` (30 seeds).** Disjoint from every prior seed set: 0..29 (G7/G8/G9 r-final), 200..219 (G7 calib), 300..319 (O5 exploratory), 500..519 (G8 calib), 600..629 (G8 r-final), 700..719 (G9 calib). One shot, no rerolls, no seed-shopping, no retune.
- **MDE (minimum detectable effect):** δ ≥ 0.20 mean post-shift-regret-area reduction of P0 vs A1 (decisive ambition, matching G9).
- **Power:** G9's observed per-seed effect was P0<A0 30/30 with a ~45% mean reduction — a very large paired effect. At α=0.01, paired one-sided Wilcoxon, the seed count needed for power ≥ 0.8 against δ≥0.20 is well under 30; **30 fresh seeds give power ≈ >0.99**. (Pre-registered statement, not post-hoc.)
- **Reporting:** report **effect size (median paired reduction) + bootstrap 95% CI**, not p alone. A NOT MET is only a valid negative if this design's power held (it does); an underpowered miss would be "inconclusive", not falsification.
- **Candidate locked:** P0. No post-hoc re-nomination of any other arm.

## 4. G10 preregistered gate (r-final seeds 800..829, one shot)

| criterion | requirement |
|---|---|
| G10-1 decisive margin over cheap reset | `mean(P0) ≤ (1 − 0.20) · mean(A1)` |
| G10-2 bitter-lesson guard | `P0 < A0` on ≥ 27/30 seeds **and** Wilcoxon one-sided p < 0.01 |
| G10-3 beats the cheap reset | `P0 < A1` on ≥ 27/30 seeds **and** Wilcoxon one-sided p < 0.01 |
| G10-4 effect size reported | median paired reduction + bootstrap 95% CI reported; CI lower bound exceeds 0 |
| G10-C6 organ-not-subject preserved | deterministic test: gate reads only the subject's `ActionOutcomeModel`; no organ→action/policy/shell surface |
| G10-C7 corrigibility undiminished | deterministic test: forbidden stays weight-0; pause/tighten dominate the gated policy |

G10 is MET only if all six rows pass.

## 5. Implementation (contract-first; reuses frozen mechanism)

| file | change |
|---|---|
| `src/aac/policy.py` | **none** — reuse the frozen `{gate_kappa=0.5, gate_temp_floor=0.1}` gate from ADR-0023 |
| `experiments/confidence_gated_g10.py` | r-final on seeds 800..829, arms A0/A1/P0, reuse `_g7_common`; print effect size + bootstrap CI |
| `tests/test_confidence_gated_g10.py` | C6/C7 guards + deterministic replay (mechanism tests already exist from G9) |

## 6. NOT MET disposition (pre-committed)

If P0 does not replicate the decisive margin on fresh seeds 800..829, the G9 P0 result was a seed artifact → record honestly per ENGINEERING.md §4 item 3, do not retune. Route C (ADR-0025/G11) would then lose its single-axis foundation and must be re-scoped before the C1 build.

## 7. Consequences

- **On MET**: the program has its first *confirmed* decisive win — subject-side belief→action coupling, C6-preserving, beating cheap baselines on a single axis. This becomes the foundation ADR-0025/G11 generalises to the multi-axis system-level signature.
- **Coordination note**: the confidence-gate mechanism is owned by the concurrent `feat/g9-confidence-gated-policy` line (committed `bb65121`/`9c0d6c3`). G10 adds only an experiment + guard tests on the frozen gate; it does not modify `policy.py`. Branch/merge coordination is a founder-hands item (this work and the G9 line share the orchestrator surface).
- **PROJECT_PLAN update on first run**: add P6.1/G10 result to §5 and ROADMAP after r-final.

## 8. Result (2026-06-14, r-final seeds 800..829) — G10 MET

Pure confirmatory run against the frozen G9 gate `{gate_kappa=0.5, gate_temp_floor=0.1}`, P0 the pre-specified candidate. Full suite 367 tests green.

| arm | mean post-shift regret area, seeds 800..829 |
|---|---:|
| A0 baseline + none | 1304.7 |
| A1 baseline + O1 cheap reset | 1268.6 |
| **P0 gated policy + none** | **759.8** |

| criterion | result |
|---|---|
| G10-1 mean(P0) ≤ 0.8·A1 | 759.8 ≤ 1014.9 PASS |
| G10-2 P0<A0 ≥27/30 & Wilcoxon p<0.01 | 30/30, p<1e-6 PASS |
| G10-3 P0<A1 ≥27/30 & Wilcoxon p<0.01 | 30/30, p<1e-6 PASS |
| G10-4 effect size + bootstrap 95% CI lower>0 | mean reduction 508.8, median 499.4, −40.1%, CI [457.0, 562.9] PASS |
| G10-C6/C7 | unit tests PASS |

**G10: MET.** The decisive subject-side win replicates cleanly on fresh seeds — the G9 P0 result was **not** a seed artifact. P0 (confidence-gated policy, no organ, C6-preserving) beats the cheap reset by **40.1%** (30/30, p<1e-6, bootstrap 95% CI [457, 563]). This is the **first MET decisive gate in the G0–G10 program** and the first break of the bitter-lesson pattern, confirmed under ENGINEERING.md §4 items 5–6 (fresh seeds, pre-specified candidate, effect size + CI). Foundation for ADR-0025/G11 (system-level generalisation).

Reproduce: `PYTHONPATH=src python -m experiments.confidence_gated_g10`.
