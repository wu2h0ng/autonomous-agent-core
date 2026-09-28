# Mandate / Situated Responsibility Loop — Parallel Design Wave

> Date: 2026-07-16
> Track: Product / Architecture / Research boundary
> Status: `FOUNDER_DIRECTION_ACCEPTED / DESIGN_ONLY / NO_RUNTIME_AUTHORIZATION`
> Scope: Product lifecycle above Task/AWL; Mandate, environment binding, relevance, help, authority and falsification contracts
> Depends on: DEV-REAL-OUTCOME-1, W1-W5 write-channel decision, ADR-0037, ADR-0058, existing Task/Action/C7 spine
> Does not authorize: provider calls, training, runtime changes, external effects, merge, push or release

## 1. Authority read order

1. `docs/GOAL-BLUEPRINT.md` sections 5 and 9B ( Situated Responsibility Loop as architecture center, `Autonomy(S,E,O,V,T)` discipline ).
2. `docs/research/founder-decision-2026-07-16-adaptive-write-channels-and-requirement-taxonomy.md` ( W1-W5, U/P/A/E/R taxonomy, machine-readable `requirement_claim` ).
3. `docs/research/situated-responsibility-loop-architecture-2026-07-16.md` ( canonical objects, SRL loop, R-SRL-1 falsifier, parallel task cast ).
4. `docs/research/situated-operational-model-architecture-2026-07-16.md` ( SOM layers, generic Core vs domain projection, assertion semantics ).
5. `docs/research/portfolio-attack-review-synthesis-2026-07-16.md` ( P0 false `VERIFIED`, missing user-task evidence, C7 fault domain, cost/budget shells ).
6. `docs/adr/ADR-0058-mandate-driven-situated-responsibility-loop.md` ( V0/V1 phasing, correction-epoch atomicity, entry gates ).
7. `docs/CURRENT_STATE.yaml` ( DEV-REAL-OUTCOME-1 status, SPINE-0 boundary, blockers ).

## 2. Decision summary

Agent OS needs a Product lifecycle above `Task` so that a continuing responsibility can be delegated without the operator reconstructing identity, state, attention and next steps on every turn. The top object is a **Mandate**; the architecture center is the **Situated Responsibility Loop (SRL)**.

This packet designs, but does not implement, the contracts and invariants for:

- `P-MANDATE-1`: Mandate contract, ratification receipt, authority envelope and correction epoch.
- `P-SRL-ENV-1`: environment binding, relevance context and situated assessment.
- `P-SRL-HELP-1`: structured `HelpRequest` contract and escalation conditions.
- `A-SRL-1`: threat model and authority boundaries ( C7, no self-approval, W1-W5 separation ).
- `R-SRL-1`: falsifiable metrics for reducing Founder hidden cognitive work.

The loop is composed of typed, independently versioned ports; no single component observes, scores relevance, writes portfolio truth, grants capabilities and accepts its own outcomes. `MandateSteward` is a logical coordinator, not a person, final authority or monolithic cognitive subject.

## 3. Requirement taxonomy receipts

```yaml
requirement_claims:
  - id: P-MANDATE-1
    primary_class: P
    secondary_class: A
    protects_or_delivers_ref: U-SRL-1
    state: SPECIFIED
    evidence_refs: [this document, ADR-0058, GOAL-BLUEPRINT §5]
    closed_by: null

  - id: P-SRL-ENV-1
    primary_class: P
    secondary_class: A
    protects_or_delivers_ref: U-SRL-1
    state: SPECIFIED
    evidence_refs: [this document, situated-responsibility-loop-architecture-2026-07-16.md]
    closed_by: null

  - id: P-SRL-HELP-1
    primary_class: P
    secondary_class: U
    protects_or_delivers_ref: U-SRL-1
    state: SPECIFIED
    evidence_refs: [this document, ADR-0058 §HelpRequest]
    closed_by: null

  - id: A-SRL-1
    primary_class: A
    secondary_class: E
    protects_or_delivers_ref: PERMANENT_BOUNDARY_C7_NO_SELF_APPROVAL
    state: SPECIFIED
    evidence_refs: [this document, GOAL-BLUEPRINT §6, founder-decision-2026-07-16]
    closed_by: null

  - id: R-SRL-1
    primary_class: R
    secondary_class: null
    protects_or_delivers_ref: P-SRL-1
    state: DRAFT_NOT_FROZEN
    evidence_refs: [this document, situated-responsibility-loop-architecture-2026-07-16.md §8]
    closed_by: null

  - id: U-SRL-1
    primary_class: U
    secondary_class: null
    protects_or_delivers_ref: null
    state: HYPOTHESIS
    evidence_refs: [GOAL-BLUEPRINT §5, portfolio-attack-review-synthesis-2026-07-16.md §2]
    closed_by: null
```

