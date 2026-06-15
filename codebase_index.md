# codebase_index - autonomous-agent-core

> Last updated: 2026-06-15
> Purpose: fast map from current research state to code, tests, experiments, and ADRs.
> First read: `docs/CURRENT_STATE.yaml`.

## Current Snapshot

```yaml
branch: main
stage: P6 consolidated
immediate_next: synthesize ADR-0034/0035 results and request founder direction
tests: 412 OK
```

Do not use older references that say the current stage is P1, P2, P3, or P4. They are historical.

## Source Of Truth

| File | Role |
|---|---|
| `docs/CURRENT_STATE.yaml` | Machine-readable current state, read order, latest tests, active gate |
| `docs/P6-research-synthesis.md` | P6 synthesis package: claim ledger, negative-result map, mechanism lineage, reproducibility appendix, publication outline |
| `docs/PROJECT_PLAN.md` | Human handoff plan and task cards |
| `ROADMAP.md` | Phase ledger and gate sequence |
| `ENGINEERING.md` | Engineering and experiment discipline, especially statistical rules |
| `AGENTS.md` | Agent rules and non-negotiable boundaries |
| `docs/PRD.md` | Four core claims |
| `docs/adr/` | Preregistered decisions and gate results |
| `../docs/research/RR-0001..0005` | Cross-repo research constitution and falsification record |

## Recent ADR Index

| ADR | Status | Meaning |
|---|---|---|
| `ADR-0020-g7-latent-regime-organ.md` | NOT MET | O4 beats O1 but not O2 at required dominance |
| `ADR-0021-p1-spectrum-ablation.md` | Implemented | O4 spectrum/ablation strengthening |
| `ADR-0022-g8-ensemble-regime-organ.md` | NOT MET | O5 ensemble did not improve over O4 |
| `ADR-0023-g9-confidence-gated-policy.md` | Accepted, implemented, formal NOT MET | P0 gate-alone decisive discovery; P4 preregistered candidate failed |
| `ADR-0024-g10-subject-side-win-confirmation.md` | MET | Fresh-seed confirmation of P0; first decisive positive gate |
| `ADR-0025-system-level-autonomy-signature-gate.md` | Route accepted, parked by ADR-0027 | G11 system-level vector gate needs a second independent winning axis |
| `ADR-0026-c3-idle-productivity-de-risk.md` | RED | Endogeny axis has no directed signal; dropped from C1 |
| `ADR-0027-post-c3-route-disposition.md` | Accepted | Consolidate G10; park G11/C1 until another axis wins |
| `ADR-0028-survival-axis-de-risk.md` | RED | Survival-under-cost is not independent; it shadows reframe/adaptation speed |
| `ADR-0029-risk-calibration-axis-de-risk.md` | RED | Stationary risk calibration not improved by the gate; cheap broad explorer wins |
| `ADR-0030-g10-completeness-trap-avoidance.md` | COMPLETENESS PASS | G10/P0 survives fixed-low-temp, metric, real-stake, structure-theft, and spectrum traps |
| `ADR-0031-prediction1-residual-calibrator-vs-g10.md` | PRED1-HOLDS | Residual self-calibrator did not beat frozen G10; RR-0019 Claim 1/3 survived the attack |
| `ADR-0032-frontier-architecture-intake-and-structured-env-route.md` | Accepted | Frontier systems enter only through classified lanes/channels; structured environments are the next admissible experiment family |
| `ADR-0033-hyperagents-dgm-assimilation-boundary.md` | Accepted | HyperAgents/DGM-style systems are external candidate generators only; runtime self-modification remains forbidden |
| `ADR-0034-relevance-aware-g10-theory-test.md` | Completed | Full-Agent B/R/K test: PRED-A/C pass, PRED-B fail; RSTAR explains part but not most of the old margin |
| `ADR-0035-p7-ecological-environment-axis.md` | Completed, inconclusive | P7/G12 mixed pattern; C01/C10/C11 win, C00 misses threshold, so no distinct ecological-irreversible axis isolated |

