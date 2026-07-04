# codebase_index - autonomous-agent-core

> Last updated: 2026-07-04
> Purpose: fast map from current research state to code, tests, experiments, and ADRs.
> First read: `docs/CURRENT_STATE.yaml`.

## Current Snapshot

```yaml
branch: research/stage0-gate-sovereignty-2026-07-03
stage: AGDE-T3 fresh scored NULL; CWM-LEARN-5e-2 hard non-enumerable functional-forms r-final MET
immediate_next: stop boundary-prose drift; choose scale/cross-domain transfer gate, governed seam-lane design/execution, or PARK
tests: 740 OK
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
| `ADR-0036-bounded-consequence-prior-gate.md` | Completed, NOT MET | G13 tested a belief-only bounded consequence prior over P0 for scar-specific irreversible benefit |
| `ADR-0037-self-determination-depth-vs-corrigibility.md` | Proposed, docs-only / OPEN | Registers SD0-SD4 and the open SD4-separability question; parent SD4 VAL-DISENT-1 read-out adds negative H1 evidence but does not decide the ADR |
| `ADR-0038-g-eco-mechanism-lower-half.md` | Accepted, lower-half implemented + F1-F6 discipline fixes + hardened pre-Gate-2 candidate writer/verifier | G-Eco mechanism substrate/env/arms/refs/guards plus candidate rates/battery/threshold/audit JSON writer, calibration-selected VH parameter provenance, recursive AST static firewalls, calibration-ref-only rate witness, C3 verdict-mechanics leaves, and integrity/firewall verifier; no co-signed freeze, no r-final, no verdict |
| `ADR-0039-viability-empowerment-c1-formalization.md` | Proposed (open, founder-reserved); landed 2026-06-29 from branch | Viability/empowerment formalization of C1 + preregistered S1/S2 gate; not accepted, not funded, not run |

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
| `src/aac/consequence_prior.py` | ADR-0036 bounded consequence-prior organ and cheap CAUTIOUS control | `ConsequencePriorRecord`, `BoundedConsequencePriorOrgan`, `CautiousScarOrgan` |
| `src/aac/g_eco.py` | ADR-0038 G-Eco lower-half shared substrate, value aggregators, frozen-source battery adapters, truth-privileged cheat refs, metrics, pre-Gate-2 candidate freezes, content-hash verifier, recursive AST static firewalls, calibration-ref-only rate witness, audit guards, Gate-2 guards | `GEcoSharedSubstrate`, `GEcoArm`, `GEcoArmSource`, `GEcoVHParams`, `build_g_eco_arms`, `scan_rate_grid`, `select_vh_parameters`, `freeze_battery_parameters`, `derive_threshold_freeze`, `build_baseline_audit`, `verify_content_hash`, `assert_g_eco_static_firewalls`, `assert_static_firewall`, `assert_no_calibration_refs_in_rfinal`, `GEcoMetrics` |
| `src/aac/rap.py` | RAP field/messages, archived after G4 | `Need`, `Bid`, `Bond`, `Trace`, `Dissolve`, `RAPField` |
| `src/aac/rap_coordinator.py` | RAP coordinator, archived after G4 | `RAPCoordinator` |
| `src/aac/outcome_judge.py` | Grounded RAP outcome judge | `OutcomeJudge` |
| `src/aac/idle_drives.py` | Idle endogenous drives, G3/C3 input | `IdleDrives` |
| `src/aac/residual_calibrator.py` | ADR-0031 subject-side belief calibrator | `ResidualCalibrator` |
| `src/aac/commitment_ledger.py` | R-CSL-1 no-model commitment-ledger mechanism (preserved-failed-baseline; builder!=reviewer separation enforced in its harness) | `CommitmentLedgerPolicy` |
| `src/envs/structured_regime.py` | Reusable structured regime env for G6/G7/G8/G9/G10 | `StructuredRegimeEnv` |
| `src/envs/staleness.py` | P4 staleness-only environment | `StalenessEnv` |
| `src/envs/semantic_regime.py` | Offline semantic de-risk env | `SemanticRegimeEnv` |
| `src/envs/idle_windows.py` | Idle window wrapper used by C3 | `IdleWindowEnv` |
| `src/envs/ecological_regime.py` | ADR-0035/G12 2x2 environment cells | `EcologicalRegimeEnv` |
| `src/envs/consequence_scar.py` | ADR-0036/G13 public-affordance scar environment | `ConsequenceScarEnv`, `ConsequenceFeature` |
| `src/envs/ecological_4cond.py` | ADR-0038 G-Eco four-condition environment with partial/lagged/noisy observation; no rate-grid scan or divergence detector | `Ecological4CondEnv`, `GEcoState`, `GEcoRates`, `GEcoObservation`, `transition_state` |
| `src/envs/commitment_correction.py` | R-CSL-1 commitment/correction environment | `CommitmentCorrectionEnv`, `CorrectionSignal` |

## Current Experiments

| Path | Gate | Status |
|---|---|---|
| `experiments/svar_scm.py` | AGDE-T3 | SVAR trajectory arena for temporal active-discovery pilots; contemporaneous MEC × lag-support pool with window-clamp interventions |
| `experiments/agde_t3_pilot.py` | AGDE-T3 pilot v1/v2 | Calibration-only apparatus pilot; exact fixed-point clamp predictor after v1 caught truth-self-survival bug |
| `experiments/agde_t3_costgap.py` | AGDE-T3 pilot v3 | Calibration-only cost/gap pilot; exposed insufficient arena separation before freeze |
| `experiments/agde_t3_separation.py` | AGDE-T3 pilot v4 | Calibration-only separation measurement; diagnosed nested lag-superset equivalence / causal-minimality issue |
| `experiments/agde_t3_pilot5.py` | AGDE-T3 pilot v5 | Calibration-only causal-minimality collapse pilot; v5 inputs make T3 freeze-packet-ready, no verdict |
| `experiments/agde_t3_pilot5.result.json` | AGDE-T3 pilot v5 | Calibration result schema; `do_value=3.2`, `budget=4` gives active_id 0.750 vs random_id 0.417 on calib families |
| `tests/test_agde_t3_pilot5.py` | AGDE-T3 pilot v5 | Guards explicit minimality collapse and calibration-only / no-freeze result schema |
| `docs/pre_spec/AGDE-T3.PREREG-2026-07-04.md` | AGDE-T3 fresh scored gate | Frozen inputs and mechanical result; scored NULL on fresh families, controls pass, no rescue/re-cut |
| `experiments/agde_t3_freeze.py` | AGDE-T3 fresh scored gate | Uses v5 inputs with fresh families, ACTIVE/RANDOM/BLIND_CEILING arms, C7 halt guard, bounded result schema |
| `experiments/agde_t3_freeze.result.json` | AGDE-T3 fresh scored gate | Fresh scoring artifact: ACTIVE 0.5000, RANDOM 0.2083, BLIND_CEILING 0.5000, verdict NULL |
| `tests/test_agde_t3_freeze.py` | AGDE-T3 fresh scored gate | Guards frozen constants, calibration-family exclusion, paused-shell zero-intervention behavior, and non-claim schema |
| `docs/pre_spec/5E-2.ZERO-SHOT-CALIBRATION-2026-07-04.md` | CWM-LEARN-5e-2 zero-shot calibration | Records no freeze-ready region: zero-shot signal exists near n=38/40, but cheap screening does not collapse enough |
| `experiments/cwm_learn_5e2.py` | CWM-LEARN-5e-2 zero-shot calibration | Calibration-only runner using frozen data-blind 5e union before data; compares later-data screening, random, and oracle across train-size sweep |
| `experiments/cwm_learn_5e2.result.json` | CWM-LEARN-5e-2 zero-shot calibration | Calibration artifact for n_train 30/36/38/40/60/80; all candidate_freeze_region=false |
| `tests/test_cwm_learn_5e2.py` | CWM-LEARN-5e-2 zero-shot calibration | Guards frozen proposal source, no-claim schema, later-data screening arm, and train-size restoration |
| `docs/pre_spec/5E-2.FORMS-CALIBRATION-2026-07-04.md` | CWM-LEARN-5e-2 functional-forms calibration | Records typed forms signal with clean Condition-B collapse, but no freeze-ready region because pair screening remains high |
| `experiments/cwm_learn_5e2_forms.py` | CWM-LEARN-5e-2 functional-forms calibration | Calibration-only non-enumerable form runner: threshold/saturation/ratio proposals vs finite pair-product screening, random forms, oracle, and Condition-B |
| `experiments/cwm_learn_5e2_forms.result.json` | CWM-LEARN-5e-2 functional-forms calibration | Calibration artifact: proposed forms median_s=1.0000, pair-screening median_s=0.7823, Condition-B collapse ok, candidate_freeze_region=false |
| `tests/test_cwm_learn_5e2_forms.py` | CWM-LEARN-5e-2 functional-forms calibration | Guards typed non-pair form specs, finite feature expansion, bounded no-claim schema, Condition-B control, and pair-screening comparison |
| `docs/pre_spec/5E-2.HARD-FORMS-CALIBRATION-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms calibration | Records freeze-candidate bandpass arena: proposed hard forms median_s=1.0000, pair-screening/random=0.0000, Condition-B collapse ok |
| `experiments/cwm_learn_5e2_forms_hard.py` | CWM-LEARN-5e-2 hard functional-forms calibration | Calibration-only bandpass-product form arena that breaks finite pair-product proxies while preserving typed-form verifier health |
| `experiments/cwm_learn_5e2_forms_hard.result.json` | CWM-LEARN-5e-2 hard functional-forms calibration | Calibration artifact for seeds 30..33; candidate_freeze_region=true, not a verdict |
| `tests/test_cwm_learn_5e2_forms_hard.py` | CWM-LEARN-5e-2 hard functional-forms calibration | Guards bandpass-form arena, bounded no-claim schema, and smoke seed pair-proxy gap |
| `docs/pre_spec/5E-2.HARD-FORMS-FRESH-SCORED-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Records disjoint-seed fresh scored MET for hard bandpass forms; not r-final and no autonomy/product/C6-C7 claim |
| `experiments/cwm_learn_5e2_forms_hard_freeze.py` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Uses frozen hard-form arena with calibration seeds 30..33 and fresh scoring seeds 40..45; mechanical MET/NULL/INVALID verdict |
| `experiments/cwm_learn_5e2_forms_hard_freeze.result.json` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Fresh scored artifact: proposed hard forms median_s=1.0000, pair-screening/random=0.0000, Condition-B collapse, verdict MET |
| `tests/test_cwm_learn_5e2_forms_hard_freeze.py` | CWM-LEARN-5e-2 hard functional-forms fresh scored gate | Guards disjoint seeds, Condition-B invalidation, no-claim schema, and verdict domain |
| `docs/pre_spec/5E-2.HARD-FORMS-RFINAL.PREREG-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms r-final | Preregistered seeds, decision rule, lock scope, and non-claim boundaries for the hard non-enumerable form channel |
| `docs/pre_spec/5E-2.HARD-FORMS-RFINAL.lock.json` | CWM-LEARN-5e-2 hard functional-forms r-final | SHA-256 lock binding prereg, hard-form mechanism runner, r-final runner, and r-final tests before r-final execution |
| `experiments/cwm_learn_5e2_forms_hard_rfinal.py` | CWM-LEARN-5e-2 hard functional-forms r-final | Lock-verified r-final runner for seeds 60..69; emits MET/NULL/INVALID with bounded non-claim schema |
| `experiments/cwm_learn_5e2_forms_hard_rfinal.result.json` | CWM-LEARN-5e-2 hard functional-forms r-final | R-final artifact: proposed hard forms median_s=1.0000, pair-screening/random=0.0000, Condition-B collapse, verdict MET |
| `tests/test_cwm_learn_5e2_forms_hard_rfinal.py` | CWM-LEARN-5e-2 hard functional-forms r-final | Guards disjoint seed bands, prereg lock drift refusal, bounded r-final schema, and non-claim fields |
| `docs/pre_spec/5E-2.HARD-FORMS-RFINAL-RESULT-2026-07-04.md` | CWM-LEARN-5e-2 hard functional-forms r-final | Human result record and route decision: continue only through scale/cross-domain transfer, governed seam-lane design, or park |
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
| `experiments/consequence_prior_g13.py` | ADR-0036/G13 | Completed; development and one r-final harness |
| `experiments/consequence_prior_g13.development.json` | ADR-0036/G13 | Development audit artifact; scar screen PASS, gate preview NOT MET |
| `experiments/consequence_prior_g13.freeze.json` | ADR-0036/G13 | Founder unlock artifact for the one r-final |
| `experiments/consequence_prior_g13.result.json` | ADR-0036/G13 | R-final artifact; G13 NOT MET |
| `tests/test_consequence_prior_g13.py` | ADR-0036/G13 | CP interface, C6/C7, scar env, collapse, denominator, r-final guard tests |
| `experiments/g_eco.py` | ADR-0038/G-Eco + r-final harness | Lower-half smoke/mechanism-check + `pregate2-candidates`/`pregate2-verify` + `gate2-cosign`. r-final harness: `assert_gate2_unlocked` (founder-cosign-gated verifier), `run_rfinal` (faithful frozen-candidate replay -> RAW only, C6/C7 + Stage-2 prereg.lock double-bind), `verify_prereg_lock` (mechanism-code drift gate), `build_adjudication_packet` + `verify_adjudication_integrity` (kimicode handoff + Claude verify-and-narrate incl. gate-4 Wilcoxon/bootstrap). freeze/r-final/verdict CLI still refuse; verdict is kimicode's |
| `tests/test_g_eco.py` | ADR-0038/G-Eco | Shared substrate, r-final cheat-ref firewall, truth-state separation, frozen-source battery adapters, de-complete observation, active lookahead, VH_noStake, deterministic replay, reset boundary, calibration-selected VH params, recursive static firewalls, C3 verdict-mechanics leaves, pre-Gate-2 candidate writer/verifier/audit guards, C6/C7, Gate-2 refusal guards |
| `tests/test_gate2_unlock.py` | G-Eco r-final harness | Gate-2 unlock verifier: locked-by-default, founder co-sign exact-bytes binding, audit-halt/incomplete, seed-band, tamper guards |
| `tests/test_rfinal_runner.py` | G-Eco r-final harness | run_rfinal: refuses-when-locked, faithful-replay drift, RAW-only no-verdict, determinism, C6/C7 (multi-seed, non-acting-arm rejected) |
| `tests/test_adjudication.py` | G-Eco r-final harness | Packet assembly + verify-and-narrate integrity (fabrication/non-frozen-theta/ragged-rows/alpha-drift caught); gate-4 Wilcoxon+bootstrap known-answers |
| `tests/test_prereg_lock.py` | G-Eco r-final harness Stage-2 | prereg.lock double-bind: no-lock-not-ready, verified-lock-ready, mechanism drift / traversal / non-object / missing rejected |
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
| `experiments/r_csl_1.py` | R-CSL-1 | Preserved-failed-baseline no-model commitment-ledger mechanism + harness; preregistered, NOT run (landed 2026-06-29 from probe branch) |
| `experiments/direction1_coupling_sweep.py` | Direction-1 | confidence->temperature coupling falsifier; FLAT / record-and-stop (max frozen-vs-best gap 3.3%) |
| `experiments/parity_lag_falsifier.py` | parity-lag | structural-vs-artifact falsifier; INCONCLUSIVE (kimicode flagged the clean re-prereg as unfair-baseline OVERCLAIM) |
| `experiments/parity_lag_largelag_falsifier.py` | parity-lag | clean large-lag re-prereg; ARTIFACT (structural foreclosure refuted) |

