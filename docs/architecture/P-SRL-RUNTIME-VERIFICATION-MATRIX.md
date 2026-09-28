# P-SRL Runtime Verification Matrix

> Status: `VERIFICATION_PLAN / REVISE_ACCEPTED / NOT_IMPLEMENTATION_CLAIM`
> Updated: 2026-07-17
> Scope: Convert SRL pain points and roadmap packages into testable engineering gates.
> Authority: `P-SRL-RUNTIME-IMPLEMENTATION-ROADMAP.md`, `AGENT-OS-CAPABILITY-IMPLEMENTATION-MAP.md`, `../AGENT-OS-PRODUCT-BLUEPRINT.md`.

## 1. Purpose

This matrix closes the gap between:

```text
pain point -> engineering package -> first failing test -> implementation entry -> evidence -> baseline/falsifier -> pass gate
```

It does not claim the packages are implemented. It defines what must be true before a package can move from `DESIGN_ONLY` or `PARTIAL` to `IMPLEMENTED_LOCAL`.

## 2. Verification levels

| Level | Meaning |
|---|---|
| `V0_SPEC` | Contract, package boundary and non-goals are specified. |
| `V1_RED_TEST` | A failing or bypass-detecting test exists before implementation. |
| `V2_LOCAL_UNIT` | Unit tests pass for the new service/contract behavior. |
| `V3_INTEGRATED` | Behavior is connected to TaskService, Capability, Evidence, Outcome or trace spine. |
| `V4_BASELINE` | Cheap baseline or falsifier is run where comparative value is claimed. |
| `V5_PRODUCT_PILOT` | Controlled real or production-adjacent task evidence exists. |

## 3. Matrix

