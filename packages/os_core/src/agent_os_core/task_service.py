from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ActionReceipt,
    AgentRun,
    ApprovalDecision,
    ApprovalDisposition,
    Commitment,
    ExpectedOutcome,
    ExternalSignal,
    Goal,
    NodeKind,
    NodeSpec,
    RunPlanRebound,
    RunStatus,
    TaskStatus,
    TaskConfigurationSnapshot,
    WorkflowGraph,
    WaitCondition,
    TaskEventDraft,
    TaskEventType,
    ObservedOutcome,
    OutcomeStatus,
    PolicyDecision,
    PolicyVerdict,
    ProviderMessage,
    ProviderMessageRole,
    ProviderToolProposal,
    ProviderExecutionReceipt,
    ReceiptStatus,
    SessionRef,
)

from .errors import (
    CommitmentExpiredError,
    ConcurrentWriteError,
    InvalidTransitionError,
    ReplanRejectedError,
    SignalMismatchError,
    TaskNotFoundError,
    WaitExpiredError,
)
from .event_store import TaskEventStore
from .governance import CorrectionGuard
from .session_projection import (
    ProjectedApprovalContinuation,
    ProjectedSession,
    SessionLoopConfig,
    SessionProjectionError,
    SessionProjector,
)
from .task_aggregate import TaskAggregate


IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]
ArtifactReader = Callable[[str], bytes | None]


PYTEST_EVALUATOR_IDENTITY = ("pytest", "1")
PYTEST_EVIDENCE_REQUIREMENTS = ("test-report",)
PYTEST_FAILURE_SEMANTICS = frozenset(
    {"non-zero exit", "test command exits non-zero", "tests fail"}
)
PROTECTED_TRUTH_EVENTS = frozenset(
    {
        TaskEventType.ACTION_RECEIPT_RECORDED,
        TaskEventType.ARTIFACT_RECORDED,
        TaskEventType.OUTCOME_OBSERVED,
        TaskEventType.SESSION_APPROVAL_PENDING,
        TaskEventType.SESSION_APPROVAL_RESOLVED,
    }
)


@dataclass(frozen=True)
class ValidatedTestReport:
    artifact_ids: tuple[str, ...]
    exit_code: int
    node_id: str
    action_id: str
    receipt_id: str
    completed_sequence: int
    completed_at: datetime
    node_ids: tuple[str, ...] = ()


def expected_outcome_contract_error(expected: ExpectedOutcome) -> str | None:
    if (
        expected.evaluator_type,
        expected.evaluator_version,
    ) != PYTEST_EVALUATOR_IDENTITY:
        return "unsupported evaluator"
    if tuple(expected.evidence_requirements) != PYTEST_EVIDENCE_REQUIREMENTS:
        return "unsupported evidence requirements"
    if (
        not expected.failure_semantics
        or len(set(expected.failure_semantics)) != len(expected.failure_semantics)
        or not set(expected.failure_semantics).issubset(PYTEST_FAILURE_SEMANTICS)
    ):
        return "unsupported failure semantics"
    return None