`U-SRL-1`: a user can delegate an ongoing responsibility ( for example, maintaining repository quality invariants or operating a bounded organizational function ) without repeatedly restating mission, reconstructing cross-task state, noticing every relevant environment change, forming the next goal and interpreting outcomes.

## 4. P-MANDATE-1 — Mandate contract, ratification receipt, authority envelope and correction epoch

### 4.1 Scope

`P-MANDATE-1` specifies the externally ratified responsibility contract that sits above `OutcomePortfolio`, `PersistentCommitment`, `Goal`, `Program`, `Task` and `Action`. It separates:

- `PrincipalIdentity` / authority grants ( W5-adjacent );
- `Mandate` / standing mission;
- `AgentInstanceRef` ( attribution only );
- `CommitmentPortfolioView`;
- environment bindings;
- W1/W2 cognitive state and learning history.

### 4.2 Mandate lifecycle

```text
DRAFT (system or principal proposes)
  -> RATIFIED (principal signs; receipt sealed; correction epoch 0)
    -> ACTIVE (StandingMission projected; environment bindings enabled)
      -> AMENDMENT_PROPOSED (principal must ratify; new correction epoch)
      -> SUSPENDED (temporary; external authority)
      -> REVOKED (terminal; all descendant work halts)
      -> EXPIRED (terminal by time horizon)
```

- The system may **propose** a Mandate, an amendment or a revocation, but cannot ratify, self-expand, self-renew, weaken evaluation principles or remove revocation rights.
- A ratification receipt is an immutable, content-addressed record binding the exact Mandate bytes, the principal attestation, the `AgentInstanceRef` scope and the initial correction epoch.
- A Mandate is not one giant Task; it authorizes the SRL to form bounded work beneath it.

### 4.3 Authority envelope

The envelope enumerates the allowed space of autonomous action:

| Envelope field | Meaning | Overflow behavior |
|---|---|---|
| `allowed_task_classes` | which Goal/Program/Task shapes may be spawned | emit `HelpRequest` |
| `allowed_effect_classes` | side-effect guarantee tiers allowed ( see `CapabilitySpec` ) | deny / escalate |
| `allowed_repository_refs` / `resource_refs` | where work may touch | deny / escalate |
| `capability_grant_rules` | which capabilities the steward may request and under what policy | deny / escalate |
| `wake_budget`, `query_budget`, `help_budget` | event-processing, sensing and help ceilings | `HELP_BURDEN_EXCEEDED` |
| `max_concurrent_tasks`, `max_duration_seconds` | concurrency and time bounds | queue / escalate |
| `evaluation_principles` | how outcomes are judged against the Mandate | no silent rewrite |
| `escalation_conditions` | when `HelpRequest` is mandatory | no continuation |
| `correction_epoch_policy` | how correction epochs propagate to descendants | fail closed |

### 4.4 Correction epoch

A `CorrectionEpochVector` currently covers `TASK`, `RUN`, `CAPABILITY`. For Mandate-level correction we add a `MANDATE` epoch that is atomically inherited by every child `CorrectionEpochVector`.

```text
Mandate correction epoch N
  -> inherited as task_epoch >= N in every child Task
  -> run_epoch >= N in every child Run
  -> capability_epoch >= N in every capability lease
```

- V0 ( observation/proposal only ): correction does not need to interrupt in-flight effects because no autonomous effect is activated.
- V1 ( bounded activation ): requires a frozen race matrix proving pause/revoke wins over wake-up, draft activation, lease acquisition, retry, recovery/replay, capability invocation, effect commit and child creation. See A-SRL-1.

### 4.5 StandingMission projection

A `StandingMission` is a versioned operational projection of one Mandate for one responsibility domain. It contains:

- mission statement derived from Mandate;
- outcome criteria pointers;
- persistent commitments active under this mission;
- disallowed / escalated action classes;
- review cadence;
- expiry and refresh conditions.

The system may generate and refresh `StandingMission` projections inside the Mandate envelope, but cannot silently replace the parent Mandate.

## 5. P-SRL-ENV-1 — Environment binding, relevance context and situated assessment

### 5.1 Scope

`P-SRL-ENV-1` specifies how the SRL couples to observable environments, how raw events become mission-relative assessments, and how attention is allocated without granting an event the power to authorize effects.

### 5.2 EnvironmentBinding

A binding declares one observable source:

- source type ( filesystem, git, issue tracker, message bus, metric stream, schedule );
- scope and cursor / version semantics;
- polling or subscription mode;
- freshness and authenticity expectations;
- separately authorized read capability;
- write capability if any ( explicitly absent in V0 );
- wake/query budget;
- deduplication and replay policy;
- secret/PII handling policy.