| Pain point | Package | First failing test | Implementation entry | Evidence artifact | Baseline / falsifier | Pass gate | Current |
|---|---|---|---|---|---|---|---|
| Event source can be forged or untyped | `P-SRL-EVENT-CONTRACT-1` | `test_unauthorized_event_binding_rejected`; `test_duplicate_environment_event_is_idempotent`; `test_event_schema_rejects_unknown_effect_payload` | `EnvironmentEvent`; `EventSourceRef`; `MandateBindingResolver` | event receipt, source binding digest, redacted payload digest | forged-event falsifier | Only authenticated, scoped, schema-valid events reach MandateSteward | `V0_SPEC` |
| M1 leaks secrets or crosses tenant boundary | `P-SECURITY-BOUNDARY-0` | `test_trace_does_not_leak_secret_payload`; `test_cross_tenant_event_rejected`; `test_credential_ref_never_serializes_secret` | `SecurityBoundaryPolicy`; `TraceRedactor`; credential lease ref | redacted trace, denial receipt | raw-payload trace falsifier | No raw secret/PII payload in trace; tenant/workspace/principal scope enforced | `V0_SPEC` |
| User should not drive every next task | `P-SRL-RUNTIME-M1-plus` | `test_mandate_steward_authorized_event_creates_task_draft`; `test_revoked_or_epoch_changed_mandate_fails_closed`; `test_duplicate_event_replays_same_assessment` | `MandateSteward.observe_event(...)`; `MandateSteward.emit_task_draft(...)` | persisted `SituatedAssessmentRecord`; non-executing `TaskDraft` | user-prompted task creation baseline | Authorized event creates draft; revoked/stale/changed mandate cannot emit; duplicate event is idempotent | `V0_SPEC` |
| User/model must not hand-build prompt context | `P-SRL-SITUATED-WORKING-SET-1` | `test_working_set_rejects_cross_tenant_source`; `test_working_set_excludes_secret_payload`; `test_stale_input_requires_marker_or_abstain`; `test_conflicting_assertions_are_preserved`; `test_same_sources_replay_same_digest`; `test_source_version_drift_changes_digest`; `test_budget_exhaustion_preserves_mandatory_state`; `test_missing_required_state_emits_help_or_abstain`; `test_model_narration_cannot_override_selection_manifest`; `test_working_set_cannot_activate_task_or_effect` | `SituatedWorkingSetAssembler.assemble(...)`; existing `MandateRelevanceContext`/`OperationalProjectionRef` readers | immutable selection receipt with included/excluded reasons, missing refs, staleness/conflicts, budget, compiler version and digest | full event log, long context, rolling summary, unstructured RAG and typed explicit-state arms | Scoped minimal working set is replayable, provenance-complete and fails closed; comparative value requires better state continuity/HCW/outcome at matched cost, otherwise keep the strongest simpler baseline | `V0_SPEC` |
| TaskDraft accidentally triggers effects | `P-SRL-DRAFT-ACTIVATION-BOUNDARY-1` | `test_mandate_steward_cannot_activate_task_without_policy_gate`; `test_task_draft_does_not_call_external_connectors`; `test_task_activation_requires_expected_outcome_and_commitment` | `TaskDraft`; `TaskActivationGate`; `TaskActivation` | activation denial receipt; policy decision; expected outcome digest | direct-draft-to-task falsifier | Draft is non-executing; activation requires policy/capability gate, Goal, Commitment, ExpectedOutcome and WorkflowGraph | `V0_SPEC` |
| Agent asks too much or too little | `P-SRL-DISPATCH-1` | `test_missing_minimum_input_emits_help_request`; `test_available_evidence_prevents_unnecessary_help`; `test_help_response_reentry_unblocks_draft`; `test_unanswered_help_blocks_activation` | `DispatchDecision`; `HelpRequest`; `HelpResponse` | help ledger, response receipt, blocking state | always-ask and never-ask baselines | HelpRequest appears only after bounded acquisition attempts or authority/evidence gap; response path is typed | `V0_SPEC` |
| Every signal becomes work | `P-SRL-DISPATCH-1` | `test_low_impact_signal_observe_only`; `test_high_impact_due_commitment_creates_draft`; `test_disputed_evidence_abstains`; `test_random_disposition_fails_heldout` | `DispatchPolicy.score(...)`; `DispatchDecision` | score receipt with reason codes | all-events-create-tasks and random-disposition baselines | Disposition follows deterministic score over impact, urgency, uncertainty, risk, authority and cost | `V0_SPEC` |
| Complex analysis chooses wrong method | `P-SRL-DISPATCH-1` | `test_unknown_data_grain_routes_explore_first`; `test_forecast_routes_algorithm_first`; `test_causal_claim_requires_identification_or_help`; `test_data_agent_adapter_used_for_supported_metric_task` | `MethodSelectionReceipt`; Data Agent adapter | method receipt bound to draft | prompt-only planner baseline | Model narration cannot bypass data readiness, causal/statistical requirement or Data Agent adapter | `V0_SPEC` |
| SRL components pass but product value fails | `P-SRL-E2E-FALSIFIER-1` | `test_srl_v0_arm_uses_matched_budget`; `test_hidden_scorer_rejects_posthoc_gate_move`; `test_srl_not_better_than_prompt_baseline_is_not_met` | frozen task units, arm runner, hidden scorer | adjudication report, HCW ledger, drift report | user-driven prompt and scheduled workflow arms | SRL reduces hidden cognitive work without worse safety/cost/verified outcome rate | `V0_SPEC` |
| Outcome learning learns false success | `P-OUTCOME-EVAL-2` | `test_learning_rejects_unresolved_outcome`; `test_learning_rejects_unbound_evidence`; `test_verified_threshold_is_enforced_before_learning`; `test_knowledge_asset_rejects_unverified_outcome` | `OutcomeLearningGate.admit(...)` | learning admission receipt tied to `ObservedOutcome` | self-reported success falsifier | Only verified, scoped, evidence-bound outcomes may affect confidence/defaults | `V0_SPEC` |
| Rules and methods are ungrounded RAG | `P-KNOWLEDGE-ASSET-TYPES-1` | `test_seeded_procedure_changes_dispatch_with_trace`; `test_invalid_outcome_cannot_raise_confidence`; `test_rule_change_requires_w3_promotion`; `test_bad_asset_can_be_revoked` | `KnowledgeAssetService`; `Rule/Pattern/Procedure/Case/MethodAsset` | typed asset with source trace and lifecycle event | unstructured RAG-only baseline | Assets have trigger, input contract, evidence requirement, boundary, failure modes and update/deprecation policy | `V0_SPEC` |
| Policy or mandate changes cannot roll back | `P-OBSERVABILITY-LEDGER-0` | `test_policy_rollback_restores_previous_behavior`; `test_mandate_binding_epoch_dominates_pending_drafts`; `test_trace_records_cost_latency_reason_codes` | `PolicyVersionRef`; `MandateBindingEpoch`; `SrlTraceRecord` | trace record, rollback receipt | unversioned-policy falsifier | Policy/binding changes are versioned, observable and revertible in local controlled slice | `V0_SPEC` |
| Jailbreak or model narration bypasses gates | `P-SRL-ADVERSARIAL-1` | `test_policy_bypass_via_jailbreak_input`; `test_model_narration_does_not_satisfy_evidence_requirement`; `test_revoked_mandate_reused_in_assessment` | adversarial event fixtures | denial receipts, evidence gaps | prompt-injection bypass falsifier | Model text never satisfies authority/evidence by itself | `V0_SPEC` |
| Multimodal input remains grounded | `P-MULTIMODAL-IR-1` | `test_image_ocr_grounding_requires_bbox`; `test_pdf_claim_requires_page_anchor`; `test_video_claim_requires_timestamp`; `test_text_model_fallback_uses_modal_ir` | `ModalIngestionService.parse(...)`; `ModalEvidenceAnchor` | modality IR with page/timestamp/bbox/table anchors | direct multimodal narrative baseline | Deferred until M1-M3 and outcome gate are stable | `DEFERRED` |
| Training improves behavior without replacing runtime gates | `R/P-MODEL-TRAINING-LOOP-1` | `test_training_sample_requires_trace_and_outcome`; `test_authority_violation_not_used_as_positive_sample`; `test_shadow_model_cannot_execute_effects`; `test_reward_penalizes_unverified_claims` | `TrainingDatasetBuilder`; `ModelCandidateRegistry`; `ShadowModelEvaluator` | dataset manifest, eval report, canary/rollback record | tools/schema/RAG baseline | Deferred until tools/contracts/RAG insufficiency is measured on held-out tasks | `DEFERRED` |
| Million-agent runtime is virtualized and observable | `P-DISTRIBUTED-RUNTIME-1` | `test_dormant_agent_consumes_no_worker`; `test_lease_fence_blocks_double_mutation`; `test_idempotent_effect_replay_does_not_duplicate`; `test_backpressure_pauses_low_priority_runs`; `test_cost_ledger_sums_by_tenant_task_model_tool` | `AgentScheduler`; `VirtualAgentExecutor`; `RunLeaseStore`; `CostLedger` | scheduler trace, lease records, cost ledger, replay report | one-process-per-agent falsifier | Deferred until local SRL pilot evidence exists | `DEFERRED` |