## Current Code Map

| Path | Role | Key symbols |
|---|---|---|
| `src/aac/viability.py` | Viability core | `ViabilityCore` |
| `src/aac/world_model.py` | Action-outcome belief and uncertainty | `ActionOutcomeModel` |
| `src/aac/policy.py` | EFE policy plus G9 confidence gate | `PolicySelector` |
| `src/aac/agent.py` | Main loop wiring, shell view, optional prior organ, policy gate | `Agent` |
| `src/aac/shell.py` | Corrigibility shell and read-only view | `CorrigibilityShell`, `ShellView` |
| `src/aac/audit.py` | Append-only audit chain | `AuditLog` |
| `src/aac/prior_organ.py` | P4 belief-only organ interface | `PriorOrgan`, `OrganAdvice`, `BeliefSnapshot`, `merge_organ_advice` |
| `src/aac/prior_organ_o1.py` | Cheap deterministic reset scaffold | `ResetScaffoldOrgan` |
| `src/aac/prior_organ_o2.py` | Adaptive hazard organ, G5 archived | `AdaptiveHazardOrgan` |
| `src/aac/prior_organ_library.py` | Regime library organ, G6a | `RegimeLibraryOrgan` |
| `src/aac/prior_organ_latent.py` | Bayesian latent regime organ, G7/O4 | `LatentRegimeOrgan` |
| `src/aac/prior_organ_ensemble.py` | Ensemble regime organ, G8/O5 | `EnsembleRegimeOrgan` |
| `src/aac/prior_organ_llm.py` | LLM organ scaffold, no live key/control path | `LLMPriorOrgan`, `DeterministicStubBackend` |
| `src/aac/rap.py` | RAP field/messages, archived after G4 | `Need`, `Bid`, `Bond`, `Trace`, `Dissolve`, `RAPField` |
| `src/aac/rap_coordinator.py` | RAP coordinator, archived after G4 | `RAPCoordinator` |
| `src/aac/outcome_judge.py` | Grounded RAP outcome judge | `OutcomeJudge` |
| `src/aac/idle_drives.py` | Idle endogenous drives, G3/C3 input | `IdleDrives` |
| `src/aac/residual_calibrator.py` | ADR-0031 subject-side belief calibrator | `ResidualCalibrator` |
| `src/envs/structured_regime.py` | Reusable structured regime env for G6/G7/G8/G9/G10 | `StructuredRegimeEnv` |
| `src/envs/staleness.py` | P4 staleness-only environment | `StalenessEnv` |
| `src/envs/semantic_regime.py` | Offline semantic de-risk env | `SemanticRegimeEnv` |
| `src/envs/idle_windows.py` | Idle window wrapper used by C3 | `IdleWindowEnv` |
| `src/envs/ecological_regime.py` | ADR-0035/G12 2x2 environment cells | `EcologicalRegimeEnv` |

## Current Experiments