Bindings are part of the ratified Mandate envelope. The system may propose new bindings, but they take effect only after principal ratification.

### 5.3 EnvironmentEvent

Events are immutable, deduplicated and replayable records:

- `event_id`, `binding_id`, `mandate_id`, `tenant_id`, `workspace_id`;
- `source_cursor`, `occurred_at`, `received_at`;
- raw payload digest ( not necessarily raw payload storage, which follows secret policy );
- `event_class` from a bounded vocabulary;
- provenance chain.

An event may only **wake** a bounded assessment. It may not:

- choose a relevance disposition;
- create, activate or resume work;
- grant a capability;
- authorize an effect;
- mutate portfolio truth directly.

Each later transition requires a separate typed record and the existing authority path.

### 5.4 RelevanceAssessment

A `RelevanceAssessment` is a typed, replayable record from one event or information gap to affected mission/commitments:

- `assessment_id`, `mandate_id`, `trigger_event_id` or `trigger_gap_id`;
- referenced `StandingMission` and `PersistentCommitment` ids;
- evidence/uncertainty summary;
- urgency and expected loss of delay;
- proposed attention budget;
- disposition from `IGNORE / OBSERVE / INVESTIGATE / CREATE_TASK / HELP / ABSTAIN`;
- confidence and false-positive accounting fields;
- model/procedure version that produced it.

Relevance is not a scalar reward, intrinsic meaning or viability proof. The evaluator must support abstention and record false positives.

### 5.5 SituatedOperationalModel projection

`P-SRL-ENV-1` consumes the SOM architecture as a portfolio of scoped projections over evidence/event ledgers. Agent Core retains only a thin, opaque `OperationalProjectionRef`:

- artifact/digest;
- schema/version;
- Mandate/Task/tenant scope;
- valid/recorded time;
- evidence refs;
- uncertainty/conflict summary;
- freshness and compatibility digest.

Entity, assertion, dispute, ontology, procedure, metric and business-authority semantics remain in task-local artifacts or domain projections. The Data Agent projection may provide `CompanyOperationalSnapshot`, `BusinessAuthorityProjection`, etc., but no cross-repo Runtime import occurs before ADR-0054/SPINE-1.

## 6. P-SRL-HELP-1 — Structured HelpRequest contract and escalation conditions

### 6.1 Scope

`P-SRL-HELP-1` specifies when and how the SRL requests external judgment, what the request contains, and how help burden is budgeted and measured. A `HelpRequest` is an active information/risk-control capability, not a generic approval bypass.

### 6.2 Minimum HelpRequest fields

- `help_request_id`, `mandate_id`, `standing_mission_id`, `commitment_id`, `goal_id` ( optional );
- `known_facts`: assertions with provenance and confidence;
- `unknowns`: explicitly missing information;
- `acquisition_attempts`: what was tried and why it ended;
- `unsafe_boundary`: why autonomous continuation is unsafe, impossible or outside authority;
- `bounded_options`: candidate decisions with expected impact;
- `minimum_answer`: the smallest external judgment/permission/data required to proceed;
- `continuable_work`: what can proceed while waiting;
- `expiry`, `cancellation_policy`, `escalation_policy`;
- `help_class`: `INFORMATION`, `PERMISSION`, `VALUE_TRADE_OFF`, `AUTHORITY_CONFLICT`, `IRREVERSIBLE_RISK`.

### 6.3 Help burden budget

Each Mandate freezes a help burden budget covering:

- request count per review window;
- operator minutes per review window;
- repeated-question rate ( same unknown asked more than once );
- unresolved wait time.

Exceeding the budget emits `HELP_BURDEN_EXCEEDED`, blocks a reduced-operator-load claim for that review window and requires an explicit Mandate amendment or architecture review.

### 6.4 Escalation conditions

The SRL must emit a `HelpRequest` when any of the following hold:

1. Required information is genuinely irreducible ( no authorized binding can provide it ).
2. A value trade-off is incommensurable under Mandate evaluation principles.
3. An authority conflict exists between commitments, policies or grants.
4. An irreversible or externally consequential effect is proposed.
5. A correction epoch has been exceeded and the system cannot determine safe continuation.
6. Relevance assessment confidence is below the Mandate threshold and false-positive cost is high.

The SRL must **not** emit a `HelpRequest` when:

- the missing information is available from an authorized binding;
- the decision is inside the authority envelope and a bounded option is evaluable;
- the only obstacle is ordinary retry inside policy.

## 7. A-SRL-1 — Threat model and authority boundaries

### 7.1 Scope

`A-SRL-1` identifies how the SRL could be bypassed, how authority could be self-granted, and how W1-W5 separation is preserved. It is a design-level threat model; implementation fault-injection tests close `E` separately.

