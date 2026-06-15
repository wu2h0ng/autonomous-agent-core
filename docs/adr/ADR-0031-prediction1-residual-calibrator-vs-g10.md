# ADR-0031: PREDICTION 1 — residual self-calibrator vs the frozen G10 gate (a falsification attempt on RR-0019 Claim 1/3)

- Status: **Proposed** (agent draft per ADR-0003; **founder acceptance required before r-final** — this gate can wound a core claim, see §7).
- Date: 2026-06-14
- Deciders: founder (reserved: accepting a pre-registered gate whose decisive outcome wounds Claim 1/3 and the C6-orthogonality narrative — AGENTS.md §5). Agent drafts and runs once accepted.
- Scope: P6/theory line. Tests `RR-0019` **[PREDICTION 1]**. One additive, frozen, subject-side calibrator inside `PolicySelector`; the G9/G10 confidence gate stays frozen. No LLM, no spend, no new dependency, no cross-repo import, no business semantics.
- Predecessors: ADR-0023/G9, ADR-0024/G10, ADR-0030 (completeness), and `../research/RR-0019-channel-decomposition-principle.md` §5 PREDICTION 1, §6 admission screen.

## 1. Context — why this experiment, and why it is inverted

RR-0019 reorganises the G0–G10 corpus under one channel decomposition `R = R_B + R_K`
and makes a sharp, falsifiable claim:

- **Claim 1 (belief-channel ceiling):** any mechanism confined to channel `B`
  (writes only `μ` / `u`) can reduce only `R_B`, whose floor `R_B^min` the cheap
  reset already nearly saturates — so its margin is bounded by the observed
  ~8–13% belief-side residual and **cannot touch `R_K`**.
- **Claim 3 (corrigibility–performance orthogonality):** the decisive lever lives
  in channel `K`, which C6 confines untrusted advice *out of*; safety-by-confinement
  is therefore free on the margin that matters.

**[PREDICTION 1]** names the single most dangerous belief-side mechanism the program
has not yet run: `verify()` / residual self-calibration (predict → observe → residual
→ recalibrate `u`). The principle predicts it is a **channel-`B` mechanism** that, at
most, **sharpens `conf`** and thereby improves the *existing* G10 `K`-lever — it must
**not** open an independent decisive axis. RR-0019 §5 pre-commits the falsifier:

> *if a frozen residual-calibrator run beats G10's frozen gate by a decisive,
> channel-independent margin on fresh seeds, Claim 1/3 are wounded.*

