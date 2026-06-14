# Subject-side belief-to-action coupling - the program's decisive positive result

- Status: **Consolidated / archival** (founder-directed G10 consolidation, 2026-06-14).
- Scope: object-layer prototype (`autonomous-agent-core`). Continues RR-0005 (G0-G5 synthesis); authoritative source for the G7-G10 arc and the post-G10 de-risks.
- Authoritative ADRs: ADR-0020/G7, ADR-0021 (spectrum/ablation), ADR-0022/G8, ADR-0023/G9, ADR-0024/G10, ADR-0026/C3, ADR-0027 (consolidation), ADR-0028 (survival-axis de-risk), ADR-0029 (stationary risk-axis de-risk).

## 1. The result in one paragraph

For the first time in the G0-G10 falsification program, a mechanism **decisively beats the cheap baseline**: a **subject-side, C6-preserving confidence gate** on the policy's exploration temperature cuts post-shift regret by **40.1%** vs the cheap reset on fresh seeds (G10, 30/30 seeds, p<1e-6, bootstrap 95% CI [457, 563]). The win is not a smarter organ (those hit an ~8-13% belief-only ceiling, G7/G8); it is the subject translating a confident belief into a sharp action - the **belief-to-action coupling** the program had been missing. Three follow-up de-risks (C3 endogeny, ADR-0028 survival, ADR-0029 stationary risk) then showed this is **one lever, not a multi-axis signature**: everything that looked like an independent second axis was either dead (idle), a shadow of the first (survival ~= adaptation speed), or not served by the gate at all (risk calibration). The honest end state: **one robust decisive win, consolidated.**

## 2. The arc

| phase | finding |
|---|---|
| G0-G5 (RR-0005) | directed cognition / learned priors lose to cheap baselines in structure-free envs - "cheap wins" |
| G6a | first crack: a learned prior beats cheap reset when exploitable structure exists |
| G7 / G8 | belief-only organs (Bayesian O4, ensemble O5) beat cheap reset only modestly (~8-13%) and per-seed-fragilely |
| ADR-0021 ablation | the organ win is carried by honest Bayesian accumulation, not active cleverness |
| G9 | discovery: residual post-shift regret is policy-exploration stochasticity, which C6 forbids an organ from touching; P0 gate-alone wins decisively, but G9 is formally NOT MET because the preregistered candidate was P4 (gate+organ) |
| G10 | confirmation: P0 re-run on fresh seeds 800..829 as the prespecified candidate - 40.1% reduction vs A1, 30/30, p<1e-6, MET |
| C3 / survival / risk | de-risks for a second axis: endogeny RED; survival RED as a shadow of reframe/adaptation speed; stationary risk RED with cheap broad exploration winning |