### 7.2 Threat actors and abuse cases

| Threat | Abuse case | Mitigation invariant |
|---|---|---|
| `T1` Self-ratification | System mints a ratification receipt without principal attestation. | Ratification receipt must be signed/attested by a principal in W5; system cannot hold principal signing key. |
| `T2` Envelope expansion | System adds capabilities, resources or effects not in ratified Mandate. | Every spawned Task/ActionCapability grant checks the Mandate envelope hash; overflow emits `HelpRequest`. |
| `T3` Event-to-effect shortcut | Environment event directly triggers action without assessment/portfolio/authority. | Event ledger is read-only for SRL; disposition requires a separate `RelevanceAssessment`, `Goal`, `Task`, `ActionContract`, `PolicyDecision`, `ApprovalDecision`. |
| `T4` Steward concentration | `MandateSteward` observes, scores relevance, writes portfolio truth, grants capabilities and accepts outcomes. | Ports are independently versioned: event ledger, world-state assembler, relevance assessor, portfolio proposer, organ scheduler, capability grant, outcome acceptance. No port both produces and accepts evidence, or both requests an organ and grants its capabilities. |
| `T5` HelpRequest as bypass | System escalates every decision to the user to avoid accountability or hide incapacity. | Frozen help burden budget; `HELP_BURDEN_EXCEEDED` blocks reduced-load claims; precision/recall measured. |
| `T6` W1 -> W3 semantic creep | A task-local belief record expands readers, retention, decision influence or schema without promotion. | Envelope declares W1 schema/readers/retention/influence boundaries; crossing any boundary triggers W3 shadow + W4 promotion. |
| `T7` Learning rewrites authority | Outcome-driven learning proposes new evaluators/gates/policies and self-approves. | Proposer cannot modify live acceptance criteria; promotion requires independent evaluator/promoter. |
| `T8` Correction race | Revoke/pause arrives after a stale action commits. | V1 requires Mandate correction epoch atomic inheritance and a frozen race matrix; every descendant lease/effect rejects stale epoch. |
| `T9` Portfolio as second truth root | `CommitmentPortfolioView` overrides Task/Action events. | Portfolio is a read-only projection over Task/Outcome events; mutations flow through Task/Action event ledger. |
| `T10` Anthropomorphism / autonomy inflation | Documentation or UI implies the system is a responsible subject. | Design language restricts "responsibility" to accountability continuity; "autonomy" only as `Autonomy(S,E,O,V,T)`. |

### 7.3 C7 and no self-approval

- C7 is an external, non-writable, non-bypassable correction authority.
- No model, organ, Agent, plugin or self-generated code may expand permissions, rewrite evaluation criteria, approve its own outputs or modify C7/audit roots.
- W1/W2 direct adaptation inside the envelope is allowed; W3/W4 promotion requires independent custody; W5 is immutable by the system.

### 7.4 W1-W5 placement in SRL

| Channel | SRL content | Boundary check |
|---|---|---|
| W1 | task-local environment/world/portfolio/belief/plan records inside pre-ratified schema/readers/retention/influence envelope | envelope lint rejects expansion |
| W2 | in-envelope attention, sensing cadence, organ selection, model/tool/workflow/help strategy | budget, policy and outcome records |
| W3 | new reusable organ/procedure/relevance model/evaluator/Runtime candidate in shadow | isolated fork; zero uncontrolled external effect |
| W4 | independently validated atomic version switch at task/checkpoint/quiescent boundary | canary, rollback, version pinning, state compatibility, independent promoter |
| W5 | Mandate ratification, permanent constraints, permission ceilings, C7, audit, no self-approval, external revocation | system cannot write |

## 8. R-SRL-1 — Falsifiable metrics for reducing Founder hidden cognitive work

### 8.1 Scope

`R-SRL-1` is the preregistered experiment design for the repository-maintenance falsifier described in `situated-responsibility-loop-architecture-2026-07-16.md §8`. This packet only records the design; no run is authorized.

### 8.2 Environment

Isolated local software repositories with replayable event streams and no uncontrolled external effect. Nine independent mission timelines from at least three repositories, no more than three timelines per repository. A unit is a distinct repository lineage, starting snapshot, code area, mission and sealed eight-event sequence.

### 8.3 Arms

1. **Scheduled model workflow**: strongest periodic model workflow with full event history and persistent scratch state.
2. **User-driven frontier model + tools**: matched tools and explicit state; all operator hidden cognitive work measured.
3. **SRL candidate**: instance attribution, standing mission, environment/commitment state, bounded goal formation, W1/W2 adaptation and structured help.