def _default_id_factory(kind: str) -> str:
    return f"{kind}-{uuid4()}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskService:
    def __init__(
        self,
        event_store: TaskEventStore,
        *,
        id_factory: IdFactory = _default_id_factory,
        clock: Clock = _utc_now,
        artifact_reader: ArtifactReader | None = None,
    ) -> None:
        self._event_store = event_store
        self._id_factory = id_factory
        self._clock = clock
        self._artifact_reader = artifact_reader
        self._correction_reader: CorrectionGuard | None = None
        self._runtime_writer_token = object()

    def bind_artifact_reader(self, artifact_reader: ArtifactReader) -> None:
        self._artifact_reader = artifact_reader

    def bind_correction_reader(self, correction_reader: CorrectionGuard) -> None:
        self._correction_reader = correction_reader

    def now(self) -> datetime:
        return self._clock()

    def create_task(self, goal: Goal) -> TaskAggregate:
        task_id = self._id_factory("task")
        draft = TaskAggregate.create_task(
            task_id=task_id,
            goal=goal,
            event_id=self._id_factory("event"),
            occurred_at=self._clock(),
        )
        self._event_store.append(task_id, expected_sequence=0, drafts=(draft,))
        return self.get_task(task_id)

    def commit_task(
        self,
        task_id: str,
        commitment: Commitment,
        workflow: WorkflowGraph,
        expected_outcome: ExpectedOutcome,
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        draft = aggregate.commit(
            commitment,
            workflow,
            expected_outcome,
            event_id=self._id_factory("event"),
            occurred_at=self._clock(),
        )
        self._event_store.append(
            task_id,
            expected_sequence=aggregate.sequence,
            drafts=(draft,),
        )
        return self.get_task(task_id)

    def seal_configuration_snapshot(
        self,
        task_id: str,
        snapshot: TaskConfigurationSnapshot,
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if aggregate.configuration_snapshot is not None:
            if aggregate.configuration_snapshot == snapshot:
                return aggregate
            raise InvalidTransitionError(
                "configuration snapshot is already sealed with different content"
            )
        draft = aggregate.seal_configuration_snapshot(
            snapshot,
            event_id=self._id_factory("event"),
            occurred_at=self._clock(),
        )
        self._event_store.append(
            task_id,
            expected_sequence=aggregate.sequence,
            drafts=(draft,),
        )
        return self.get_task(task_id)

    def start_run(
        self,
        task_id: str,
        *,
        provider_profile_id: str = "provider-profile:unbound",
        configuration_snapshot_id: str | None = None,
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if aggregate.status is not TaskStatus.COMMITTED:
            raise InvalidTransitionError(
                f"cannot start task from "
                f"{aggregate.status.value if aggregate.status else 'NONE'}"
            )
        if (
            aggregate.commitment is None
            or aggregate.workflow is None
            or aggregate.expected_outcome is None
        ):
            raise InvalidTransitionError("task is missing committed contracts")
        if self._clock() >= aggregate.commitment.expires_at:
            raise CommitmentExpiredError("commitment expired before run start")

        snapshot = aggregate.configuration_snapshot
        if snapshot is not None:
            if configuration_snapshot_id != snapshot.snapshot_id:
                raise InvalidTransitionError(
                    "exact configuration snapshot id is required before run start"
                )
            if (
                provider_profile_id != "provider-profile:unbound"
                and provider_profile_id != snapshot.provider_profile.profile_id
            ):
                raise InvalidTransitionError(
                    "provider profile does not match configuration snapshot"
                )
            resolved_run_id = snapshot.reserved_run_id
            resolved_provider_profile_id = snapshot.provider_profile.profile_id
        else:
            if configuration_snapshot_id is not None:
                raise InvalidTransitionError(
                    "configuration snapshot id was supplied for an unsealed task"
                )
            resolved_run_id = self._id_factory("run")
            resolved_provider_profile_id = provider_profile_id

        run = AgentRun(
            run_id=resolved_run_id,
            task_id=task_id,
            commitment_id=aggregate.commitment.commitment_id,
            workflow_id=aggregate.workflow.workflow_id,
            workflow_version=aggregate.workflow.version,
            workflow_digest=aggregate.workflow.canonical_digest(),
            expected_outcome_id=aggregate.expected_outcome.expected_outcome_id,
            tenant_id=aggregate.commitment.tenant_id,
            workspace_id=aggregate.commitment.workspace_id,
            status=RunStatus.QUEUED,
            created_at=self._clock(),
            provider_profile_id=resolved_provider_profile_id,
            policy_version=aggregate.workflow.policy_version,
            configuration_snapshot_id=(
                snapshot.snapshot_id if snapshot is not None else None
            ),
            configuration_snapshot_digest=(
                snapshot.snapshot_digest if snapshot is not None else None
            ),
        )
        draft = aggregate.start(
            run,
            event_id=self._id_factory("event"),
            occurred_at=self._clock(),
        )
        self._event_store.append(
            task_id,
            expected_sequence=aggregate.sequence,
            drafts=(draft,),
        )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> TaskAggregate:
        events = self._event_store.read(task_id)
        if not events:
            raise TaskNotFoundError(f"task not found: {task_id}")
        return TaskAggregate.rehydrate(events)

    def current_outcome(self, task_id: str) -> ObservedOutcome | None:
        """Project current outcome truth without rewriting historical events."""

        aggregate = self.get_task(task_id)
        outcome = aggregate.observed_outcome
        expected = aggregate.expected_outcome
        run = aggregate.run
        if (
            outcome is None
            or outcome.status is not OutcomeStatus.VERIFIED
            or expected is None
            or run is None
        ):
            return outcome
        report = self.validated_test_report(task_id, run.run_id)
        score = outcome.score
        evidence_is_current = (
            report is not None
            and report.exit_code == 0
            and set(report.artifact_ids).issubset(outcome.evidence_refs)
            and score is not None
            and score == 1.0
            and score >= expected.threshold
            and expected.frozen_at <= report.completed_at <= outcome.observed_at
            and expected.frozen_at
            <= outcome.observed_at
            <= expected.frozen_at
            + timedelta(seconds=expected.observation_window_seconds)
        )
        if evidence_is_current:
            return outcome
        return ObservedOutcome(
            observed_outcome_id=f"current-{outcome.observed_outcome_id}",
            expected_outcome_id=outcome.expected_outcome_id,
            task_id=outcome.task_id,
            run_id=outcome.run_id,
            tenant_id=outcome.tenant_id,
            workspace_id=outcome.workspace_id,
            evaluator_type=outcome.evaluator_type,
            evaluator_version=outcome.evaluator_version,
            status=OutcomeStatus.UNRESOLVED,
            score=None,
            confidence=1.0,
            evidence_refs=outcome.evidence_refs,
            unresolved_gaps=("verified evidence is no longer currently valid",),
            observed_at=self._clock(),
        )

    def append_event(
        self,
        task_id: str,
        event_type: TaskEventType,
        payload: dict[str, object],
        *,
        correlation_id: str | None = None,
    ) -> TaskAggregate:
        if event_type in PROTECTED_TRUTH_EVENTS:
            raise InvalidTransitionError(
                f"protected event requires a typed writer: {event_type.value}"
            )
        return self._append_event(
            task_id,
            event_type,
            payload,
            correlation_id=correlation_id,
        )

    def record_provider_response(
        self,
        task_id: str,
        *,
        node_id: str,
        provider_output: dict[str, object],
        receipt: ProviderExecutionReceipt,
    ) -> TaskAggregate:
        """Append one receipt-anchored provider response through a typed writer."""

        aggregate = self.get_task(task_id)
        run = aggregate.run
        if run is None:
            raise InvalidTransitionError("provider response requires an active Run")
        if (
            receipt.source_event_id == aggregate.last_event_id
            or receipt.node_id != node_id
            or receipt.task_id != task_id
            or receipt.run_id != run.run_id
            or receipt.tenant_id != run.tenant_id
            or receipt.workspace_id != run.workspace_id
            or receipt.provider_profile_id != run.provider_profile_id
        ):
            raise InvalidTransitionError("provider response receipt binding mismatch")
        draft = TaskEventDraft.build(
            event_id=receipt.source_event_id,
            task_id=task_id,
            event_type=TaskEventType.PROVIDER_RESPONDED,
            payload={
                "node_id": node_id,
                "provider_output": provider_output,
                "provider_execution_receipt": receipt.model_dump(mode="json"),
            },
            occurred_at=self._clock(),
            correlation_id=run.run_id,
            causation_id=aggregate.last_event_id,
        )
        self._event_store.append(
            task_id,
            expected_sequence=aggregate.sequence,
            drafts=(draft,),
        )
        return self.get_task(task_id)

    def _append_event(
        self,
        task_id: str,
        event_type: TaskEventType,
        payload: dict[str, object],
        *,
        correlation_id: str | None = None,
        writer_token: object | None = None,
    ) -> TaskAggregate:
        if (
            event_type in PROTECTED_TRUTH_EVENTS
            and writer_token is not self._runtime_writer_token
        ):
            raise InvalidTransitionError(
                f"protected event requires a typed writer: {event_type.value}"
            )
        aggregate = self.get_task(task_id)
        draft = TaskEventDraft.build(
            event_id=self._id_factory("event"),
            task_id=task_id,
            event_type=event_type,
            payload=payload,
            occurred_at=self._clock(),
            correlation_id=correlation_id or task_id,
            causation_id=aggregate.last_event_id,
        )
        self._event_store.append(
            task_id, expected_sequence=aggregate.sequence, drafts=(draft,)
        )
        return self.get_task(task_id)

    def open_session(
        self,
        ref: SessionRef,
        envelope_id: str,
        expected_outcome_id: str,
        *,
        loop_config: SessionLoopConfig,
    ) -> TaskAggregate:
        if not envelope_id.strip() or not expected_outcome_id.strip():
            raise ValueError("session envelope and expected outcome must be non-empty")
        aggregate = self.get_task(ref.task_id)
        self._validate_session_binding(aggregate, ref, expected_outcome_id)
        try:
            SessionProjector(self._event_store).project(ref.task_id, ref.session_id)
        except SessionProjectionError as exc:
            if str(exc) != "session not found":
                raise
        else:
            raise InvalidTransitionError("session is already open")
        return self._append_event(
            ref.task_id,
            TaskEventType.SESSION_OPENED,
            {
                "session_id": ref.session_id,
                "task_id": ref.task_id,
                "run_id": ref.run_id,
                "tenant_id": ref.tenant_id,
                "workspace_id": ref.workspace_id,
                "session": ref.model_dump(mode="json"),
                "envelope_id": envelope_id,
                "expected_outcome_id": expected_outcome_id,
                "agent_loop_config": loop_config.payload(),
                "agent_loop_config_digest": loop_config.digest(),
            },
            correlation_id=ref.session_id,
        )

    def record_session_message(
        self,
        task_id: str,
        session_id: str,
        message_index: int,
        message: ProviderMessage,
        *,
        turn_id: str | None,
    ) -> TaskAggregate:
        if message_index < 0:
            raise ValueError("message_index must be non-negative")
        aggregate = self.get_task(task_id)
        projected = SessionProjector(self._event_store).project(task_id, session_id)
        self._validate_session_binding(
            aggregate,
            projected.ref,
            projected.expected_outcome_id,
        )
        if projected.closed:
            raise InvalidTransitionError("cannot record a message after session close")
        if projected.pending_continuation is not None:
            raise InvalidTransitionError(
                "pending approval TOOL/resolution must be appended atomically"
            )
        if message_index != projected.next_message_index:
            raise InvalidTransitionError("message_index must be the next contiguous index")
        return self._append_event(
            task_id,
            TaskEventType.SESSION_MESSAGE_RECORDED,
            {
                "session_id": session_id,
                "message_index": message_index,
                "message": message.model_dump(mode="json"),
                "turn_id": turn_id,
            },
            correlation_id=session_id,
        )

    def project_session(self, task_id: str, session_id: str) -> ProjectedSession:
        return SessionProjector(self._event_store).project(task_id, session_id)

    def record_session_approval_pending(
        self,
        task_id: str,
        session_id: str,
        *,
        turn_id: str,
        action: ActionContract,
        proposal: ProviderToolProposal,
        preview: str,
        assistant_message_index: int,
        proposal_index: int,
        steps: int,
        total_tokens: int,
        seen_action_digests: dict[str, int],
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        run = aggregate.run
        snapshot = aggregate.configuration_snapshot
        projected = SessionProjector(self._event_store).project(task_id, session_id)
        self._validate_session_binding(
            aggregate,
            projected.ref,
            projected.expected_outcome_id,
        )
        if run is None or snapshot is None:
            raise InvalidTransitionError(
                "pending approval requires an active configured Run"
            )
        if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise InvalidTransitionError(
                "pending approval requires a runnable Run"
            )
        if projected.closed or projected.pending_continuation is not None:
            raise InvalidTransitionError(
                "session already has an unresolved pending approval"
            )
        if projected.resumable_turn_id != turn_id:
            raise InvalidTransitionError("pending approval turn binding mismatch")
        if (
            action.task_id != task_id
            or action.run_id != run.run_id
            or action.tenant_id != run.tenant_id
            or action.workspace_id != run.workspace_id
            or action.candidate_envelope_id != projected.envelope_id
            or action.expected_outcome_id != projected.expected_outcome_id
            or proposal.capability_id != action.capability_id
            or proposal.arguments_json != action.arguments_json
        ):
            raise InvalidTransitionError("pending approval action binding mismatch")
        if (
            run.configuration_snapshot_id != snapshot.snapshot_id
            or run.configuration_snapshot_digest != snapshot.snapshot_digest
            or run.provider_profile_id != snapshot.provider_profile.profile_id
        ):
            raise InvalidTransitionError(
                "pending approval configuration binding mismatch"
            )
        if not preview.strip():
            raise ValueError("pending approval preview must be non-empty")
        colliding_actions: list[dict[str, object]] = []
        for event in self._event_store.read(task_id):
            if event.event_type is not TaskEventType.ACTION_PROPOSED:
                continue
            value = event.decoded_payload().get("action")
            if not isinstance(value, dict):
                raise InvalidTransitionError("invalid durable proposed action payload")
            if any(
                value.get(field) == expected
                for field, expected in (
                    ("action_id", action.action_id),
                    ("idempotency_key", action.idempotency_key),
                )
            ):
                colliding_actions.append(value)
        if colliding_actions:
            raise InvalidTransitionError(
                "pending approval action identity is already recorded"
            )
        waiting_run = run.model_copy(
            update={
                "status": RunStatus.WAITING_APPROVAL,
                "active_node_id": action.node_id,
            }
        )
        requested_at = self._clock()
        pending_payload: dict[str, object] = {
            "session_id": session_id,
            "task_id": task_id,
            "run_id": run.run_id,
            "tenant_id": run.tenant_id,
            "workspace_id": run.workspace_id,
            "turn_id": turn_id,
            "provider_proposal": proposal.model_dump(mode="json"),
            "action": action.model_dump(mode="json"),
            "preview": preview,
            "action_digest": action.action_digest(),
            "assistant_message_index": assistant_message_index,
            "proposal_index": proposal_index,
            "steps": steps,
            "total_tokens": total_tokens,
            "seen_action_digests": dict(sorted(seen_action_digests.items())),
            "configuration_snapshot_id": snapshot.snapshot_id,
            "configuration_snapshot_digest": snapshot.snapshot_digest,
            "provider_profile_id": snapshot.provider_profile.profile_id,
            "provider_profile_digest": snapshot.provider_profile_digest,
            "c7_epochs": action.observed_correction_epochs.model_dump(mode="json"),
            "requested_at": requested_at,
        }
        return self._append_batch(
            aggregate,
            (
                (
                    TaskEventType.ACTION_PROPOSED,
                    {"action": action.model_dump(mode="json")},
                ),
                (TaskEventType.SESSION_APPROVAL_PENDING, pending_payload),
                (
                    TaskEventType.APPROVAL_REQUESTED,
                    {
                        "run": waiting_run.model_dump(mode="json"),
                        "action_id": action.action_id,
                        "action_digest": action.action_digest(),
                    },
                ),
            ),
            correlation_id=run.run_id,
        )

    def record_or_reuse_session_approval(
        self,
        task_id: str,
        session_id: str,
        action: ActionContract,
        approval: ApprovalDecision,
    ) -> ApprovalDecision:
        projected = SessionProjector(self._event_store).project(task_id, session_id)
        pending = projected.pending_continuation
        if pending is None or pending.action != action:
            raise InvalidTransitionError("approval has no exact pending action")
        matching: list[ApprovalDecision] = []
        for event in self._event_store.read(task_id):
            if event.event_type is not TaskEventType.APPROVAL_RECORDED:
                continue
            value = event.decoded_payload().get("approval")
            if not isinstance(value, dict):
                raise InvalidTransitionError("invalid durable approval payload")
            recorded = ApprovalDecision.model_validate(value)
            if recorded.action_digest == action.action_digest():
                matching.append(recorded)
        if len(matching) > 1:
            raise InvalidTransitionError(
                "multiple approvals bind the same pending action"
            )
        if matching:
            recorded = matching[0]
            if (
                recorded.tenant_id != approval.tenant_id
                or recorded.workspace_id != approval.workspace_id
                or recorded.actor_id != approval.actor_id
                or recorded.actor_role is not approval.actor_role
                or recorded.disposition is not approval.disposition
                or recorded.reason != approval.reason
            ):
                raise InvalidTransitionError(
                    "approval retry does not match the exact durable decision"
                )
            return recorded
        self.record_approval(task_id, approval)
        return approval

    def resolve_session_approval(
        self,
        task_id: str,
        session_id: str,
        *,
        pending: ProjectedApprovalContinuation,
        approval: ApprovalDecision,
        tool_message: ProviderMessage,
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        projected = SessionProjector(self._event_store).project(task_id, session_id)
        run = aggregate.run
        if (
            run is None
            or run.status is not RunStatus.WAITING_APPROVAL
            or projected.pending_continuation != pending
            or projected.resumable_turn_id != pending.turn_id
        ):
            raise InvalidTransitionError(
                "approval resolution does not bind the current pending state"
            )
        if (
            approval.action_digest != pending.action.action_digest()
            or approval.tenant_id != pending.action.tenant_id
            or approval.workspace_id != pending.action.workspace_id
            or approval.disposition
            not in {ApprovalDisposition.APPROVE, ApprovalDisposition.REJECT}
        ):
            raise InvalidTransitionError("approval resolution decision mismatch")
        recorded = tuple(
            event.decoded_payload().get("approval")
            for event in self._event_store.read(task_id)
            if event.event_type is TaskEventType.APPROVAL_RECORDED
            and event.decoded_payload().get("approval")
            == approval.model_dump(mode="json")
        )
        if len(recorded) != 1:
            raise InvalidTransitionError(
                "approval resolution lacks one exact durable decision"
            )
        if (
            tool_message.role is not ProviderMessageRole.TOOL
            or tool_message.tool_call_id != pending.proposal.proposal_id
        ):
            raise InvalidTransitionError("approval resolution TOOL binding mismatch")
        message_index = projected.next_message_index
        resumed_run = run.model_copy(
            update={"status": RunStatus.RUNNING, "active_node_id": None}
        )
        resolved_at = self._clock()
        return self._append_batch(
            aggregate,
            (
                (
                    TaskEventType.SESSION_MESSAGE_RECORDED,
                    {
                        "session_id": session_id,
                        "message_index": message_index,
                        "message": tool_message.model_dump(mode="json"),
                        "turn_id": pending.turn_id,
                    },
                ),
                (
                    TaskEventType.SESSION_APPROVAL_RESOLVED,
                    {
                        "session_id": session_id,
                        "task_id": pending.action.task_id,
                        "run_id": pending.action.run_id,
                        "tenant_id": pending.action.tenant_id,
                        "workspace_id": pending.action.workspace_id,
                        "turn_id": pending.turn_id,
                        "action_digest": pending.action.action_digest(),
                        "proposal_id": pending.proposal.proposal_id,
                        "approval_id": approval.approval_id,
                        "disposition": approval.disposition.value,
                        "tool_message_index": message_index,
                        "resolved_at": resolved_at,
                    },
                ),
                (
                    TaskEventType.RUN_RESUMED,
                    {"run": resumed_run.model_dump(mode="json")},
                ),
            ),
            correlation_id=run.run_id,
        )

    def close_session(self, task_id: str, session_id: str) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        projected = SessionProjector(self._event_store).project(task_id, session_id)
        self._validate_session_binding(
            aggregate,
            projected.ref,
            projected.expected_outcome_id,
        )
        if projected.closed:
            raise InvalidTransitionError("session is already closed")
        if projected.pending_approval is not None:
            raise InvalidTransitionError(
                "cannot close a session with an unresolved pending approval"
            )
        return self._append_event(
            task_id,
            TaskEventType.SESSION_CLOSED,
            {"session_id": session_id},
            correlation_id=session_id,
        )

    @staticmethod
    def _validate_session_binding(
        aggregate: TaskAggregate,
        ref: SessionRef,
        expected_outcome_id: str,
    ) -> None:
        run = aggregate.run
        expected = aggregate.expected_outcome
        if (
            run is None
            or expected is None
            or ref.task_id != aggregate.task_id
            or ref.run_id != run.run_id
            or ref.tenant_id != run.tenant_id
            or ref.workspace_id != run.workspace_id
            or expected_outcome_id != run.expected_outcome_id
            or expected_outcome_id != expected.expected_outcome_id
        ):
            raise InvalidTransitionError("session scope mismatch")

    def _record_action_receipt(
        self,
        task_id: str,
        *,
        action: ActionContract,
        decision: PolicyDecision,
        permit: ActionPermit,
        receipt: ActionReceipt,
        writer_token: object,
    ) -> TaskAggregate:
        if writer_token is not self._runtime_writer_token:
            raise InvalidTransitionError("action receipt writer is not authorized")
        aggregate = self.get_task(task_id)
        if aggregate.run is None:
            raise InvalidTransitionError("action receipt requires an active run")
        run = aggregate.run
        if (
            action.task_id != task_id
            or action.run_id != run.run_id
            or action.tenant_id != run.tenant_id
            or action.workspace_id != run.workspace_id
        ):
            raise InvalidTransitionError("action receipt scope mismatch")
        if (
            decision.action_id != action.action_id
            or decision.action_digest != action.action_digest()
            or decision.tenant_id != action.tenant_id
            or decision.workspace_id != action.workspace_id
            or decision.verdict is not PolicyVerdict.ALLOW
        ):
            raise InvalidTransitionError("action receipt policy binding mismatch")
        if (
            not permit.matches(action)
            or permit.policy_decision_id != decision.decision_id
            or receipt.action_id != action.action_id
            or receipt.action_digest != action.action_digest()
            or receipt.permit_id != permit.permit_id
            or receipt.tenant_id != action.tenant_id
            or receipt.workspace_id != action.workspace_id
            or receipt.connector_id != action.capability_id
            or receipt.idempotency_key != action.idempotency_key
        ):
            raise InvalidTransitionError("action receipt permit binding mismatch")
        events = self._event_store.read(task_id)
        action_recorded = any(
            event.event_type is TaskEventType.ACTION_PROPOSED
            and event.correlation_id == run.run_id
            and event.decoded_payload().get("action")
            == action.model_dump(mode="json")
            for event in events
        )
        decision_recorded = any(
            event.event_type is TaskEventType.POLICY_DECIDED
            and event.correlation_id == run.run_id
            and event.decoded_payload().get("decision")
            == decision.model_dump(mode="json")
            for event in events
        )
        if not action_recorded or not decision_recorded:
            raise InvalidTransitionError(
                "action receipt lacks proposed action or policy decision"
            )
        expected_payload: dict[str, object] = {
            "decision": decision.model_dump(mode="json"),
            "permit": permit.model_dump(mode="json"),
            "receipt": receipt.model_dump(mode="json"),
        }
        logically_bound_receipts: list[dict[str, object]] = []
        for event in events:
            if event.event_type is not TaskEventType.ACTION_RECEIPT_RECORDED:
                continue
            payload = event.decoded_payload()
            stored_receipt = payload.get("receipt")
            if not isinstance(stored_receipt, dict):
                raise InvalidTransitionError("invalid durable action receipt payload")
            if any(
                stored_receipt.get(field) == value
                for field, value in (
                    ("action_id", action.action_id),
                    ("action_digest", action.action_digest()),
                    ("idempotency_key", action.idempotency_key),
                )
            ):
                logically_bound_receipts.append(payload)
        if logically_bound_receipts:
            if len(logically_bound_receipts) != 1:
                raise InvalidTransitionError(
                    "multiple durable receipts bind the same logical action"
                )
            if logically_bound_receipts[0] != expected_payload:
                raise InvalidTransitionError(
                    "durable action receipt identity conflict"
                )
            return aggregate
        return self._append_event(
            task_id,
            TaskEventType.ACTION_RECEIPT_RECORDED,
            expected_payload,
            correlation_id=run.run_id,
            writer_token=writer_token,
        )

    def _recover_action_receipt(
        self,
        task_id: str,
        *,
        action: ActionContract,
        permit: ActionPermit,
        receipt: ActionReceipt,
        writer_token: object,
    ) -> TaskAggregate:
        """Append the original sealed receipt, or prove it is already present.

        The policy decision is recovered only from the append-only Task stream;
        connector outcome storage cannot mint or reconstruct policy authority.
        """

        if writer_token is not self._runtime_writer_token:
            raise InvalidTransitionError("action receipt writer is not authorized")
        matching: list[PolicyDecision] = []
        for event in self._event_store.read(task_id):
            if event.event_type is not TaskEventType.POLICY_DECIDED:
                continue
            value = event.decoded_payload().get("decision")
            if not isinstance(value, dict):
                raise InvalidTransitionError("invalid durable policy decision payload")
            decision = PolicyDecision.model_validate(value)
            if decision.decision_id == permit.policy_decision_id:
                matching.append(decision)
        if len(matching) != 1:
            raise InvalidTransitionError(
                "sealed action outcome lacks one exact durable policy decision"
            )
        return self._record_action_receipt(
            task_id,
            action=action,
            decision=matching[0],
            permit=permit,
            receipt=receipt,
            writer_token=writer_token,
        )

    def register_wait(self, task_id: str, node: NodeSpec) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if aggregate.run is None or aggregate.workflow is None or aggregate.commitment is None:
            raise InvalidTransitionError("wait registration requires an active committed run")
        if node.kind is not NodeKind.WAIT_EVENT:
            raise InvalidTransitionError("wait registration requires a wait_event node")
        committed_node = next(
            (candidate for candidate in aggregate.workflow.nodes if candidate.node_id == node.node_id),
            None,
        )
        if committed_node != node:
            raise InvalidTransitionError("wait node does not match the committed workflow")
        if aggregate.run.status is RunStatus.WAITING_EVENT:
            if aggregate.run.wait_condition is not None and (
                aggregate.run.wait_condition.node_id == node.node_id
            ):
                return aggregate
            raise InvalidTransitionError("run is already waiting for a different event")
        if aggregate.run.status is not RunStatus.RUNNING:
            raise InvalidTransitionError(
                f"cannot register wait from {aggregate.run.status.value}"
            )
        now = self._clock()
        deadline = min(
            now + timedelta(seconds=node.timeout_seconds),
            aggregate.commitment.expires_at,
        )
        if deadline <= now:
            raise CommitmentExpiredError("commitment expired before wait registration")
        condition = WaitCondition(
            node_id=node.node_id,
            signal_name=node.wait_signal_name or "",
            correlation_key=node.wait_correlation_key or "",
            registered_at=now,
            deadline=deadline,
        )
        run = aggregate.run.model_copy(
            update={
                "status": RunStatus.WAITING_EVENT,
                "active_node_id": node.node_id,
                "wait_condition": condition,
            }
        )
        return self._append_batch(
            aggregate,
            (
                (
                    TaskEventType.WAIT_REGISTERED,
                    {
                        "run": run.model_dump(mode="json"),
                        "wait_condition": condition.model_dump(mode="json"),
                    },
                ),
            ),
            correlation_id=run.run_id,
        )

    def record_signal(self, task_id: str, signal: ExternalSignal) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        duplicate = self._recorded_signal(task_id, signal.signal_id)
        if duplicate is not None:
            if duplicate == signal:
                return aggregate
            raise SignalMismatchError("signal_id already recorded with different content")
        if signal.task_id != task_id:
            raise SignalMismatchError("signal task scope mismatch")
        run = aggregate.run
        if run is None or run.wait_condition is None or run.status is not RunStatus.WAITING_EVENT:
            raise SignalMismatchError("task has no active wait for this signal")
        condition = run.wait_condition
        mismatches: list[str] = []
        if signal.run_id != run.run_id:
            mismatches.append("run")
        if signal.tenant_id != run.tenant_id:
            mismatches.append("tenant")
        if signal.workspace_id != run.workspace_id:
            mismatches.append("workspace")
        if signal.signal_name != condition.signal_name:
            mismatches.append("signal name")
        if signal.correlation_key != condition.correlation_key:
            mismatches.append("correlation key")
        if signal.occurred_at < condition.registered_at:
            mismatches.append("occurred_at")
        if mismatches:
            raise SignalMismatchError("signal mismatch: " + ", ".join(mismatches))
        if max(self._clock(), signal.occurred_at) >= condition.deadline:
            self.expire_wait(task_id)
            raise WaitExpiredError("signal arrived after the wait deadline")
        resumed = run.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "active_node_id": None,
                "wait_condition": None,
            }
        )
        events: tuple[tuple[TaskEventType, dict[str, object]], ...] = (
            (
                TaskEventType.EXTERNAL_SIGNAL_RECORDED,
                {"signal": signal.model_dump(mode="json")},
            ),
            (
                TaskEventType.WAIT_SATISFIED,
                {
                    "run": resumed.model_dump(mode="json"),
                    "node_id": condition.node_id,
                    "signal_id": signal.signal_id,
                },
            ),
            (
                TaskEventType.NODE_COMPLETED,
                {
                    "node_id": condition.node_id,
                    "output": {
                        "signal_id": signal.signal_id,
                        "signal_name": signal.signal_name,
                        "correlation_key": signal.correlation_key,
                        "payload": signal.decoded_payload(),
                        "evidence_refs": signal.evidence_refs,
                    },
                },
            ),
        )
        try:
            return self._append_batch(aggregate, events, correlation_id=run.run_id)
        except ConcurrentWriteError:
            duplicate = self._recorded_signal(task_id, signal.signal_id)
            if duplicate == signal:
                return self.get_task(task_id)
            raise SignalMismatchError("wait was satisfied concurrently by another signal")

    def expire_wait(
        self,
        task_id: str,
        *,
        reason: str = "wait deadline exceeded",
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if aggregate.run is None or aggregate.run.wait_condition is None:
            raise InvalidTransitionError("task has no active wait to expire")
        condition = aggregate.run.wait_condition
        failed = aggregate.run.model_copy(
            update={
                "status": RunStatus.FAILED,
                "active_node_id": condition.node_id,
                "wait_condition": None,
            }
        )
        return self._append_batch(
            aggregate,
            (
                (
                    TaskEventType.WAIT_TIMED_OUT,
                    {
                        "run": failed.model_dump(mode="json"),
                        "wait_condition": condition.model_dump(mode="json"),
                        "reason": reason,
                    },
                ),
            ),
            correlation_id=failed.run_id,
        )

    def expire_commitment(
        self,
        task_id: str,
        *,
        reason: str = "commitment deadline exceeded",
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if aggregate.run is None:
            raise InvalidTransitionError("task has no active run to expire")
        failed = aggregate.run.model_copy(
            update={
                "status": RunStatus.FAILED,
                "wait_condition": None,
            }
        )
        return self._append_batch(
            aggregate,
            (
                (
                    TaskEventType.COMMITMENT_EXPIRED,
                    {"run": failed.model_dump(mode="json"), "reason": reason},
                ),
            ),
            correlation_id=failed.run_id,
        )

    def replan_task(
        self,
        task_id: str,
        workflow: WorkflowGraph,
        *,
        requested_by: str,
        reason: str,
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if aggregate.configuration_snapshot is not None:
            raise ReplanRejectedError(
                "configuration snapshot-bound runs cannot replan in ADM-P4"
            )
        current = aggregate.workflow
        run = aggregate.run
        if current is None or run is None or aggregate.expected_outcome is None:
            raise ReplanRejectedError("replan requires an active committed run")
        if run.status not in {RunStatus.WAITING_EVENT, RunStatus.PAUSED, RunStatus.FAILED}:
            raise ReplanRejectedError(f"cannot replan from {run.status.value}")
        if run.replan_count >= current.max_replans:
            raise ReplanRejectedError("replan budget exhausted")
        if workflow.workflow_id != current.workflow_id:
            raise ReplanRejectedError("workflow_id cannot change during replan")
        if workflow.version != current.version + 1:
            raise ReplanRejectedError("workflow version must increase by exactly one")
        if workflow.max_replans > current.max_replans:
            raise ReplanRejectedError("max_replans cannot increase during replan")
        if (
            workflow.tenant_id != current.tenant_id
            or workflow.workspace_id != current.workspace_id
        ):
            raise ReplanRejectedError("workflow scope cannot change during replan")
        if workflow.policy_version != current.policy_version:
            raise ReplanRejectedError("policy version cannot change during replan")
        if workflow.evaluator_refs != current.evaluator_refs:
            raise ReplanRejectedError("evaluator refs cannot change during replan")
        evaluator_ref = (
            f"evaluator:{aggregate.expected_outcome.evaluator_type}:"
            f"{aggregate.expected_outcome.evaluator_version}"
        )
        if evaluator_ref not in workflow.evaluator_refs:
            raise ReplanRejectedError("expected outcome evaluator must remain bound")

        completed = self._completed_node_ids(task_id)
        current_nodes = {node.node_id: node for node in current.nodes}
        new_nodes = {node.node_id: node for node in workflow.nodes}
        for node_id in completed:
            if new_nodes.get(node_id) != current_nodes.get(node_id):
                raise ReplanRejectedError(f"completed node cannot change: {node_id}")
        current_incoming = {
            edge.model_dump_json()
            for edge in current.edges
            if edge.target in completed
        }
        new_incoming = {
            edge.model_dump_json()
            for edge in workflow.edges
            if edge.target in completed
        }
        if new_incoming != current_incoming:
            raise ReplanRejectedError("incoming edges for completed nodes cannot change")

        preserved = tuple(
            sorted(
                node_id
                for node_id in current_nodes.keys() & new_nodes.keys()
                if current_nodes[node_id] == new_nodes[node_id]
            )
        )
        invalidated = tuple(sorted(current_nodes.keys() - set(preserved)))
        added = tuple(sorted(new_nodes.keys() - set(preserved)))
        rebound = RunPlanRebound(
            rebound_id=self._id_factory("rebound"),
            task_id=task_id,
            run_id=run.run_id,
            previous_workflow_version=current.version,
            previous_workflow_digest=current.canonical_digest(),
            new_workflow_version=workflow.version,
            new_workflow_digest=workflow.canonical_digest(),
            preserved_node_ids=preserved,
            invalidated_node_ids=invalidated,
            new_node_ids=added,
            requested_by=requested_by,
            reason=reason,
            created_at=self._clock(),
        )
        rebound_run = run.model_copy(
            update={
                "workflow_version": workflow.version,
                "workflow_digest": workflow.canonical_digest(),
                "status": RunStatus.PAUSED,
                "active_node_id": None,
                "wait_condition": None,
                "replan_count": run.replan_count + 1,
            }
        )
        return self._append_batch(
            aggregate,
            (
                (
                    TaskEventType.RUN_PLAN_REBOUND,
                    {
                        "workflow": workflow.model_dump(mode="json"),
                        "rebound": rebound.model_dump(mode="json"),
                        "run": rebound_run.model_dump(mode="json"),
                    },
                ),
            ),
            correlation_id=run.run_id,
        )

    def _append_batch(
        self,
        aggregate: TaskAggregate,
        events: tuple[tuple[TaskEventType, dict[str, object]], ...],
        *,
        correlation_id: str,
    ) -> TaskAggregate:
        occurred_at = self._clock()
        causation_id = aggregate.last_event_id
        drafts: list[TaskEventDraft] = []
        for event_type, payload in events:
            event_id = self._id_factory("event")
            drafts.append(
                TaskEventDraft.build(
                    event_id=event_id,
                    task_id=aggregate.task_id,
                    event_type=event_type,
                    payload=payload,
                    occurred_at=occurred_at,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                )
            )
            causation_id = event_id
        self._event_store.append(
            aggregate.task_id,
            expected_sequence=aggregate.sequence,
            drafts=tuple(drafts),
        )
        return self.get_task(aggregate.task_id)

    def _recorded_signal(
        self, task_id: str, signal_id: str
    ) -> ExternalSignal | None:
        for event in self._event_store.read(task_id):
            if event.event_type is not TaskEventType.EXTERNAL_SIGNAL_RECORDED:
                continue
            payload = event.decoded_payload().get("signal")
            if isinstance(payload, dict) and payload.get("signal_id") == signal_id:
                return ExternalSignal.model_validate(payload)
        return None

    def _completed_node_ids(self, task_id: str) -> set[str]:
        completed: set[str] = set()
        for event in self._event_store.read(task_id):
            if event.event_type is TaskEventType.NODE_COMPLETED:
                node_id = event.decoded_payload().get("node_id")
                if isinstance(node_id, str):
                    completed.add(node_id)
        return completed

    def record_approval(
        self,
        task_id: str,
        approval: ApprovalDecision,
    ) -> TaskAggregate:
        events = self._event_store.read(task_id)
        if not events:
            raise TaskNotFoundError(f"task not found: {task_id}")
        aggregate = TaskAggregate.rehydrate(events)
        pending: ActionContract | None = None
        for event in reversed(events):
            if event.event_type in {
                TaskEventType.RUN_PLAN_REBOUND,
                TaskEventType.APPROVAL_RECORDED,
            }:
                break
            if event.event_type is not TaskEventType.ACTION_PROPOSED:
                continue
            candidate = event.decoded_payload().get("action")
            if isinstance(candidate, dict):
                pending = ActionContract.model_validate(candidate)
                break
        if pending is None:
            raise InvalidTransitionError("task has no pending action in the current plan")
        if pending.task_id != task_id:
            raise InvalidTransitionError("pending action task binding mismatch")
        if aggregate.run is None or pending.run_id != aggregate.run.run_id:
            raise InvalidTransitionError("pending action run binding mismatch")
        if approval.action_digest != pending.action_digest():
            raise InvalidTransitionError("approval does not bind the pending action")
        return self._append_batch(
            aggregate,
            (
                (
                    TaskEventType.APPROVAL_RECORDED,
                    {"approval": approval.model_dump(mode="json")},
                ),
            ),
            correlation_id=aggregate.run.run_id,
        )

    def update_run_status(
        self,
        task_id: str,
        status: RunStatus,
        *,
        event_type: TaskEventType,
        active_node_id: str | None = None,
        lease_fence: int | None = None,
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if aggregate.run is None:
            raise InvalidTransitionError("task has no run")
        allowed: dict[RunStatus, set[RunStatus]] = {
            RunStatus.CREATED: {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLED},
            RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED},
            RunStatus.RUNNING: {RunStatus.RUNNING, RunStatus.WAITING_APPROVAL, RunStatus.WAITING_EVENT, RunStatus.PAUSED, RunStatus.VERIFYING, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
            RunStatus.WAITING_APPROVAL: {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.CANCELLED, RunStatus.FAILED},
            RunStatus.WAITING_EVENT: {RunStatus.PAUSED, RunStatus.CANCELLED, RunStatus.FAILED},
            RunStatus.PAUSED: {RunStatus.RUNNING, RunStatus.CANCELLED},
            RunStatus.VERIFYING: {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.PAUSED},
            RunStatus.SUCCEEDED: set(),
            RunStatus.FAILED: {RunStatus.RUNNING, RunStatus.CANCELLED},
            RunStatus.CANCELLED: set(),
        }
        if status not in allowed[aggregate.run.status]:
            raise InvalidTransitionError(
                f"cannot move run from {aggregate.run.status.value} to {status.value}"
            )
        updates: dict[str, object] = {"status": status, "active_node_id": active_node_id}
        if lease_fence is not None:
            updates["lease_fence"] = lease_fence
        run = aggregate.run.model_copy(update=updates)
        return self._append_batch(
            aggregate,
            ((event_type, {"run": run.model_dump(mode="json")}),),
            correlation_id=run.run_id,
        )

    def _bound_action_receipt(
        self,
        aggregate: TaskAggregate,
        *,
        node_id: str,
        action_id: str,
        artifact_id: str,
        before_sequence: int | None = None,
    ) -> tuple[ActionContract, ActionReceipt, int] | None:
        if aggregate.run is None or aggregate.workflow is None:
            return None
        run = aggregate.run
        committed_node = next(
            (
                node
                for node in aggregate.workflow.nodes
                if node.node_id == node_id and node.capability is not None
            ),
            None,
        )
        if committed_node is None:
            return None
        events = self._event_store.read(aggregate.task_id)
        cutoff = before_sequence or (events[-1].sequence + 1 if events else 1)
        last_rebound = max(
            (
                event.sequence
                for event in events
                if event.sequence < cutoff
                and event.event_type is TaskEventType.RUN_PLAN_REBOUND
            ),
            default=0,
        )
        proposed: tuple[ActionContract, int] | None = None
        for event in events:
            if event.sequence <= last_rebound or event.sequence >= cutoff:
                continue
            if event.correlation_id != run.run_id:
                continue
            if event.event_type is TaskEventType.ACTION_PROPOSED:
                payload = event.decoded_payload().get("action")
                if not isinstance(payload, dict):
                    continue
                try:
                    action = ActionContract.model_validate(payload)
                except (TypeError, ValueError):
                    continue
                if (
                    action.action_id == action_id
                    and action.task_id == aggregate.task_id
                    and action.run_id == run.run_id
                    and action.node_id == node_id
                    and action.tenant_id == run.tenant_id
                    and action.workspace_id == run.workspace_id
                    and action.capability_id == committed_node.capability
                ):
                    proposed = (action, event.sequence)
                continue
            if (
                event.event_type is not TaskEventType.ACTION_RECEIPT_RECORDED
                or proposed is None
                or event.sequence <= proposed[1]
            ):
                continue
            event_payload = event.decoded_payload()
            receipt_payload = event_payload.get("receipt")
            permit_payload = event_payload.get("permit")
            decision_payload = event_payload.get("decision")
            if not all(
                isinstance(value, dict)
                for value in (receipt_payload, permit_payload, decision_payload)
            ):
                continue
            try:
                receipt = ActionReceipt.model_validate(receipt_payload)
                permit = ActionPermit.model_validate(permit_payload)
                decision = PolicyDecision.model_validate(decision_payload)
            except (TypeError, ValueError):
                continue
            action = proposed[0]
            if (
                decision.action_id == action.action_id
                and decision.action_digest == action.action_digest()
                and decision.tenant_id == action.tenant_id
                and decision.workspace_id == action.workspace_id
                and decision.verdict is PolicyVerdict.ALLOW
                and permit.matches(action)
                and permit.policy_decision_id == decision.decision_id
                and receipt.action_id == action.action_id
                and receipt.action_digest == action.action_digest()
                and receipt.permit_id == permit.permit_id
                and receipt.tenant_id == action.tenant_id
                and receipt.workspace_id == action.workspace_id
                and receipt.connector_id == action.capability_id
                and receipt.status is ReceiptStatus.SUCCEEDED
                and artifact_id in receipt.output_artifact_ids
            ):
                return action, receipt, event.sequence
        return None

    def validated_test_report(
        self,
        task_id: str,
        run_id: str,
    ) -> ValidatedTestReport | None:
        aggregate = self.get_task(task_id)
        if (
            aggregate.run is None
            or aggregate.run.run_id != run_id
            or aggregate.workflow is None
            or self._artifact_reader is None
        ):
            return None
        test_nodes = {
            node.node_id
            for node in aggregate.workflow.nodes
            if node.capability == "workspace.run_tests"
        }
        if not test_nodes:
            return None
        events = self._event_store.read(task_id)
        artifact_bindings: dict[
            str, tuple[int, str, ActionContract, ActionReceipt]
        ] = {}
        for event in events:
            if (
                event.event_type is not TaskEventType.ARTIFACT_RECORDED
                or event.correlation_id != run_id
            ):
                continue
            payload = event.decoded_payload()
            artifact_id = payload.get("artifact_id")
            node_id = payload.get("node_id")
            action_id = payload.get("action_id")
            if not all(
                isinstance(value, str)
                for value in (artifact_id, node_id, action_id)
            ):
                continue
            binding = self._bound_action_receipt(
                aggregate,
                node_id=str(node_id),
                action_id=str(action_id),
                artifact_id=str(artifact_id),
                before_sequence=event.sequence,
            )
            if binding is None:
                continue
            action, receipt, _ = binding
            artifact_bindings[str(artifact_id)] = (
                event.sequence,
                str(node_id),
                action,
                receipt,
            )

        candidates: list[ValidatedTestReport] = []
        for event in events:
            if (
                event.event_type is not TaskEventType.NODE_COMPLETED
                or event.correlation_id != run_id
            ):
                continue
            payload = event.decoded_payload()
            node_id = payload.get("node_id")
            output = payload.get("output")
            if node_id not in test_nodes or not isinstance(output, dict):
                continue
            exit_code = output.get("exit_code")
            output_artifacts = output.get("artifact_ids")
            if (
                isinstance(exit_code, bool)
                or not isinstance(exit_code, int)
                or not isinstance(output_artifacts, (list, tuple))
            ):
                continue
            digest = output.get("digest")
            bound_artifact_ids = {
                artifact_id
                for artifact_id in output_artifacts
                if isinstance(artifact_id, str)
                and artifact_id in artifact_bindings
                and artifact_bindings[artifact_id][0] < event.sequence
                and artifact_bindings[artifact_id][1] == node_id
            }
            bound_artifacts = tuple(
                sorted(
                    artifact_id
                    for artifact_id in bound_artifact_ids
                    if digest == artifact_id.removeprefix("artifact:")
                    and self._test_report_artifact_matches(
                        artifact_id,
                        artifact_bindings[artifact_id][2],
                        exit_code,
                    )
                )
            )
            if not bound_artifacts:
                continue
            first_binding = artifact_bindings[bound_artifacts[0]]
            candidates.append(
                ValidatedTestReport(
                    artifact_ids=bound_artifacts,
                    exit_code=exit_code,
                    node_id=str(node_id),
                    action_id=first_binding[2].action_id,
                    receipt_id=first_binding[3].receipt_id,
                    completed_sequence=event.sequence,
                    completed_at=event.occurred_at,
                )
            )
        if not candidates:
            return None
        latest_by_node = {
            node_id: max(
                (
                    candidate
                    for candidate in candidates
                    if candidate.node_id == node_id
                ),
                key=lambda candidate: candidate.completed_sequence,
            )
            for node_id in test_nodes
            if any(candidate.node_id == node_id for candidate in candidates)
        }
        if set(latest_by_node) != test_nodes:
            return None
        required_reports = tuple(latest_by_node[node_id] for node_id in sorted(test_nodes))
        latest_report = max(
            required_reports,
            key=lambda candidate: candidate.completed_sequence,
        )
        failed_report = next(
            (candidate for candidate in required_reports if candidate.exit_code != 0),
            None,
        )
        report = ValidatedTestReport(
            artifact_ids=tuple(
                sorted(
                    {
                        artifact_id
                        for candidate in required_reports
                        for artifact_id in candidate.artifact_ids
                    }
                )
            ),
            exit_code=failed_report.exit_code if failed_report is not None else 0,
            node_id=latest_report.node_id,
            action_id=latest_report.action_id,
            receipt_id=latest_report.receipt_id,
            completed_sequence=latest_report.completed_sequence,
            completed_at=max(candidate.completed_at for candidate in required_reports),
            node_ids=tuple(sorted(test_nodes)),
        )
        required_node_ids = set(report.node_ids or (report.node_id,))
        for event in events:
            if event.sequence <= report.completed_sequence:
                continue
            if event.event_type is TaskEventType.RUN_PLAN_REBOUND:
                payload = event.decoded_payload().get("rebound")
                if not isinstance(payload, dict):
                    return None
                try:
                    rebound = RunPlanRebound.model_validate(payload)
                except (TypeError, ValueError):
                    return None
                if not required_node_ids.issubset(rebound.preserved_node_ids):
                    return None
            if (
                event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
                and event.correlation_id == run_id
            ):
                payload = event.decoded_payload().get("receipt")
                if isinstance(payload, dict):
                    try:
                        receipt = ActionReceipt.model_validate(payload)
                    except (TypeError, ValueError):
                        return None
                    if receipt.status is ReceiptStatus.SUCCEEDED:
                        action = next(
                            (
                                ActionContract.model_validate(
                                    candidate.decoded_payload().get("action")
                                )
                                for candidate in reversed(events)
                                if candidate.sequence < event.sequence
                                and candidate.event_type
                                is TaskEventType.ACTION_PROPOSED
                                and candidate.correlation_id == run_id
                                and isinstance(
                                    candidate.decoded_payload().get("action"), dict
                                )
                                and candidate.decoded_payload()["action"].get(
                                    "action_id"
                                )
                                == receipt.action_id
                            ),
                            None,
                        )
                        if action is None or action.capability_id != "workspace.read":
                            return None
        return report

    def _test_report_artifact_matches(
        self,
        artifact_id: str,
        action: ActionContract,
        exit_code: int,
    ) -> bool:
        if self._artifact_reader is None:
            return False
        content = self._artifact_reader(artifact_id)
        if content is None:
            return False
        try:
            report = json.loads(content)
            arguments = json.loads(action.arguments_json)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        if not isinstance(report, dict) or not isinstance(arguments, dict):
            return False
        report_exit_code = report.get("exit_code")
        return (
            report.get("schema_version") == "test-report.v1"
            and report.get("action_key_sha256")
            == hashlib.sha256(action.idempotency_key.encode("utf-8")).hexdigest()
            and report.get("command") == arguments.get("command")
            and not isinstance(report_exit_code, bool)
            and isinstance(report_exit_code, int)
            and report_exit_code == exit_code
        )

    def record_outcome(self, task_id: str, outcome: ObservedOutcome) -> TaskAggregate:
        if self._correction_reader is None:
            raise InvalidTransitionError("outcome correction authority is not bound")
        aggregate = self.get_task(task_id)
        if aggregate.run is None or aggregate.expected_outcome is None:
            raise InvalidTransitionError("outcome requires a committed active run")
        correction_epochs = self._correction_reader.snapshot(
            task_id,
            aggregate.run.run_id,
            "outcome.evaluate",
        )
        if self._correction_reader.halted(
            task_id,
            aggregate.run.run_id,
            "outcome.evaluate",
        ):
            raise InvalidTransitionError(
                "outcome recording is halted by correction authority"
            )
        expected = aggregate.expected_outcome
        if (
            outcome.expected_outcome_id != expected.expected_outcome_id
            or outcome.task_id != task_id
            or outcome.run_id != aggregate.run.run_id
            or outcome.tenant_id != expected.tenant_id
            or outcome.workspace_id != expected.workspace_id
            or outcome.evaluator_type != expected.evaluator_type
            or outcome.evaluator_version != expected.evaluator_version
        ):
            raise InvalidTransitionError("outcome scope or evaluator binding mismatch")
        contract_error = expected_outcome_contract_error(expected)
        if contract_error is not None:
            if not (
                outcome.status is OutcomeStatus.INVALID
                and outcome.score is None
                and outcome.unresolved_gaps == (contract_error,)
            ):
                raise InvalidTransitionError(contract_error)
        if outcome.status is OutcomeStatus.VERIFIED:
            score = outcome.score
            if score is None or score != 1.0:
                raise InvalidTransitionError(
                    "verified outcome score does not match the trusted pytest score"
                )
            if score < expected.threshold:
                raise InvalidTransitionError(
                    "verified outcome score is below frozen threshold"
                )
            now = self._clock()
            if outcome.observed_at > now:
                raise InvalidTransitionError(
                    "verified outcome cannot be observed in the future"
                )
            if now > expected.frozen_at + timedelta(
                seconds=expected.observation_window_seconds
            ):
                raise InvalidTransitionError(
                    "verified outcome observation window is closed"
                )
            if not (
                expected.frozen_at
                <= outcome.observed_at
                <= expected.frozen_at
                + timedelta(seconds=expected.observation_window_seconds)
            ):
                raise InvalidTransitionError(
                    "verified outcome is outside the frozen observation window"
                )
            report = self.validated_test_report(task_id, aggregate.run.run_id)
            if report is None:
                raise InvalidTransitionError(
                    "verified outcome lacks durable test-report evidence"
                )
            if not set(report.artifact_ids).issubset(outcome.evidence_refs):
                raise InvalidTransitionError(
                    "verified outcome evidence does not match durable test report"
                )
            if report.exit_code != 0:
                raise InvalidTransitionError(
                    "verified outcome is bound to a failing test report"
                )
            if report.completed_at < expected.frozen_at:
                raise InvalidTransitionError(
                    "verified test report predates frozen contract"
                )
            if report.completed_at > outcome.observed_at:
                raise InvalidTransitionError(
                    "verified outcome predates its durable test report"
                )
        guarded_append = getattr(self._event_store, "append_guarded", None)
        if callable(guarded_append) and correction_epochs is not None:
            draft = TaskEventDraft.build(
                event_id=self._id_factory("event"),
                task_id=task_id,
                event_type=TaskEventType.OUTCOME_OBSERVED,
                payload={"outcome": outcome.model_dump(mode="json")},
                occurred_at=self._clock(),
                correlation_id=outcome.run_id,
                causation_id=aggregate.last_event_id,
            )
            try:
                guarded_append(
                    task_id,
                    run_id=aggregate.run.run_id,
                    capability_id="outcome.evaluate",
                    expected_correction_epochs=correction_epochs,
                    expected_sequence=aggregate.sequence,
                    drafts=(draft,),
                )
            except ConcurrentWriteError as exc:
                if "correction authority" in str(exc):
                    raise InvalidTransitionError(
                        "outcome recording is halted by correction authority"
                    ) from exc
                raise
            return self.get_task(task_id)
        if self._correction_reader is not None and correction_epochs is not None:
            with self._correction_reader.guard_unchanged(
                task_id,
                aggregate.run.run_id,
                "outcome.evaluate",
                correction_epochs,
            ) as unchanged:
                if not unchanged:
                    raise InvalidTransitionError(
                        "outcome recording is halted by correction authority"
                    )
                return self._append_event(
                    task_id,
                    TaskEventType.OUTCOME_OBSERVED,
                    {"outcome": outcome.model_dump(mode="json")},
                    correlation_id=outcome.run_id,
                    writer_token=self._runtime_writer_token,
                )
        return self._append_event(
            task_id,
            TaskEventType.OUTCOME_OBSERVED,
            {"outcome": outcome.model_dump(mode="json")},
            correlation_id=outcome.run_id,
            writer_token=self._runtime_writer_token,
        )

    def record_artifact(
        self,
        task_id: str,
        artifact_id: str,
        *,
        node_id: str,
        action_id: str,
    ) -> TaskAggregate:
        aggregate = self.get_task(task_id)
        if self._bound_action_receipt(
            aggregate,
            node_id=node_id,
            action_id=action_id,
            artifact_id=artifact_id,
        ) is None:
            raise InvalidTransitionError(
                "artifact is not bound to a successful action receipt"
            )
        if aggregate.run is None:
            raise InvalidTransitionError("artifact requires an active run")
        return self._append_event(
            task_id,
            TaskEventType.ARTIFACT_RECORDED,
            {
                "artifact_id": artifact_id,
                "node_id": node_id,
                "action_id": action_id,
            },
            correlation_id=aggregate.run.run_id,
            writer_token=self._runtime_writer_token,
        )
