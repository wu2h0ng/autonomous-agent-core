from __future__ import annotations

import json
from enum import Enum
from typing import Any, Mapping

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime, canonical_json
from .evidence import Sha256Digest


class TaskStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_EVENT = "WAITING_EVENT"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CompensationMode(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class CompensationStatus(str, Enum):
    STARTED = "STARTED"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class TaskEventType(str, Enum):
    TASK_CREATED = "TASK_CREATED"
    TASK_COMMITTED = "TASK_COMMITTED"
    TASK_CONFIGURATION_SNAPSHOT_SEALED = "TASK_CONFIGURATION_SNAPSHOT_SEALED"
    RUN_STARTED = "RUN_STARTED"
    RUN_QUEUED = "RUN_QUEUED"
    NODE_STARTED = "NODE_STARTED"
    NODE_COMPLETED = "NODE_COMPLETED"
    NODE_FAILED = "NODE_FAILED"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    CANDIDATES_GENERATED = "CANDIDATES_GENERATED"
    PROVIDER_RESPONDED = "PROVIDER_RESPONDED"
    PROVIDER_ATTEMPT_FAILED = "PROVIDER_ATTEMPT_FAILED"
    POLICY_DECIDED = "POLICY_DECIDED"
    ACTION_RECEIPT_RECORDED = "ACTION_RECEIPT_RECORDED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    CORRECTION_WRITTEN = "CORRECTION_WRITTEN"
    OUTCOME_OBSERVED = "OUTCOME_OBSERVED"
    ARTIFACT_RECORDED = "ARTIFACT_RECORDED"
    RUN_PAUSED = "RUN_PAUSED"
    RUN_RESUMED = "RUN_RESUMED"
    RUN_CANCELLED = "RUN_CANCELLED"
    RUN_SUCCEEDED = "RUN_SUCCEEDED"
    RUN_FAILED = "RUN_FAILED"
    WAIT_REGISTERED = "WAIT_REGISTERED"
    EXTERNAL_SIGNAL_RECORDED = "EXTERNAL_SIGNAL_RECORDED"
    WAIT_SATISFIED = "WAIT_SATISFIED"
    WAIT_TIMED_OUT = "WAIT_TIMED_OUT"
    COMMITMENT_EXPIRED = "COMMITMENT_EXPIRED"
    RUN_PLAN_REBOUND = "RUN_PLAN_REBOUND"
    COMPENSATION_STARTED = "COMPENSATION_STARTED"
    ACTION_COMPENSATED = "ACTION_COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    COMPENSATION_BLOCKED = "COMPENSATION_BLOCKED"
    SESSION_TURN_STARTED = "SESSION_TURN_STARTED"
    SESSION_TURN_COMPLETED = "SESSION_TURN_COMPLETED"
    SESSION_OPENED = "SESSION_OPENED"
    SESSION_MESSAGE_RECORDED = "SESSION_MESSAGE_RECORDED"
    SESSION_APPROVAL_PENDING = "SESSION_APPROVAL_PENDING"
    SESSION_APPROVAL_EXECUTION_CLAIMED = "SESSION_APPROVAL_EXECUTION_CLAIMED"
    SESSION_APPROVAL_RESOLVED = "SESSION_APPROVAL_RESOLVED"
    SESSION_TURN_CONTINUATION_CHECKPOINT = "SESSION_TURN_CONTINUATION_CHECKPOINT"
    SESSION_CONTEXT_COMPACTED = "SESSION_CONTEXT_COMPACTED"
    SESSION_PERMISSION_MODE_SET = "SESSION_PERMISSION_MODE_SET"
    POLICY_VERDICT_RECORDED = "POLICY_VERDICT_RECORDED"
    SESSION_CLOSED = "SESSION_CLOSED"
    # Form B child agents (additive, 2026-09-19). CHILD_AGENT_SPAWNED carries
    # ChildAgentSpawned; CHILD_AGENT_FINISHED carries ChildAgentFinished. Both
    # are digest-only: never prompt or completion text.
    CHILD_AGENT_SPAWNED = "CHILD_AGENT_SPAWNED"
    CHILD_AGENT_FINISHED = "CHILD_AGENT_FINISHED"
    # Additive (2026-09-19, kernel slice): the operator-declared reconciliation
    # of a child whose runtime generation is gone. It carries the typed burial
    # block (reason_code/declared_by/outcome) plus the exact durable fields the
    # declaration binds; it never carries prompt or completion text.
    CHILD_AGENT_RECONCILED = "CHILD_AGENT_RECONCILED"
    # Additive (2026-09-19, checkpoint P0 forward form): an append-only,
    # operator-named durable marker in the session event stream. It records a
    # replayable reference to (sequence, turn_id, state_digest) so a crashed
    # process can reconstruct the session state by re-projecting the stream
    # FORWARD from this point. It never deletes or rewrites history, and it
    # never carries prompt or completion text.
    SESSION_CHECKPOINT_RECORDED = "SESSION_CHECKPOINT_RECORDED"
    # Additive (2026-09-19, checkpoint P0 "fork" form): the append-only lineage
    # record of a NEW session that branches from a named checkpoint on a parent
    # session. It binds (parent_session_id, parent_task_id, checkpoint_sequence,
    # checkpoint_label, parent_state_digest) so the new session can always trace
    # its provenance. It NEVER deletes or rewrites the parent's events (the
    # parent is closed read-only) and NEVER carries prompt or completion text.
    # This is the only "rewind" the append-only evidence spine allows: a new
    # epoch that starts at the checkpoint, not a time-travel mutation.
    SESSION_FORKED_FROM_CHECKPOINT = "SESSION_FORKED_FROM_CHECKPOINT"


class WaitCondition(ContractModel):
    node_id: NonEmptyStr
    signal_name: NonEmptyStr
    correlation_key: NonEmptyStr
    registered_at: UtcDateTime
    deadline: UtcDateTime

    @model_validator(mode="after")
    def _validate_deadline(self) -> WaitCondition:
        if self.deadline <= self.registered_at:
            raise ValueError("wait deadline must be after registered_at")
        return self


class ExternalSignal(ContractModel):
    signal_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    signal_name: NonEmptyStr
    correlation_key: NonEmptyStr
    payload_json: NonEmptyStr
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    occurred_at: UtcDateTime

    @field_validator("payload_json", mode="after")
    @classmethod
    def _canonicalize_payload_json(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("signal payload_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("signal payload_json must encode an object")
        return canonical_json(payload)

    @field_validator("evidence_refs", mode="after")
    @classmethod
    def _normalize_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    def decoded_payload(self) -> dict[str, Any]:
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("signal payload_json must encode an object")
        return payload


class RunPlanRebound(ContractModel):
    rebound_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    previous_workflow_version: int = Field(ge=1)
    previous_workflow_digest: NonEmptyStr
    new_workflow_version: int = Field(ge=2)
    new_workflow_digest: NonEmptyStr
    preserved_node_ids: tuple[NonEmptyStr, ...] = ()
    invalidated_node_ids: tuple[NonEmptyStr, ...] = ()
    new_node_ids: tuple[NonEmptyStr, ...] = ()
    requested_by: NonEmptyStr
    reason: NonEmptyStr
    created_at: UtcDateTime

    @field_validator(
        "preserved_node_ids", "invalidated_node_ids", "new_node_ids", mode="after"
    )
    @classmethod
    def _normalize_node_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_versions_and_sets(self) -> RunPlanRebound:
        if self.new_workflow_version != self.previous_workflow_version + 1:
            raise ValueError("rebound workflow version must increase by exactly one")
        groups = (
            set(self.preserved_node_ids),
            set(self.invalidated_node_ids),
            set(self.new_node_ids),
        )
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("rebound node sets must be disjoint")
        return self


class PatchCompensationRecord(ContractModel):
    compensation_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    node_id: NonEmptyStr
    original_action_id: NonEmptyStr
    compensation_action_id: NonEmptyStr | None = None
    compensation_ref: NonEmptyStr | None = None
    manifest_sha256: Sha256Digest | None = None
    mode: CompensationMode
    status: CompensationStatus
    reason: NonEmptyStr
    manual_intervention_required: bool = False
    receipt_id: NonEmptyStr | None = None
    created_at: UtcDateTime

    @model_validator(mode="after")
    def _validate_compensation_state(self) -> PatchCompensationRecord:
        if self.status in {
            CompensationStatus.STARTED,
            CompensationStatus.COMPENSATED,
        } and (
            self.compensation_action_id is None
            or self.compensation_ref is None
            or self.manifest_sha256 is None
        ):
            raise ValueError(
                "started/compensated record requires action and snapshot bindings"
            )
        if self.status is CompensationStatus.COMPENSATED and self.receipt_id is None:
            raise ValueError("compensated record requires receipt_id")
        if (
            self.status
            in {
                CompensationStatus.FAILED,
                CompensationStatus.BLOCKED,
            }
            and not self.manual_intervention_required
        ):
            raise ValueError(
                "failed/blocked record requires manual_intervention_required"
            )
        if (
            self.status
            in {
                CompensationStatus.STARTED,
                CompensationStatus.COMPENSATED,
            }
            and self.manual_intervention_required
        ):
            raise ValueError(
                "active/successful compensation cannot require manual intervention"
            )
        return self


class RunRecoverySnapshot(ContractModel):
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    event_sequence: int = Field(ge=1)
    run_resumed_count: int = Field(default=0, ge=0)
    wait_registered_count: int = Field(default=0, ge=0)
    signal_satisfied_count: int = Field(default=0, ge=0)
    replan_count: int = Field(default=0, ge=0)
    compensation_count: int = Field(default=0, ge=0)
    action_receipt_count: int = Field(default=0, ge=0)
    unique_logical_action_count: int = Field(default=0, ge=0)
    outcome_status: NonEmptyStr | None = None


class TaskEventDraft(ContractModel):
    event_id: NonEmptyStr
    task_id: NonEmptyStr
    event_type: TaskEventType
    payload_json: NonEmptyStr
    occurred_at: UtcDateTime
    correlation_id: NonEmptyStr | None = None
    causation_id: NonEmptyStr | None = None

    @field_validator("payload_json", mode="after")
    @classmethod
    def _canonicalize_payload_json(cls, value: str) -> str:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("event payload_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("event payload_json must encode an object")
        return canonical_json(payload)

    @classmethod
    def build(
        cls,
        *,
        event_id: str,
        task_id: str,
        event_type: TaskEventType,
        payload: Mapping[str, Any],
        occurred_at: UtcDateTime,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> TaskEventDraft:
        return cls(
            event_id=event_id,
            task_id=task_id,
            event_type=event_type,
            payload_json=canonical_json(payload),
            occurred_at=occurred_at,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

    def decoded_payload(self) -> dict[str, Any]:
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("event payload_json must encode an object")
        return payload


class TaskEvent(TaskEventDraft):
    sequence: int = Field(ge=1)


class AgentRun(ContractModel):
    run_id: NonEmptyStr
    task_id: NonEmptyStr
    commitment_id: NonEmptyStr
    workflow_id: NonEmptyStr
    workflow_version: int = Field(ge=1)
    workflow_digest: NonEmptyStr
    expected_outcome_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    status: RunStatus = RunStatus.CREATED
    created_at: UtcDateTime
    provider_profile_id: NonEmptyStr = "provider-profile:unbound"
    policy_version: NonEmptyStr = "policy-1"
    lease_fence: int = Field(default=0, ge=0)
    active_node_id: str | None = None
    attempt: int = Field(default=1, ge=1)
    wait_condition: WaitCondition | None = None
    replan_count: int = Field(default=0, ge=0)
    configuration_snapshot_id: NonEmptyStr | None = None
    configuration_snapshot_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def _validate_configuration_snapshot_pair(self) -> AgentRun:
        if (self.configuration_snapshot_id is None) != (
            self.configuration_snapshot_digest is None
        ):
            raise ValueError(
                "configuration snapshot id and digest must be provided together"
            )
        return self