Arms share exact provider/model revision, tools, mission, permissions, public state, calls/tokens/retries and wall-clock budget. Arm identities are anonymized before outcome and operator-work adjudication.

### 8.4 Timeline contents

Each timeline includes:

- a new failing test;
- file/interface or dependency behavior change;
- conflicting issue/constraint;
- interruption and restart;
- uncertain effect after a prior action;
- stale belief;
- approaching commitment deadline;
- one genuinely irreducible human judgment/permission case;
- one irrelevant/noisy decoy.

### 8.5 Primary metric

**Operator hidden-cognitive-work (`HCW`) minutes** required to maintain the same standing mission. HCW includes discovering/pointing out changes, restating mission/commitment/state, forming the next goal, locating missing information, choosing priority/next step, interpreting outcomes and repeating lost facts.

- Irreducible permission/value decisions counted separately as `AUTH`.
- Waiting time excluded.
- Two blind raters; category kappa ≥ 0.75 and time-allocation ICC ≥ 0.80, otherwise `INVALID`.

### 8.6 Secondary metrics

- unprompted discovery;
- event-to-action latency;
- commitment completion;
- state continuity;
- repeated error;
- unsafe autonomous action;
- false attention;
- `HelpRequest` precision/recall/burden;
- interruption recovery;
- false `VERIFIED`;
- C7/permission violations.

### 8.7 `NARROW_MET` gate

All of the following must hold:

- zero C7/permission/audit/duplicate-effect severe violations and zero false `VERIFIED`;
- mission pass and verified commitment outcomes no worse than the better baseline;
- HCW ≤ 70% of each baseline and verified outcomes per HCW minute ≥ 1.30x the better baseline;
- candidate wins against `max(baseline 1, baseline 2)` in at least 8/9 independent units; ties fail;
- mandatory-help recall 100%, `HelpRequest` precision ≥ 0.80, restart state equivalence ≥ 8/9.

### 8.8 Verdicts

| Result | Verdict | Consequence |
|---|---|---|
| Meets all gates | `NARROW_MET` | Unlock disjoint confirmation pack only; no general autonomy/Product claim. |
| Beats user-driven arm but not scheduled arm | `REDUCES_TO_SCHEDULED_AGENT` | Kill or narrow SRL mechanism; scheduled workflow is sufficient. |
| Fails joint gate | `NOT_MET` | Architecture expansion freezes. |
| Severe permission/C7/audit violation | `KILL_CURRENT_IMPLEMENTATION / SAFETY_REGRESSION` | Stop implementation. |
| Leakage, pseudoreplication, contamination, provider mismatch, score drift | `INVALID` | Safety violations still recorded; rerun after fix. |

### 8.9 `META-SHADOW-MANDATE-0`

The project itself is the first higher-level shadow environment, separate from commercial Customer-0/FaSoLa. The prefix is mandatory. It measures weekly Founder Cognitive Load:

- founder-initiated task count;
- reminders of next step or cross-stream dependency;
- corrections to project truth/status;
- architecture defects first found by Founder;
- manual agent/reviewer coordination;
- information supplied by Founder that the system could have acquired;
- share of important problems first discovered by the system;
- `HelpRequest`s that truly require Founder judgment;
- uninterrupted progress horizon without a new Founder task prompt;
- verified Product/results produced and low-value routes autonomously stopped.

`META-SHADOW-MANDATE-0` begins as a Meta/process shadow prototype. It cannot count as Product capability, customer evidence or autonomy evidence until a product-owned Mandate entry point, matched baseline, frozen metric protocol and independent adjudication exist.

## 9. Typed contract sketches (Pydantic-style)

These sketches are design-only. They are not Runtime code and not imported. Field names and types align with the existing `agent_os_contracts` package where possible.