## 4. Mandatory test shape

Each package must start with tests that would fail if the implementation:

- returns constant success;
- accepts model narration as evidence;
- bypasses policy, authority or correction epoch;
- creates executable work without ratified mandate and environment binding;
- activates a TaskDraft without Goal, Commitment, ExpectedOutcome and WorkflowGraph;
- leaks raw secrets or cross-tenant data into traces;
- learns from `INVALID`, `UNRESOLVED` or unbound outcomes;
- changes cross-task default behavior without W3/W4 promotion;
- hides missing data, causal non-identifiability or unsupported modality.

## 5. First implementation slice

The first build slice is `P-SRL-RUNTIME-M1-plus`, not plain M1:

```text
P-SRL-EVENT-CONTRACT-1
  + P-SECURITY-BOUNDARY-0
  + held-out/baseline/HCW protocol
  + MandateSteward V0
  + TaskDraft/TaskActivation boundary
  + Policy/Capability gate integration
  + Observability trace
```

Do not start `P-DISTRIBUTED-RUNTIME-1`, `P-MULTIMODAL-IR-1`, or `R/P-MODEL-TRAINING-LOOP-1` until M1-plus and Dispatch have a tested integrated path and the E2E falsifier has at least one run.

## 6. Completion claim template

Any package completion claim must include:

```text
Package:
Requirement class:
Implementation entry:
Source checkout / branch:
Public entry point:
Contracts:
Failure paths:
Tests:
Evidence artifact:
Baseline/falsifier:
Cost/SLO:
Security/tenant boundary:
Residual risk:
Current state:
```
