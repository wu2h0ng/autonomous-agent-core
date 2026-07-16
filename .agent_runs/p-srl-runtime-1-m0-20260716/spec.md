# P-SRL-RUNTIME-1 M0 Specification

## 1. Contracts to use

Import from `agent_os_contracts`:
- `Mandate`, `MandateRatificationReceipt`, `AgentInstanceRef`, `MandateEnvelope`, `EvaluationPrinciple`
- `StandingMission`
- `EnvironmentBinding`, `EnvironmentBindingMode`, `SrlEnvironmentEvent`
- `SrlRelevanceAssessment`, `SrlRelevanceDisposition`
- `SrlHelpRequest`, `SrlHelpResponse`, `SrlHelpResponseKind`, `HelpBudget`, `HelpBurdenReceipt`

## 2. Public API

### `SrlRuntime` class

```python
class SrlRuntime:
    def __init__(
        self,
        *,
        event_ledger: EventLedgerPort,
        mandate_registry: MandateRegistryPort,
        assessor_port: AssessorPort,
        goal_formation: GoalFormationPort,
        budget_enforcement: BudgetEnforcementPort,
        help_dispatch: HelpDispatchPort,
        task_activation: TaskActivationPort,
        outcome_acceptor: OutcomeAcceptorPort,
        audit_port: AuditPort,
        runtime_instance_ref: AgentInstanceRef,
    ) -> None: ...

    def evaluate_event(self, event: SrlEnvironmentEvent) -> SrlEvaluationResult: ...
    def propose_goal(self, assessment: SrlRelevanceAssessment) -> ProposedGoal: ...
    def activate_goal(self, proposed_goal: ProposedGoal, authority: ActivationAuthority) -> TaskActivationResult: ...
    def emit_help_request(self, help_request: SrlHelpRequest) -> HelpDispatchResult: ...
    def resolve_help_request(self, response: SrlHelpResponse) -> HelpDispatchResult: ...
    def accept_outcome(self, outcome_record: TrustedOutcomeRecord) -> OutcomeAcceptanceResult: ...
```

### Result types

All result types are `ContractModel` subclasses:
- `SrlEvaluationResult`: `result_class`, `event_id`, `assessment_id | None`, `goal_id | None`, `help_request_id | None`, `halt_reason | None`
- `TaskActivationResult`: `activated`, `task_id | None`, `rejection_reason | None`
- `HelpDispatchResult`: `emitted | resolved`, `help_request_id`, `burden_receipt | None`
- `OutcomeAcceptanceResult`: `accepted`, `rejection_reason | None`

## 3. Port Protocols

### `EventLedgerPort`
- `append(event: SrlEnvironmentEvent) -> EventLedgerReceipt`
- `get(binding_id: str, dedupe_key: str) -> SrlEnvironmentEvent | None`
- `list_events(binding_id: str) -> Sequence[SrlEnvironmentEvent]`

### `MandateRegistryPort`
- `current_ratified_mission(mandate_id: str) -> StandingMission`
- `ratify_mandate(mandate: Mandate, receipt: MandateRatificationReceipt) -> None`
- `get_mandate(mandate_id: str) -> Mandate`

### `AssessorPort`
- `assess(event: SrlEnvironmentEvent, mission: StandingMission) -> SrlRelevanceAssessment`

### `GoalFormationPort`
- `form_goal(assessment: SrlRelevanceAssessment, mission: StandingMission) -> ProposedGoal`

### `BudgetEnforcementPort`
- `check_binding_budget(binding: EnvironmentBinding) -> BudgetStatus`
- `charge_help(help_request: SrlHelpRequest) -> HelpBurdenReceipt`

### `HelpDispatchPort`
- `emit(help_request: SrlHelpRequest) -> HelpDispatchResult`
- `resolve(response: SrlHelpResponse) -> HelpDispatchResult`

### `TaskActivationPort`
- `activate(proposed_goal: ProposedGoal, authority: ActivationAuthority) -> TaskActivationResult`

### `OutcomeAcceptorPort`
- `accept(outcome_record: TrustedOutcomeRecord) -> OutcomeAcceptanceResult`

### `AuditPort`
- `record(transition: AuditTransition) -> None`

## 4. Invariant mapping for RED tests

| ID | Test scenario |
|---|---|
| I-4 | `current_ratified_mission` rejects `StandingMission` with mismatched `parent_mandate_digest` |
| I-8 | `evaluate_event` rejects assessment with mismatched `assessor_policy_digest` |
| I-11 | Repeated help requests flip `HelpBurdenReceipt.status` to `EXCEEDED` |
| I-12 | `EventLedgerPort.append` rejects duplicate `dedupe_key` for same binding |
| I-13 | `evaluate_event` returns `BUDGET_HALT` when wake budget exceeded |
| I-14 | `TaskActivationPort` rejects any attempt to create `CapabilityGrant` |
| I-15 | `accept_outcome` rejects `ObservedOutcome` not signed by trusted evaluator registry |
| I-16 | `current_ratified_mission` rejects mission when Mandate status is not `RATIFIED`/`ACTIVE` or expired |
| I-18 | `GoalFormationPort` rejects write-effect proposal on read-only binding |
| I-20 | After `SrlHelpRequest.expires_at`, `resolve` permits only `continuable_work` |
| I-21 | `BudgetEnforcementPort` computes `HelpBurdenReceipt`, not `HelpDispatchPort` |
| I-22 | `SrlRuntime` rejects W1/W2 update objects that mutate Mandate/Envelope/Mission/grants |
| I-23 | Same `instance_id` cannot produce assessment and accept authority for same transition |
| I-25 | Cross-restart replay with same `dedupe_key` is idempotent |

## 5. Fail-closed defaults

- Unknown disposition → `ABSTAIN`
- Policy digest mismatch → reject assessment, increment help metrics
- Budget exceeded → halt binding, emit HELP/REVOCATION_REQUEST
- Untrusted outcome → reject
- C7 check failure → halt affected action