The narrative correction this forces: the slogan from RR-0005 ("cheap baselines win") is **scope-limited to belief acquisition** (exploration, learning, organ priors). On belief-to-action translation (the policy's commitment under confidence), the subject **decisively beats cheap**. The baseline-workspace paper `paper-cheap-baselines-win-safety-substrate-holds.md` predates G9/G10 and should carry this exception.

## 3. The mechanism (C6-preserving)

A confidence gate inside `PolicySelector` collapses the softmax temperature toward a floor as the subject's **own** belief confidence rises, and re-inflates it when post-shift surprise re-inflates uncertainty:

```text
gap  = mu[best] - mu[second]                 # leader separation
u    = uncertainty[best]
conf = clip(gap / (kappa*u + eps), 0, 1)     # high when leader is separated and certain
temperature = temp_floor + (1-conf) * (base_temperature + explore_drive - temp_floor)
```

Frozen params (G9 calibration, disjoint seeds 700..719): `gate_kappa=0.5`, `gate_temp_floor=0.1`.

- **C6 preserved.** Confidence is read from the subject's own `ActionOutcomeModel`. No organ enters the control path; the founder-reserved organ-to-action lever is not used. Organs remain belief-only.
- **C7 preserved.** The gated temperature is still inside the policy; forbidden actions keep weight 0; pause/tighten dominate every path. Guarded by deterministic tests.

## 4. Evidence (G10 r-final, seeds 800..829)

| arm | mean post-shift regret area |
|---|---:|
| A0 baseline + none | 1304.7 |
| A1 baseline + O1 cheap reset | 1268.6 |
| **P0 gated policy + none** | **759.8** |

All four G10 criteria PASS: decisive margin (<=0.8*A1), P0<A0 30/30 and P0<A1 30/30 (p<1e-6 each), effect size 40.1% with bootstrap 95% CI [457, 563]. C6/C7 guard tests pass.

**Robustness (survival-axis side-finding, ADR-0028):** the gate also beats a greedy baseline on post-shift regret under tight metabolic budget (1.048 vs 1.613, 30/30, p<1e-6), so the win survives a stronger baseline and a survival constraint. This is not promoted into a second-axis result because the validity check showed survival and regret are not independent.

## 5. What did not generalize - one lever, not a multi-axis signature

The route-C ambition was a system-level vector signature (RR-0001 section 9): the integrated subject jointly dominating a cheap portfolio across several demand axes. Three de-risks falsified the multi-axis premise:

- **C3 (endogeny / idle-productivity), RED.** Directed idle (`IdleDrives`) is statistically indistinguishable from random and from no-drive idle (1.69 vs 1.68 vs 1.70). Idle is belief acquisition, where cheap is enough.
- **Survival axis (ADR-0028), RED.** The gate Pareto-dominates both cheap arms on regret and budget, but the validity check failed: regret and budget are correlated, both driven by adaptation speed. Survival is a shadow of reframe, not an independent demand.
- **Stationary risk axis (ADR-0029), RED.** With no regime shift, the gate has no independent risk-aversion: the cheap broad explorer survives best (1814 steps vs GATED 1313), and GATED beats the best cheap arm in only 2/30 seeds. The gate keys on leader confidence, not variance diversification.

**Conclusion:** the program has exactly **one** confirmed lever - confidence-calibrated belief-to-action coupling - and it manifests where adaptation speed matters. There is no separable second axis among the natural candidates tried (endogeny / survival / risk), so a multi-axis G11 would collapse to "the reframe axis wins" (= G10). G11/C1 is parked/closed unless a new founder-level reset ADR first proves a genuinely independent winning axis. G10 is the consolidated decisive result.

## 6. Relation to the four claims

| claim | status after G10 and de-risks |
|---|---|
| 1 viability/stake | ablation-validated (P2/G3); load-bearing in the survival-axis env |
| 2 relevance realization | partially supported, hard-stopped (RR-0005) |
| 3 corrigibility (C7) | demonstrated + ISO-hardened; undiminished under the gate |
| 4 organ-not-subject (C6) | structural; preserved by G9/G10 - the win is subject-side, no organ in control |

G10 adds a narrower positive claim the program can stand behind: **a stake-grounded, corrigible, organ-not-subject agent can decisively beat cheap baselines via subject-side belief-to-action coupling, on the adaptation axis, without relaxing C6/C7.**

## 7. Methodological contributions

- **Statistical-power norm** (ENGINEERING.md section 4 items 5-6): preregistered MDE + sample size; underpowered NOT MET = inconclusive, not falsification; effect size + bootstrap CI mandatory; candidate prespecification with fresh-seed confirmation for any post-hoc winner.
- **De-risk-before-build discipline**: cheap probes (C3, survival, risk) settle whether an expensive gate is worth freezing before building it.
- Pre-registered gates + r-final anti-seed-shopping + calibration-frozen strong baselines + negatives-as-first-class (carried from RR-0005).

## 8. Open questions / next

- **Independent second axis**: closed for the natural candidates tried. Endogeny, survival, and stationary risk all returned RED. Any revival of G11 needs a new founder-level reset ADR and a fresh independent vs-cheap-baseline winning axis, not a retune of these probes.
- **P5 deployment projection**: harvest validated claims 1/3/4 plus the G10 coupling result into the enterprise OS (separate landing-feasibility memo; cross-repo, founder-gated).

## 9. Reproduction

```bash
PYTHONPATH=src python -m experiments.confidence_gated_g10     # G10: P0 decisive win
PYTHONPATH=src python -m experiments.idle_productivity_c3     # C3: endogeny RED
PYTHONPATH=src python -m experiments.survival_axis_c1         # survival: RED (shadow)
PYTHONPATH=src python -m experiments.risk_calibration_c1      # risk: RED (cheap broad explorer wins)
PYTHONPATH=src python -m unittest discover -s tests           # full suite green
```