| Path | Gate | Status |
|---|---|---|
| `experiments/confidence_gated_g9.py` | G9 | Implemented and run; formal NOT MET, P0 discovery positive |
| `experiments/confidence_gated_g10.py` | G10 | MET on fresh seeds 800..829 |
| `tests/test_confidence_gated_g10.py` | G10 | Exists; C6/C7 and determinism guards |
| `experiments/completeness_g10.py` | ADR-0030 | COMPLETENESS PASS; P0 survives flip-the-conclusion traps |
| `tests/test_completeness_g10.py` | ADR-0030 | additive `base_temperature` wiring and B-temp guard |
| `experiments/prediction1_residual_calibrator.py` | ADR-0031 | PRED1-HOLDS; residual calibrator vs frozen G10 |
| `tests/test_residual_calibrator.py` | ADR-0031 | calibrator math, default-off wiring, C6/C7 guards |
| `experiments/relevance_aware_g10.py` | ADR-0034 | Completed; RSTAR calibration + r-final B/R/K attribution |
| `tests/test_relevance_aware_g10.py` | ADR-0034 | severity/noise env, policy diagnostics, RSTAR freeze/r-final guards |
| `experiments/ecological_g12.py` | ADR-0035/G12 | Completed; P7 transferable ecological-structure 2x2 r-final |
| `tests/test_ecological_g12.py` | ADR-0035/G12 | 2x2 env, reset boundary, RSTAR control, cell-win guards |
| `experiments/idle_productivity_c3.py` | C3 | RED; DIRECTED/RANDOM/POLICY statistically indistinguishable |
| `tests/test_idle_productivity_c3.py` | C3 | determinism and C6/C7 guards |
| `experiments/survival_axis_c1.py` | ADR-0028 | RED; survival shadows adaptation speed |
| `tests/test_survival_axis_c1.py` | ADR-0028 | determinism, arm wiring, C6/C7 guards |
| `experiments/risk_calibration_c1.py` | ADR-0029 | RED; no independent stationary risk advantage |
| `tests/test_risk_calibration_c1.py` | ADR-0029 | deterministic risk-env and C6/C7 guards |
| `experiments/ensemble_regime_g8.py` | G8 | NOT MET |
| `experiments/latent_regime_g7.py` | G7 | NOT MET |
| `experiments/structured_g6a.py` | G6a | MET |
| `experiments/semantic_g6b_offline.py` | G6b de-risk | semantic-exploitable YES, live LLM parked |
| `experiments/prior_organ_g5.py` | G5 | NOT MET |
| `experiments/rap_g4.py` | G4 | NOT MET, RAP archived |
| `experiments/metabolic_g3.py` | G3 | NOT MET overall; claim 1 supported |
| `experiments/causal_relevance_g2.py` | G2 | NOT MET, claim 2 hard-stopped |

## Current Tests

Current full suite:

```text
412 tests OK
```

Important current test files:

| Path | Covers |
|---|---|
| `tests/test_confidence_gated_policy.py` | G9 policy gate, C6/C7 guards, deterministic replay |
| `tests/test_confidence_gated_g10.py` | G10 fresh-seed confirmation guards |
| `tests/test_completeness_g10.py` | G10 completeness additive temperature wiring |
| `tests/test_residual_calibrator.py` | ADR-0031 residual self-calibrator C6/C7 guards |
| `tests/test_relevance_aware_g10.py` | ADR-0034 severity env, policy diagnostics, RSTAR calibration/r-final guards |
| `tests/test_idle_productivity_c3.py` | C3 idle-productivity de-risk guards |
| `tests/test_survival_axis_c1.py` | ADR-0028 survival-axis de-risk guards |
| `tests/test_risk_calibration_c1.py` | ADR-0029 stationary risk-axis de-risk guards |
| `tests/test_prior_organ_ensemble.py` | G8 ensemble organ |
| `tests/test_prior_organ_latent.py` | G7/O4 latent regime organ |
| `tests/test_prior_organ_o1.py` | O1 reset scaffold |
| `tests/test_prior_organ_o2.py` | O2 adaptive hazard |
| `tests/test_prior_organ_llm.py` | LLM organ parser/scaffold, no trust boundary violation |
| `tests/test_rap_*` | RAP field/coordinator/baselines/G4 archived line |
| `tests/test_idle_drives.py` | Idle drives baseline and C3 input |

## G9/G10/C3 Truth

G9 frozen parameters:

```text
gate_kappa = 0.5
gate_temp_floor = 0.1
```

G9 r-final:

| Arm | Mean post-shift regret area |
|---|---:|
| A0 baseline + none | 1361.6 |
| A1 baseline + O1 | 1325.6 |
| A4 baseline + O4 | 1224.3 |
| P0 gated + none | 746.5 |
| P4 gated + O4 | 893.4 |

G9 verdict:

- Formal gate: **NOT MET** because P4 was preregistered and failed G9-2.
- Research finding: P0 gate-alone is decisive, C6-preserving, and beats A0/A1/A4.
- G10 confirmed P0 on fresh seeds 800..829:
  - A0 1304.7 / A1 1268.6 / P0 759.8.
  - P0 beats A1 by 40.1%, 30/30, p<1e-6, bootstrap CI [457.0, 562.9].