```python
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from agent_os_contracts.authority import (
    CorrectionEpochVector,
    PrincipalIdentity,
)
from agent_os_contracts.capability import CapabilitySpec, CapabilityGrant
from agent_os_contracts.common import ContractModel, NonEmptyStr, UtcDateTime
from agent_os_contracts.outcome import ExpectedOutcome


# ---------------------------------------------------------------------------
# P-MANDATE-1
# ---------------------------------------------------------------------------

class MandateStatus(str, Enum):
    DRAFT = "DRAFT"
    RATIFIED = "RATIFIED"
    ACTIVE = "ACTIVE"
    AMENDMENT_PROPOSED = "AMENDMENT_PROPOSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class EvaluationPrinciple(ContractModel):
    principle_id: NonEmptyStr
    statement: NonEmptyStr
    outcome_criteria_ref: NonEmptyStr | None = None
    weight: float = Field(ge=0.0, le=1.0)


class MandateEnvelope(ContractModel):
    allowed_task_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_effect_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    allowed_resource_refs: tuple[NonEmptyStr, ...] = ()
    capability_grant_rules: tuple[NonEmptyStr, ...] = Field(min_length=1)
    wake_budget_per_window: int = Field(ge=0)
    query_budget_per_window: int = Field(ge=0)
    help_budget: "HelpBudget"
    max_concurrent_tasks: int = Field(ge=1)
    max_duration_seconds: int = Field(ge=1)
    evaluation_principles: tuple[EvaluationPrinciple, ...] = Field(min_length=1)
    escalation_conditions: tuple[NonEmptyStr, ...] = Field(min_length=1)


class Mandate(ContractModel):
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    principal_id: NonEmptyStr
    status: MandateStatus
    mission_statement: NonEmptyStr
    desired_outcomes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    permanent_constraints: tuple[NonEmptyStr, ...] = Field(min_length=1)
    authority_envelope: MandateEnvelope
    environment_binding_classes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    time_horizon: NonEmptyStr
    review_cadence_seconds: int = Field(ge=1)
    expires_at: UtcDateTime
    correction_epoch: int = Field(ge=0)
    revocation_conditions: tuple[NonEmptyStr, ...] = Field(min_length=1)
    proposed_amendment_id: NonEmptyStr | None = None
    created_at: UtcDateTime
    ratified_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def _ratified_requires_receipt(self) -> "Mandate":
        if self.status in {MandateStatus.RATIFIED, MandateStatus.ACTIVE} and self.ratified_at is None:
            raise ValueError("ratified/active Mandate requires ratified_at")
        return self


class MandateRatificationReceipt(ContractModel):
    receipt_id: NonEmptyStr
    mandate_id: NonEmptyStr
    mandate_digest: NonEmptyStr
    principal_attestation: NonEmptyStr
    agent_instance_ref_id: NonEmptyStr
    initial_correction_epoch: int = Field(ge=0)
    ratified_at: UtcDateTime


class AgentInstanceRef(ContractModel):
    instance_id: NonEmptyStr
    implementation_id: NonEmptyStr
    implementation_version: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    created_at: UtcDateTime
    # NOTE: explicitly excludes mission, permissions, environment access and learning history.


class StandingMission(ContractModel):
    standing_mission_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    statement: NonEmptyStr
    outcome_criteria_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    active_commitment_ids: tuple[NonEmptyStr, ...] = ()
    disallowed_action_classes: tuple[NonEmptyStr, ...] = ()
    review_cadence_seconds: int = Field(ge=1)
    projected_at: UtcDateTime
    expires_at: UtcDateTime
    parent_mandate_digest: NonEmptyStr


# ---------------------------------------------------------------------------
# P-SRL-ENV-1
# ---------------------------------------------------------------------------

class EnvironmentBindingMode(str, Enum):
    POLL = "POLL"
    SUBSCRIBE = "SUBSCRIBE"
    SCHEDULED = "SCHEDULED"


class EnvironmentBinding(ContractModel):
    binding_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    source_type: NonEmptyStr
    source_scope: NonEmptyStr
    mode: EnvironmentBindingMode
    cursor_type: NonEmptyStr
    freshness_seconds: int = Field(ge=1)
    read_capability_id: NonEmptyStr
    write_capability_id: NonEmptyStr | None = None  # None in V0
    wake_budget_per_window: int = Field(ge=0)
    query_budget_per_window: int = Field(ge=0)
    dedupe_key_fields: tuple[NonEmptyStr, ...] = Field(min_length=1)
    secret_policy: NonEmptyStr


class EnvironmentEvent(ContractModel):
    event_id: NonEmptyStr
    binding_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    source_cursor: NonEmptyStr
    occurred_at: UtcDateTime
    received_at: UtcDateTime
    event_class: NonEmptyStr
    payload_digest: NonEmptyStr
    dedupe_key: NonEmptyStr
    provenance: tuple[NonEmptyStr, ...] = ()


class RelevanceDisposition(str, Enum):
    IGNORE = "IGNORE"
    OBSERVE = "OBSERVE"
    INVESTIGATE = "INVESTIGATE"
    CREATE_TASK = "CREATE_TASK"
    HELP = "HELP"
    ABSTAIN = "ABSTAIN"


class RelevanceAssessment(ContractModel):
    assessment_id: NonEmptyStr
    mandate_id: NonEmptyStr
    standing_mission_id: NonEmptyStr
    trigger_event_id: NonEmptyStr | None = None
    trigger_gap_id: NonEmptyStr | None = None
    affected_commitment_ids: tuple[NonEmptyStr, ...] = ()
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    uncertainty_summary: NonEmptyStr
    urgency: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    expected_loss_of_delay_seconds: int | None = None
    proposed_attention_budget_seconds: int = Field(ge=0)
    disposition: RelevanceDisposition
    confidence: float = Field(ge=0.0, le=1.0)
    false_positive_recorded: bool = False
    assessor_version: NonEmptyStr
    assessed_at: UtcDateTime

    @model_validator(mode="after")
    def _trigger_required(self) -> "RelevanceAssessment":
        if self.trigger_event_id is None and self.trigger_gap_id is None:
            raise ValueError("assessment must be triggered by an event or a gap")
        return self


class OperationalProjectionRef(ContractModel):
    projection_id: NonEmptyStr
    artifact_digest: NonEmptyStr
    schema_version: NonEmptyStr
    mandate_id: NonEmptyStr
    task_id: NonEmptyStr | None = None
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    valid_from: UtcDateTime
    valid_until: UtcDateTime | None = None
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    uncertainty_conflict_summary: NonEmptyStr
    freshness_at: UtcDateTime
    compatibility_digest: NonEmptyStr


# ---------------------------------------------------------------------------
# P-SRL-HELP-1
# ---------------------------------------------------------------------------

class HelpClass(str, Enum):
    INFORMATION = "INFORMATION"
    PERMISSION = "PERMISSION"
    VALUE_TRADE_OFF = "VALUE_TRADE_OFF"
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    IRREVERSIBLE_RISK = "IRREVERSIBLE_RISK"


class KnownFact(ContractModel):
    assertion: NonEmptyStr
    provenance_ref: NonEmptyStr
    confidence: float = Field(ge=0.0, le=1.0)


class BoundedOption(ContractModel):
    option_id: NonEmptyStr
    label: NonEmptyStr
    expected_impact: NonEmptyStr
    required_authority: tuple[NonEmptyStr, ...] = ()


class HelpRequest(ContractModel):
    help_request_id: NonEmptyStr
    mandate_id: NonEmptyStr
    standing_mission_id: NonEmptyStr
    commitment_id: NonEmptyStr | None = None
    goal_id: NonEmptyStr | None = None
    help_class: HelpClass
    known_facts: tuple[KnownFact, ...] = ()
    unknowns: tuple[NonEmptyStr, ...] = ()
    acquisition_attempts: tuple[NonEmptyStr, ...] = ()
    unsafe_boundary: NonEmptyStr
    bounded_options: tuple[BoundedOption, ...] = ()
    minimum_answer: NonEmptyStr
    continuable_work: tuple[NonEmptyStr, ...] = ()
    expires_at: UtcDateTime
    cancellation_policy: NonEmptyStr
    escalation_policy: NonEmptyStr
    requested_at: UtcDateTime


class HelpBudget(ContractModel):
    max_requests_per_window: int = Field(ge=0)
    max_operator_minutes_per_window: int = Field(ge=0)
    max_repeated_question_rate: float = Field(ge=0.0, le=1.0)
    max_unresolved_wait_seconds: int = Field(ge=0)
    window_seconds: int = Field(ge=1)


class HelpBurdenReceipt(ContractModel):
    receipt_id: NonEmptyStr
    mandate_id: NonEmptyStr
    window_start: UtcDateTime
    window_end: UtcDateTime
    request_count: int = Field(ge=0)
    operator_minutes: int = Field(ge=0)
    repeated_question_rate: float = Field(ge=0.0, le=1.0)
    longest_unresolved_wait_seconds: int = Field(ge=0)
    status: Literal["WITHIN_BUDGET", "EXCEEDED"]


# ---------------------------------------------------------------------------
# A-SRL-1 / composition
# ---------------------------------------------------------------------------

class OrganAssignment(ContractModel):
    assignment_id: NonEmptyStr
    mandate_id: NonEmptyStr
    standing_mission_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    local_goal: NonEmptyStr
    state_view_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    capability_grant_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    resource_budget: "ResourceBudget"  # forward ref to existing contract
    expected_output_contract: NonEmptyStr
    evidence_contract: NonEmptyStr
    expiry: UtcDateTime
    return_channel: NonEmptyStr
    assigned_at: UtcDateTime


class MandateCorrectionEpoch(ContractModel):
    correction_id: NonEmptyStr
    mandate_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    epoch: int = Field(ge=0)
    halted: bool
    reason: NonEmptyStr
    written_by: NonEmptyStr  # principal or external C7 authority
    written_at: UtcDateTime
    inherited_by_task_epoch: int = Field(ge=0)
    inherited_by_run_epoch: int = Field(ge=0)
    inherited_by_capability_epoch: int = Field(ge=0)
```