## Current Tests

Current full suite:

```text
740 tests OK
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
| `tests/test_consequence_prior_g13.py` | ADR-0036 bounded consequence-prior organ, scar env, r-final lock, collapse/denominator guards |
| `tests/test_g_eco.py` | ADR-0038 lower-half G-Eco mechanism, pre-Gate-2 verifier/recursive static-firewall hardening, and Gate-2 refusal guards |
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
  - frozen lambda/eta = 0.8 / 0.1; prereg hash f87c23a43d2e0abd0130cee1ffab34b5741018ec8376f291139c2a5928abc936.
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
- ADR-0036/G13 completed NOT MET:
  - Candidate `CP = P0 + bounded consequence prior`; baseline `P0-alone`.
  - It is not a G12 rescue. G12 remains inconclusive.
  - Gate requires irreversible/scarred benefit over P0, scar specificity versus reversible cells, stale-prior safety, and C6/C7 invariants.
  - Fresh seeds: development `1750..1769`, r-final `1800..1829`.
  - Implementation and development audit are complete:
    - `experiments/consequence_prior_g13.development.json` records the development run.
    - Scar validity screen PASS; CAUTIOUS capture is `0.470`, so the apparatus is not cheap-trivially avoided on development seeds.
    - R1 irreversible preview: `adv=+0.048`, `wins=14/20`, `p=0.00604`, `damage_adv=+0.434`.
    - R0 reversible preview: `adv=-0.274`, first-window `stale_prior_harm=13.094`, any reversible-cell harm seeds `17/20`; stale-prior guard fails.
  - R-final:
    - `experiments/consequence_prior_g13.freeze.json` records founder unlock.
    - `experiments/consequence_prior_g13.result.json` records the one r-final.
    - Scar validity screen PASS.
    - R1 irreversible: `adv=+0.083`, `wins=25/30`, `p=0.000001895`, CI `[291.66,589.94]`, `damage_adv=+0.463`.
    - R0 reversible: `adv=-0.255`, first-window `stale_prior_harm=12.679`, any reversible-cell harm seeds `21/30`.
    - Specificity PASS: contrast `+0.317`, CI lower `+0.150`.
    - CAUTIOUS captures `0.533` of CP's irreversible damage reduction.
    - Verdict: NOT MET. G13-1 and G13-3 fail; G13-2 and C6/C7 pass.
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
- Next: do not rerun or retune G13. G-Eco lower-half plus F1-F6 discipline fixes and hardened pre-Gate-2 candidate writer/verifier exist on `feat/g-eco-pre-gate2-hardening`, but founder/CTO co-signed freeze, Gate-2, r-final, and verdict remain locked behind the parent Route C protocol and founder-reserved gates.

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