- ADR-0030 completeness strengthened G10:
  - B-temp fixed-low baseline 1292.9 window area vs P0 739.8.
  - T1 P0<B-temp 30/30, p<1e-6.
  - T3 real-stake survival PASS: P0 1734.8 vs A0 1245.3 and B-temp 1482.6.
  - T5b StalenessEnv PASS: P0 advantage 36.4%, GENERAL FIX not structure theft.
  - Interpretation: the subject-side belief-to-action coupling survives all flip-the-conclusion traps.
- ADR-0031 residual-calibrator attack returned PRED1-HOLDS:
  - frozen lambda/eta = 0.8 / 0.1; prereg hash fe40754e2f7ff59dc6529af23703bfcf8ff99006a9e4e4a8a64694adf14833bf.
  - P0 788.8 vs PR 793.3; PR margin -0.006, wins 13/30, p=0.550830, CI [-30.8, 19.0].
  - PR-B vs A1 margin -0.039, CI [-67.9, -32.6].
  - Interpretation: residual calibration is not an independent second axis over frozen G10.
- ADR-0034 relevance-aware G10 theory test returned PARTIAL:
  - RSTAR frozen on seeds 1400..1419 as base_temperature=0.03, inertia=0.25, surprise_gain=1.0.
  - r-final seeds 1500..1529: PRED-A PASS, PRED-B FAIL, PRED-C PASS.
  - Mild severity: P0 loses to RSTAR (adv -0.089), as predicted.
  - Severe/default: P0 beats RSTAR decisively (adv +0.235, 30/30, CI [495.7,605.3]).
  - share_R=0.373: relevance-aware exploration explains part, not most, of the old margin.
  - Interpretation: G10 empirical result preserved; trajectory account weakened to B/R/K with a decisive K residue.
- ADR-0035/G12 P7 ecological environment axis returned INCONCLUSIVE:
  - C00 thin/reversible: P0 adv vs RSTAR +0.175, 30/30, but below the +0.20 cell-win threshold -> no win.
  - C01 thin/irreversible: P0 win, adv +0.340, damage_adv +0.436.
  - C10 ecological/reversible: P0 win, adv +0.208.
  - C11 ecological/irreversible: P0 win, adv +0.300, damage_adv +0.340.
  - Mixed pattern C01/C10/C11 without C00 does not isolate a distinct ecological-irreversible axis.
  - Interpretation: record as inconclusive; no G12 retuning or G11/C1 revival.
- C3 returned RED:
  - DIRECTED 1.691 / RANDOM 1.676 / POLICY 1.701.
  - Endogeny has no directed post-idle signal and is dropped from C1.
- ADR-0028 returned RED:
  - EXPLORER regret/budget 1.876 / 549.
  - EXPLOITER regret/budget 1.613 / 1709.
  - GATED regret/budget 1.048 / 2787.
  - Gated policy wins the measured metrics, but validity fails: survival is not independent of reframe/adaptation speed.
- ADR-0029 returned RED:
  - EXPLORER survival 1814 / EXPLOITER survival 1335 / GATED survival 1313.
  - GATED beats the best cheap arm in only 2/30 seeds, p=0.97, gap CI [-570, -321].
  - Stationary risk calibration is not an independent gate advantage.
- Next: synthesize ADR-0034/0035 and ask for founder direction; G11/C1 remains parked/closed unless a founder-level reset ADR first proves a new independent vs-cheap-baseline winning axis.

## Drift Prevention

When a gate, ADR, module, or test count changes, update:

1. `docs/CURRENT_STATE.yaml`
2. `docs/PROJECT_PLAN.md`
3. `codebase_index.md`
4. `ROADMAP.md` if phase/route changed
5. relevant ADR status/result section
6. root `../code_index.md` if workspace-level truth changed
7. root `../MEMORY.md` only as concise cross-agent memory

If these disagree, `docs/CURRENT_STATE.yaml` is the first place to repair, then propagate outward.