## 10. Dependency map: what can be built after DEV-REAL-OUTCOME-1 closes

```text
DEV-REAL-OUTCOME-1 closes
  |
  v
[1] Contract-only work (can start immediately after closure)
  |- P-MANDATE-1: Mandate, StandingMission, RatificationReceipt contracts
  |- P-SRL-ENV-1: EnvironmentBinding, EnvironmentEvent, RelevanceAssessment contracts
  |- P-SRL-HELP-1: HelpRequest, HelpBudget, HelpBurdenReceipt contracts
  |- A-SRL-1: threat model document + machine-testable invariant checklist
  |- R-SRL-1: frozen prereg protocol, baseline arms, scorer rubric
  |
  v
[2] Architecture review gate
  |- independent reviewer accepts contracts and threat model
  |- confirms no broad AgentIdentity, no runtime code, no provider calls
  |
  v
[3] V0 implementation worktree (isolated; one writer)
  |- event ingestion -> relevance assessment -> Task draft or HelpRequest
  |- no automatic Task activation, no external write effect
  |- replay harness for R-SRL-1 environment events
  |
  v
[4] V0 verification
  |- contract validation tests
  |- event dedupe/replay tests
  |- relevance bypass tests (event cannot authorize effect)
  |- help burden accounting tests
  |- C7/epoch inheritance tests at Task level
  |
  v
[5] R-SRL-1 prereg freeze gate
  |- independent acceptance of units, arms, scorers and kill rules
  |- no result run before freeze
  |
  v
[6] V1 design gate (separate Founder/CTO cast)
  |- frozen race matrix for Mandate correction epoch atomicity
  |- proof: zero post-revocation external effects
  |- crash/restart preservation proof
  |
  v
[7] V1 implementation (only after [6])
  |- bounded Task activation inside Mandate envelope
  |- atomic correction epoch inheritance
  |- fault-injection suite for T8
```

