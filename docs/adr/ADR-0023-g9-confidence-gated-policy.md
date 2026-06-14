# ADR-0023: G9 confidence-gated policy temperature — the C6-preserving test of the post-shift ceiling

- Status: **Accepted (preregistration; founder-approved 2026-06-14). Implementation in progress; gate criteria §6 frozen, not to be moved.**
- Date: 2026-06-14
- Scope: P4.x structured-regime prototype line; **subject-side policy mechanism**, no LLM, no spend, no new dependency, no cross-repo. **Does NOT relax C6.**
- Predecessor: ADR-0020 (G7 NOT MET), ADR-0022 (G8 NOT MET), RR-0005 G7/G8 addendum (bounded belief-only advantage).
- Branch note: stacked on `feat/g7-latent-regime-organ` (PR #1); reuses O1/O4, `StructuredRegimeEnv`, and the `_g7_common` harness. Rebase onto `main` after PR #1 merges.

## 1. Context — the headroom the organ cannot reach

G7/G8 established that a belief-only organ (O4 Bayesian, O5 ensemble) beats the cheap reset only
modestly (~8–13%) and per-seed-fragilely. The ablation + spectrum localised the unclaimed headroom:
post-shift, O4 **already** sharpens belief (the posterior identifies the regime in a few steps), but
the agent still incurs regret because the **policy keeps exploring** — `PolicySelector` samples at
`temperature = base_temperature + explore_drive`, and the relevance-field `explore_drive` does not
collapse fast/low enough once belief is confident. The residual regret is **policy-exploration
stochasticity**, which C6 forbids an *organ* from touching.

The question G9 isolates: **is that ceiling removable by a *subject-side* mechanism — the policy
gating its own exploration on its own belief confidence — without putting any organ in the control
path?** If yes, we get the decisive win *and keep C6 intact* (the cleanest outcome). If no, the only
remaining lever is genuine C6 relaxation, which stays founder-reserved (§8).

## 2. Decision — confidence-gated temperature (in the policy, i.e. the subject)

Add a confidence gate to `PolicySelector` that collapses the softmax temperature toward a floor as
the agent's **own** belief confidence rises. Confidence is read from the subject's
`ActionOutcomeModel` (mu/uncertainty) — **not** from any organ:

```text
gap  = mu[best] - mu[second_best]            # pragmatic separation of the leader
u    = uncertainty[best]                      # epistemic uncertainty on the leader
conf = clip( gap / (kappa * u + eps), 0, 1 )  # high when leader is well-separated AND certain
temperature = temp_floor + (1 - conf) * (base_temperature + explore_drive - temp_floor)
```

When `conf → 1` the policy becomes near-greedy (exploit the identified regime); when `conf → 0`
(post-shift surprise re-inflates uncertainty) it explores as before. This is the missing
**belief → action coupling**: it lets a confident belief actually translate into a sharp action,
which the current fixed schedule does not. `kappa`, `temp_floor` are frozen via calibration (§3);
`eps` is a fixed small constant.

This is a change to the **subject's policy**, the same category as RelevanceField/AttentionField
evolution — not an organ. It introduces no action/policy/shell surface for any organ.

## 3. C6/C7 boundary (the whole point of this design)

- **C6 (organ-not-subject) is PRESERVED, not relaxed.** Organs (O1/O4) remain belief-only; the
  confidence the policy reads is the subject's own `ActionOutcomeModel`, which the policy already
  owns. No organ gains influence over action selection. This ADR explicitly is **not** the
  reserved "organ → control path" lever (§8).
- **C7 (corrigibility) undiminished.** The gated temperature is still inside `PolicySelector`;
  forbidden actions keep weight 0; `pause`/`tighten` still dominate every path. Guarded by tests.

## 4. Arms (shared subject + env; only the marked slot differs)

Metric = post-shift regret area on `StructuredRegimeEnv`, identical harness to G7 (`_g7_common`,
STEPS=2000, WINDOW=15, N_ACTIONS=8).

```text
A0 = baseline policy  + no organ      (current O0)
A1 = baseline policy  + O1 cheap reset (the cheap baseline)
A4 = baseline policy  + O4            (the belief-only ceiling to break)
P0 = gated policy     + no organ      (the subject-side mechanism ALONE)
P4 = gated policy     + O4            (belief + coupling — the full candidate)
```

`A0` is the bitter-lesson guard for the policy mechanism: `P0` must beat `A0` or the gate does
nothing. `A4` is the ceiling the full candidate `P4` must break to show the headroom was policy-side.

## 5. Calibration protocol (frozen before r-final)

- Calibrate `{kappa, temp_floor}` on **disjoint seeds 700..719** only (never the r-final seeds).
- Finite grid declared in the experiment script before r-final; e.g. `kappa ∈ {0.5,1.0,2.0}`,
  `temp_floor ∈ {0.05,0.1,0.2}`. Select lowest mean **P4** post-shift regret area; freeze into
  `PolicySelector` defaults + the experiment, recorded here before r-final.
- δ target for G9-1: `calib_reduction = 1 - mean_calib(P4)/mean_calib(O1)`;
  `δ = 0.20 if calib_reduction ≥ 0.20 else floor(100*0.80*calib_reduction)/100`. **Ambition is
  decisive (δ ≥ 0.20);** the formula only pins δ *down*, never up, and only before r-final.

## 6. G9 preregistered gate (r-final seeds 0..29, one shot, no rerolls/seed-shopping/retune)

| criterion | requirement |
|---|---|
| G9-1 decisive margin over cheap reset | `mean(P4) ≤ (1 − δ) · mean(O1)` |
| G9-2 breaks the belief-only ceiling | `P4 < A4(O4)` on ≥ 90% seeds **and** Wilcoxon one-sided p < 0.01 |
| G9-3 mechanism isolation (bitter-lesson guard) | `P0 < A0` on ≥ 90% seeds **and** Wilcoxon one-sided p < 0.05 |
| G9-4 significance vs cheap reset | Wilcoxon one-sided P4 vs O1 p < 0.01 |
| G9-C6 organ-not-subject preserved | deterministic test: organs still belief-only; gate reads only the subject's `ActionOutcomeModel`; no organ→action/policy/shell surface added |
| G9-C7 corrigibility undiminished | deterministic test: forbidden stays weight-0; pause/tighten dominate the gated policy |

G9 is MET only if all six rows pass.

## 7. Required tests (deterministic mechanism only; no stochastic e2e pass/fail)

`tests/test_confidence_gated_policy.py`:
- temperature collapses toward `temp_floor` as confidence rises; relaxes when surprise re-inflates uncertainty;
- a well-separated, certain leader yields near-greedy selection; an uncertain belief explores;
- forbidden actions stay weight-0 under the gate; pause/tighten still dominate via `Agent.step`;
- deterministic replay; the gate reads no organ surface.

## 8. NOT MET disposition (pre-committed) + the reserved fallback

- **G9-3 fails (P0 ≈ A0):** "confidence-gating the policy temperature adds nothing over the existing
  relevance-field schedule" — the 6th occurrence of the bitter-lesson pattern. Record; do not retune.
- **G9-1/G9-2 fail despite G9-3:** "the post-shift ceiling is not removable by subject-side
  temperature control at this scale."
- **In either non-MET case, the genuine C6-relaxation lever** (a deterministic organ steering
  temperature / nominating actions = organ into the control path) **remains founder-reserved** and
  requires its own ADR + explicit founder sign-off. It is **not** auto-taken. G9 exists precisely to
  test whether that reserved step is even necessary.

## 9. Implementation files (after this ADR is accepted; contract-first)

| file | change |
|---|---|
| `src/aac/policy.py` | add confidence gate to `PolicySelector` (frozen params; off by default flag so A-arms keep baseline behaviour) |
| `experiments/confidence_gated_g9.py` | calibrate (700..719) + r-final gate (0..29), arms A0/A1/A4/P0/P4, reuse `_g7_common` |
| `tests/test_confidence_gated_policy.py` | mechanism + C6/C7 guards |
| `docs/adr/ADR-0023-...md` | this preregistration + frozen params/results updates |
| `codebase_index.md`, `docs/PROJECT_PLAN.md`, `../docs/research/RR-0005-...md` | after r-final |

## 10. Status log

- 2026-06-14: ADR drafted before any mechanism code, before G9 calibration/r-final. C6 explicitly
  preserved; C6-relaxation held as founder-reserved fallback.
- 2026-06-14: Founder approved the preregistration. Implemented `PolicySelector` confidence gate +
  `Agent` params + `tests/test_confidence_gated_policy.py` (12 tests, gate-off bit-identical; 363
  suite green). Calibration on disjoint seeds 700..719: FROZEN `{gate_kappa=0.5, gate_temp_floor=0.1}`
  (calib A1=1327.8, P4=899.0, reduction 0.323 → delta capped at 0.20).
- 2026-06-14: G9 r-final, seeds 0..29:

| arm | mean post-shift regret area |
|---|---:|
| A0 baseline + none | 1361.6 |
| A1 baseline + O1 cheap reset | 1325.6 |
| A4 baseline + O4 (belief-only ceiling) | 1224.3 |
| **P0 gated policy + none** | **746.5** |
| P4 gated policy + O4 | 893.4 |

| criterion | result |
|---|---|
| G9-1 mean(P4) ≤ 0.8·A1 | 893.4 ≤ 1060.5 PASS |
| G9-2 P4<A4 ≥27/30 & Wilcoxon p<0.01 | 25/30 **FAIL** (p=2.5e-5) |
| G9-3 P0<A0 ≥27/30 & Wilcoxon p<0.05 | 30/30, p<1e-6 PASS |
| G9-4 Wilcoxon P4 vs A1 p<0.01 | p<1e-6 PASS |
| G9-C6/C7 | unit tests PASS |

**G9: NOT MET** (fails G9-2 only). The gate is **not** retuned (§8). But the experiment is a decisive
positive for the underlying question, with a surprise:

1. **The subject-side confidence gate removes the post-shift ceiling decisively, and it is
   C6-preserving.** P0 (gate **alone, no organ**) = 746.5 vs A0 1361.6 = **−45%**, 30/30, p<1e-6 — the
   *passed* G9-3 criterion. P0 also beats the cheap reset A1 and the O4 ceiling A4 by large margins.
   The founder-reserved C6-relaxation lever is therefore **unnecessary**: the decisive win uses no
   organ and does not touch the soundness model.
2. **The belief-only organ is counterproductive under the gate.** P4 (gate + O4) = 893.4 is *worse*
   than P0 = 746.5. O4's post-shift reset re-inflates the leader's uncertainty, keeping the gate's
   confidence low and delaying exploitation — the organ fights the gate. The G7/G8 organ line was
   improving belief *quality*; the real bottleneck was the belief→action *coupling* in the policy.

G9-2 returned FAIL because the gate nominated P4 (gate+organ) as the candidate; the data shows P0
(gate alone) is the winner and the organ hurts. **Next (proposed): ADR-0024 / G10** — a clean
preregistered gate with P0 (gate-alone) as the candidate on **fresh r-final seeds** (disjoint from
0..29 and 700..719), to formally establish the decisive subject-side win without reusing G9's data.