This ADR is therefore an **inverted gate**: unlike G9/G10 (where "candidate beats
baseline" = MET = good), here the theory **predicts the candidate does NOT decisively
beat the incumbent gate**. The experiment's whole purpose is to *try to falsify* the
program's first original principle. A theory contributor invites the attack first
(RR-0019 §8).

## 2. The mechanism under test (frozen, subject-side, C6-safe)

A **residual self-calibrator**: an additive, deterministic, auditable function that
lives inside the subject and recalibrates per-action uncertainty `u` from realised
prediction residuals. Per RR-0019 §6 it is admissible **only** as a subject-side
function whose output feeds the subject's own belief — **never** an external organ
writing a control signal.

```text
For the chosen action a at each step:
  residual_a   = |observed_reward - model.mu[a]|              # predict → observe
  ewma_res[a] ← (1-λ)·ewma_res[a] + λ·residual_a              # frozen λ
  # recalibrate the subject's own uncertainty toward the empirical residual:
  model.uncertainty[a] ← (1-η)·model.uncertainty[a] + η·ewma_res[a]   # frozen η
```

The recalibrated `u` then enters, unchanged, the two places the subject already uses
it: (i) the score `s_a = w_p·μ_a + w_e·u_a` (belief channel `B`), and (ii) the gate's
confidence `conf = clip(gap/(κ·u_best+ε), 0, 1)` (the `B → K` input). By construction
it writes only `u`: **it is a channel-`B` mechanism by RR-0019's own table.** That is
precisely why Claim 1 predicts it cannot win a decisive independent margin.

- Implementation surface: a frozen `ResidualCalibrator` (new `src/aac/residual_calibrator.py`),
  wired into the subject's update path; `PolicySelector` and the frozen gate
  `{gate_kappa=0.5, gate_temp_floor=0.1}` are **unchanged**.
- C6 invariant (deterministic unit test, gating): the calibrator reads only the
  subject's own `(reward, μ, u)`; no organ value enters it; it never touches
  `τ`, `w_e`, the forbidden set, the shell, or the audit log.

## 3. Arms (candidate pre-specified; incumbent is P0, not a cheap baseline)

Metric = post-shift regret area on `StructuredRegimeEnv`, identical harness to
G7/G9/G10 (`_g7_common`, STEPS=2000, WINDOW=15, N_ACTIONS=8).

```text
A0      = baseline policy + none                          (bitter-lesson guard)
A1      = baseline policy + O1 cheap reset                (the standing cheap baseline)
P0      = frozen G10 gate + none                          (THE INCUMBENT — what PRED 1 says can't be beaten on B)
PR      = frozen G10 gate + residual calibrator           (THE PRE-SPECIFIED CANDIDATE)
PR-B    = baseline policy  + residual calibrator (no gate) (CHARACTERISATION: the calibrator's pure channel-B effect)
```

`PR` is the candidate. `P0` (not A1) is the bar it must clear to falsify the theory:
the question is not "does the calibrator beat a cheap reset" (a belief-side win inside
Claim 1's ceiling would be unsurprising) but "does it beat the **already-gated**
incumbent by a margin no belief-channel mechanism should reach." `PR-B` is a diagnostic
that locates the calibrator's isolated channel-`B` effect; Claim 1 predicts
`PR-B` vs `A1` lands inside the ~8–13% belief-ceiling band.

## 4. Statistical pre-registration (ENGINEERING.md §4 items 5–6)

- **Fresh seeds, disjoint from the entire ledger** (0..29, 200..219, 300..319,
  500..519, 600..629, 700..719, 800..829, 900..929, 970..989, 1000..1039, 1100..1129):
  - calibration of the frozen `(λ, η)`: **`1200..1219`** (20 seeds);
  - r-final: **`1300..1329`** (30 seeds), one shot, no rerolls, no seed-shopping.
- **MDE / falsification effect:** δ ≥ 0.20 mean post-shift-regret-area reduction of
  `PR` vs `P0` — the program's standing "decisive" bar (G9/G10). A margin this large
  from a belief-channel mechanism, stacked on the already-saturated gate, is what
  Claim 1 forbids.
- **Power:** the G10 paired effects are very large; at α=0.01, paired one-sided
  Wilcoxon, 30 seeds give power ≈ >0.99 against δ≥0.20. A null result is therefore a
  *powered* null, i.e. real corroboration — not "inconclusive."
- **Reporting:** effect size (median paired reduction) + bootstrap 95% CI for both
  `PR` vs `P0` and `PR-B` vs `A1`, not p alone.
- **Candidate locked:** `PR`. No post-hoc re-nomination of any other arm.

## 5. Two-sided integrity (the crux of a *falsification* run)

§2.5 forbids tuning a mechanism to make a pre-registered gate go **green**. A
falsification attempt has the mirror temptation: tuning the candidate to
*conveniently fail*, i.e. shipping a strawman calibrator that loses and then declaring
the theory "survived." **Both are violations.** Therefore:

- `(λ, η)` are frozen on the disjoint calibration seeds `1200..1219` by selecting the
  configuration that **maximises** the calibrator's standalone benefit (`PR-B` vs `A1`),
  so the candidate is the *strongest* belief-side calibrator we can build — not a foil.
  This selection is recorded in §7 (frozen params) before r-final.
- After freezing: no change to the calibrator, the gate, the arms, the seeds, or the
  criteria, in either direction, for any reason. A miss is recorded as a *powered*
  corroboration; a hit is escalated (§7). The non-tuning self-declaration goes in the PR.
- This ADR's pre-registration is to be **hash-frozen** before r-final via the
  `prereg` workflow run type (see `ai-agent-engineering-workflow/docs/preregistration-run-type.md`),
  so "the mechanism that ran = the mechanism that was registered" is mechanically
  verifiable, not a promise.

## 6. Preregistered outcomes (one shot, seeds 1300..1329)

| outcome | condition | disposition |
|---|---|---|
| **PRED1-HOLDS** (theory corroborated, *not* proven) | `mean(PR) > 0.80·mean(P0)` — no decisive margin over the incumbent gate; **and** `PR-B` vs `A1` falls within the ≤~15% belief-ceiling band | RR-0019 Claim 1/3 survive this attack. Record `PR-B`'s measured margin as the calibrator's sharpening effect. Per RR-0019 §6 the calibrator is admissible thereafter **only** as a G10 gate-sharpener (frozen, subject-side, feeding `conf`), never as a second axis. Agent may dispose. |
| **PRED1-FALSIFIED** (Claim 1/3 wounded) | `mean(PR) ≤ 0.80·mean(P0)` on ≥27/30 seeds, Wilcoxon one-sided p<0.01, bootstrap CI lower bound > 0 — a decisive, replicated margin of the calibrator **over the already-gated incumbent** | **Founder-reserved disposition** (AGENTS.md §5). A belief-channel mechanism reaching a decisive margin beyond the belief ceiling contradicts Claim 1 and re-opens the second-axis question. Do **not** self-dispose, do **not** retune; escalate with the full result + `PR-B` attribution. |
| **GREY** (sub-decisive positive margin) | `0 < (1 − mean(PR)/mean(P0)) < 0.20` | PRED1-HOLDS by the letter (gate-sharpener within bounds), **but** report the margin and the `PR-B` attribution to founder as a calibration of "how much conf-sharpening buys"; feeds RR-0019 §3 Claim 2 quantification. Agent may dispose with the note flagged. |
| **INCONCLUSIVE** | power precondition not met (it is met by design; this row exists only if the harness/seed assumptions break) | Not a falsification and not a corroboration. Re-examine harness validity (env too easy/hard) per §2.5 — **mechanism stays frozen**. |

C6/C7 guards (gating, deterministic, independent of the regret outcome):

| criterion | requirement |
|---|---|
| PRED1-C6 organ-not-subject preserved | calibrator reads only the subject's own `(reward, μ, u)`; no organ → `μ`/`u`/`τ`/`w_e`/action/shell surface; the gate still reads only `ActionOutcomeModel` |
| PRED1-C7 corrigibility undiminished | forbidden stays weight-0; pause/tighten dominate the calibrated+gated policy |

## 7. Frozen params (filled at freeze time, before r-final)

```text
lambda (residual EWMA)      = TBD  (frozen on seeds 1200..1219, max PR-B benefit)
eta    (u recalibration)    = TBD  (frozen on seeds 1200..1219, max PR-B benefit)
gate (unchanged)            = {gate_kappa: 0.5, gate_temp_floor: 0.1}
base_temperature            = 0.3
prereg lock hash            = TBD  (prereg freeze, before first r-final run)
```

## 8. Implementation (contract-first; gate untouched)

| file | change |
|---|---|
| `src/aac/residual_calibrator.py` | **new** — frozen `ResidualCalibrator(λ, η)`; pure-stdlib; subject-side; recalibrates `u` from residuals |
| `src/aac/agent.py` | additive, default-off wiring of the calibrator into the subject update path; default behaviour unchanged |
| `src/aac/policy.py` | **none** — frozen `{gate_kappa=0.5, gate_temp_floor=0.1}` gate reused as-is |
| `experiments/prediction1_residual_calibrator.py` | calibration on 1200..1219, r-final arms A0/A1/P0/PR/PR-B on 1300..1329, effect sizes + bootstrap CIs, emit `result.json` embedding the prereg lock hash |
| `tests/test_residual_calibrator.py` | deterministic recalibration math + PRED1-C6/C7 guards |
| `docs/adr/ADR-0031-prediction1-residual-calibrator-vs-g10.md` | this record |

## 9. Consequences

- **On PRED1-HOLDS:** RR-0019 graduates from "draft for scrutiny" to "survived its
  own sharpest pre-registered attack." This is the first *emergence* test of the
  controlled research loop: the principle predicted a powered null in advance and the
  prediction held. The calibrator is retained only as a G10 sharpener.
- **On PRED1-FALSIFIED:** the channel-decomposition principle is wounded at Claim 1/3;
  the second-axis hunt re-opens under founder-level reset, and CURRENT_STATE's
  "single robust lever" disposition is revisited. Either way the result is published
  with equal weight (§2.5; ENGINEERING.md §4 item 3).
- **PROJECT_PLAN / CURRENT_STATE / RR-0019 update on r-final**, regardless of outcome.

Reproduce (after acceptance + freeze): `PYTHONPATH=src python -m experiments.prediction1_residual_calibrator`.