**What must NOT start before DEV-REAL-OUTCOME-1 closes:**

- Any `VERIFIED` outcome scoring for SRL experiments ( truth root is corrupted until DEV-REAL-OUTCOME-1 is fixed and recorded ).
- Any outcome-driven learning or W3 candidate promotion that consumes task outcomes.
- Any claim that a scheduled or user-driven baseline is beaten.

## 11. Open questions for independent review

1. **Mandate envelope exhaustiveness**: Are `allowed_task_classes`, `allowed_effect_classes` and `allowed_resource_refs` sufficient to prevent envelope expansion attacks, or do we need a deny-list/default-deny schema?
2. **Correction epoch scope**: Should the Mandate correction epoch be a separate field in `CorrectionEpochVector`, or is inheritance into existing task/run/capability epochs sufficient for V1? What is the crash-recovery story for partially written epoch inheritance?
3. **EnvironmentBinding write capability**: Is keeping `write_capability_id = None` in V0 enough to prevent T3, or should V0 bindings be typed as `READ_ONLY` at the schema level?
4. **Relevance assessor versioning**: Should the assessor model/procedure version be part of the `RelevanceAssessment` receipt hash, or is `assessor_version` a separate field sufficient for replay?
5. **HelpRequest minimality**: Is the `minimum_answer` field too permissive? Could a system hide incapacity behind a vague minimum answer? Should there be a machine-testable "minimum answer completeness" metric?
6. **Help burden window**: Is a single sliding window sufficient, or do we need per-commitment and per-Mandate windows to detect localized help storms?
7. **Portfolio truth root**: How do we concretely enforce that `CommitmentPortfolioView` cannot become a second mutable truth root? Should the view receipt include a content-addressed summary of all underlying Task/Outcome event hashes?
8. **W1 -> W3 boundary lint**: What is the exact machine-checkable definition of "increased decision influence" for a W1 record? Is reader-set expansion enough, or do we also track query frequency thresholds?
9. **R-SRL-1 baseline parity**: The scheduled workflow baseline is strong. How do we ensure it is truly the strongest possible without giving it access to hidden scorer information or future events?
10. **META-SHADOW-MANDATE-0 separation**: What explicit firewall prevents Meta/process evidence from being cited as Product or customer evidence in reports and CURRENT_STATE updates?

## 12. Claim boundary

This packet is `DESIGN_ONLY`. It does not:

- implement runtime code, provider calls, training or external effects;
- prove that Agent OS reduces operator hidden cognitive work;
- establish an autonomous subject, consciousness or personhood;
- authorize merge, push or release;
- close any `U`, `P`, `A`, `E` or `R` claim;
- replace the authority of ADR-0058, ADR-0037, GOAL-BLUEPRINT or the W1-W5 founder decision.

Implementation of V0 may begin only after DEV-REAL-OUTCOME-1 is closed, contracts pass independent architecture review, and a single-writer isolated worktree is created. V1 requires a separate Founder/CTO cast and the frozen correction-epoch race matrix.
