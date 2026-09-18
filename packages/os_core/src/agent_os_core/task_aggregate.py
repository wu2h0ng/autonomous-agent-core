from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from pydantic import ValidationError

from agent_os_contracts import (
    AgentRun,
    ApprovalDecision,
    Commitment,
    CompensationStatus,
    ExpectedOutcome,
    Goal,
    RunStatus,
    RunPlanRebound,
    TaskEvent,
    TaskEventDraft,
    TaskEventType,
    TaskStatus,
    TaskConfigurationSnapshot,
    WorkflowGraph,
    ObservedOutcome,
    PatchCompensationRecord,
)

from .errors import EventStreamError, InvalidTransitionError, ScopeMismatchError
from .governance import POLICY_KERNEL_V1_DIGEST


@dataclass(frozen=True, slots=True)
class TaskAggregate:
    task_id: str
    sequence: int = 0
    status: TaskStatus | None = None
    goal: Goal | None = None
    commitment: Commitment | None = None
    workflow: WorkflowGraph | None = None
    expected_outcome: ExpectedOutcome | None = None
    configuration_snapshot: TaskConfigurationSnapshot | None = None
    run: AgentRun | None = None
    last_event_id: str | None = None
    observed_outcome: ObservedOutcome | None = None
    artifacts: tuple[str, ...] = ()
    approval: ApprovalDecision | None = None
    last_rebound: RunPlanRebound | None = None
    compensations: tuple[PatchCompensationRecord, ...] = ()

    @classmethod
    def create_task(
        cls,
        *,
        task_id: str,
        goal: Goal,
        event_id: str,
        occurred_at: datetime,
    ) -> TaskEventDraft:
        if not task_id.strip():
            raise ScopeMismatchError("task_id must be non-empty")
        return TaskEventDraft.build(
            event_id=event_id,
            task_id=task_id,
            event_type=TaskEventType.TASK_CREATED,
            payload={"goal": goal.model_dump(mode="json")},
            occurred_at=occurred_at,
            correlation_id=task_id,
        )

    @classmethod
    def rehydrate(cls, events: Sequence[TaskEvent]) -> TaskAggregate:
        if not events:
            raise EventStreamError("cannot rehydrate an empty task stream")
        aggregate = cls(task_id=events[0].task_id)
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence != expected_sequence:
                raise EventStreamError(
                    f"task event sequence gap: expected {expected_sequence}, "
                    f"got {event.sequence}"
                )
            if event.task_id != aggregate.task_id:
                raise EventStreamError(
                    f"event {event.event_id} belongs to a different task stream"
                )
            aggregate = aggregate._apply(event)
        return aggregate

    def commit(
        self,
        commitment: Commitment,
        workflow: WorkflowGraph,
        expected_outcome: ExpectedOutcome,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> TaskEventDraft:
        if self.status is not TaskStatus.DRAFT:
            raise InvalidTransitionError(
                f"cannot commit task from {self.status.value if self.status else 'NONE'}"
            )
        self._validate_commitment_bindings(commitment, workflow, expected_outcome)
        return TaskEventDraft.build(
            event_id=event_id,
            task_id=self.task_id,
            event_type=TaskEventType.TASK_COMMITTED,
            payload={
                "commitment": commitment.model_dump(mode="json"),
                "workflow": workflow.model_dump(mode="json"),
                "workflow_digest": workflow.canonical_digest(),
                "expected_outcome": expected_outcome.model_dump(mode="json"),
            },
            occurred_at=occurred_at,
            correlation_id=self.task_id,
            causation_id=self.last_event_id,
        )

    def start(
        self,
        run: AgentRun,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> TaskEventDraft:
        if self.status is not TaskStatus.COMMITTED:
            raise InvalidTransitionError(
                f"cannot start task from {self.status.value if self.status else 'NONE'}"
            )
        self._validate_run_bindings(run)
        return TaskEventDraft.build(
            event_id=event_id,
            task_id=self.task_id,
            event_type=TaskEventType.RUN_STARTED,
            payload={"run": run.model_dump(mode="json")},
            occurred_at=occurred_at,
            correlation_id=self.task_id,
            causation_id=self.last_event_id,
        )

    def seal_configuration_snapshot(
        self,
        snapshot: TaskConfigurationSnapshot,
        *,
        event_id: str,
        occurred_at: datetime,
    ) -> TaskEventDraft:
        if self.status is not TaskStatus.COMMITTED or self.run is not None:
            raise InvalidTransitionError(
                "configuration snapshot requires a committed task before run start"
            )
        if self.configuration_snapshot is not None:
            raise InvalidTransitionError("configuration snapshot is already sealed")
        self._validate_configuration_snapshot_bindings(snapshot)
        return TaskEventDraft.build(
            event_id=event_id,
            task_id=self.task_id,
            event_type=TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED,
            payload={"configuration_snapshot": snapshot.model_dump(mode="json")},
            occurred_at=occurred_at,
            correlation_id=self.task_id,
            causation_id=self.last_event_id,
        )

    def _apply(self, event: TaskEvent) -> TaskAggregate:
        payload = event.decoded_payload()
        try:
            if event.event_type is TaskEventType.TASK_CREATED:
                if self.status is not None:
                    raise EventStreamError("TASK_CREATED must be the first task event")
                goal = Goal.model_validate(payload["goal"])
                return replace(
                    self,
                    sequence=event.sequence,
                    status=TaskStatus.DRAFT,
                    goal=goal,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.TASK_COMMITTED:
                if self.status is not TaskStatus.DRAFT:
                    raise EventStreamError("TASK_COMMITTED requires DRAFT state")
                commitment = Commitment.model_validate(payload["commitment"])
                workflow = WorkflowGraph.model_validate(payload["workflow"])
                expected_outcome = ExpectedOutcome.model_validate(
                    payload["expected_outcome"]
                )
                self._validate_commitment_bindings(
                    commitment,
                    workflow,
                    expected_outcome,
                )
                if payload["workflow_digest"] != workflow.canonical_digest():
                    raise EventStreamError("TASK_COMMITTED workflow digest mismatch")
                return replace(
                    self,
                    sequence=event.sequence,
                    status=TaskStatus.COMMITTED,
                    commitment=commitment,
                    workflow=workflow,
                    expected_outcome=expected_outcome,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED:
                if self.status is not TaskStatus.COMMITTED or self.run is not None:
                    raise EventStreamError(
                        "configuration snapshot requires COMMITTED state before run"
                    )
                if self.configuration_snapshot is not None:
                    raise EventStreamError("configuration snapshot is already sealed")
                snapshot = TaskConfigurationSnapshot.model_validate(
                    payload["configuration_snapshot"]
                )
                self._validate_configuration_snapshot_bindings(snapshot)
                return replace(
                    self,
                    sequence=event.sequence,
                    configuration_snapshot=snapshot,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.RUN_STARTED:
                if self.status is not TaskStatus.COMMITTED:
                    raise EventStreamError("RUN_STARTED requires COMMITTED state")
                run = AgentRun.model_validate(payload["run"])
                self._validate_run_bindings(run)
                return replace(
                    self,
                    sequence=event.sequence,
                    status=TaskStatus.RUNNING,
                    run=run,
                    approval=self.approval,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.APPROVAL_RECORDED:
                approval = ApprovalDecision.model_validate(payload["approval"])
                return replace(
                    self,
                    sequence=event.sequence,
                    approval=approval,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.WAIT_REGISTERED:
                if self.run is None:
                    raise EventStreamError("wait registration requires an active run")
                run = AgentRun.model_validate(payload["run"])
                if (
                    run.status is not RunStatus.WAITING_EVENT
                    or run.wait_condition is None
                ):
                    raise EventStreamError(
                        "WAIT_REGISTERED requires WAITING_EVENT run state"
                    )
                return replace(
                    self,
                    sequence=event.sequence,
                    status=TaskStatus.WAITING,
                    run=run,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.EXTERNAL_SIGNAL_RECORDED:
                if self.run is None:
                    raise EventStreamError("external signal requires an active run")
                if not isinstance(payload.get("signal"), dict):
                    raise EventStreamError("external signal payload is missing")
                return replace(
                    self,
                    sequence=event.sequence,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.WAIT_SATISFIED:
                if self.run is None:
                    raise EventStreamError("wait satisfaction requires an active run")
                run = AgentRun.model_validate(payload["run"])
                if (
                    run.status is not RunStatus.RUNNING
                    or run.wait_condition is not None
                ):
                    raise EventStreamError("WAIT_SATISFIED requires a resumed run")
                return replace(
                    self,
                    sequence=event.sequence,
                    status=TaskStatus.RUNNING,
                    run=run,
                    last_event_id=event.event_id,
                )

            if event.event_type in {
                TaskEventType.WAIT_TIMED_OUT,
                TaskEventType.COMMITMENT_EXPIRED,
            }:
                if self.run is None:
                    raise EventStreamError("deadline event requires an active run")
                run = AgentRun.model_validate(payload["run"])
                if run.status is not RunStatus.FAILED:
                    raise EventStreamError("deadline event requires FAILED run state")
                return replace(
                    self,
                    sequence=event.sequence,
                    status=TaskStatus.FAILED,
                    run=run,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.RUN_PLAN_REBOUND:
                if self.run is None or self.workflow is None:
                    raise EventStreamError(
                        "run plan rebound requires an active workflow"
                    )
                workflow = WorkflowGraph.model_validate(payload["workflow"])
                rebound = RunPlanRebound.model_validate(payload["rebound"])
                run = AgentRun.model_validate(payload["run"])
                if rebound.task_id != self.task_id or rebound.run_id != self.run.run_id:
                    raise EventStreamError("run plan rebound scope mismatch")
                if rebound.previous_workflow_version != self.workflow.version:
                    raise EventStreamError("run plan rebound base version mismatch")
                if rebound.previous_workflow_digest != self.workflow.canonical_digest():
                    raise EventStreamError("run plan rebound base digest mismatch")
                if rebound.new_workflow_digest != workflow.canonical_digest():
                    raise EventStreamError("run plan rebound new digest mismatch")
                if (
                    run.workflow_version != workflow.version
                    or run.workflow_digest != workflow.canonical_digest()
                    or run.status is not RunStatus.PAUSED
                ):
                    raise EventStreamError("run plan rebound run binding mismatch")
                return replace(
                    self,
                    sequence=event.sequence,
                    status=TaskStatus.PAUSED,
                    workflow=workflow,
                    run=run,
                    approval=None,
                    last_rebound=rebound,
                    last_event_id=event.event_id,
                )

            if event.event_type in {
                TaskEventType.COMPENSATION_STARTED,
                TaskEventType.ACTION_COMPENSATED,
                TaskEventType.COMPENSATION_FAILED,
                TaskEventType.COMPENSATION_BLOCKED,
            }:
                if self.run is None:
                    raise EventStreamError("compensation event requires an active run")
                record = PatchCompensationRecord.model_validate(payload["compensation"])
                expected_status = {
                    TaskEventType.COMPENSATION_STARTED: CompensationStatus.STARTED,
                    TaskEventType.ACTION_COMPENSATED: CompensationStatus.COMPENSATED,
                    TaskEventType.COMPENSATION_FAILED: CompensationStatus.FAILED,
                    TaskEventType.COMPENSATION_BLOCKED: CompensationStatus.BLOCKED,
                }[event.event_type]
                if record.status is not expected_status:
                    raise EventStreamError("compensation event/status mismatch")
                if record.task_id != self.task_id or record.run_id != self.run.run_id:
                    raise EventStreamError("compensation record scope mismatch")
                return replace(
                    self,
                    sequence=event.sequence,
                    compensations=self.compensations + (record,),
                    last_event_id=event.event_id,
                )

            if event.event_type in {
                TaskEventType.RUN_QUEUED,
                TaskEventType.NODE_STARTED,
                TaskEventType.NODE_COMPLETED,
                TaskEventType.NODE_FAILED,
                TaskEventType.ACTION_PROPOSED,
                TaskEventType.CANDIDATES_GENERATED,
                TaskEventType.PROVIDER_RESPONDED,
                TaskEventType.POLICY_DECIDED,
                TaskEventType.ACTION_RECEIPT_RECORDED,
                TaskEventType.APPROVAL_REQUESTED,
                TaskEventType.CORRECTION_WRITTEN,
                TaskEventType.RUN_PAUSED,
                TaskEventType.RUN_RESUMED,
                TaskEventType.RUN_CANCELLED,
                TaskEventType.RUN_SUCCEEDED,
                TaskEventType.RUN_FAILED,
            }:
                if self.run is None:
                    raise EventStreamError("run event requires an active run")
                run_payload = payload.get("run")
                run = AgentRun.model_validate(run_payload) if run_payload else self.run
                self._validate_run_projection_bindings(run)
                task_status = self.status
                if event.event_type in {
                    TaskEventType.RUN_QUEUED,
                    TaskEventType.RUN_RESUMED,
                }:
                    task_status = TaskStatus.RUNNING
                elif (
                    event.event_type is TaskEventType.APPROVAL_REQUESTED
                    and run.status is RunStatus.WAITING_APPROVAL
                ):
                    task_status = TaskStatus.WAITING
                elif event.event_type is TaskEventType.RUN_PAUSED:
                    task_status = TaskStatus.PAUSED
                elif event.event_type is TaskEventType.RUN_CANCELLED:
                    task_status = TaskStatus.CANCELLED
                elif event.event_type is TaskEventType.RUN_SUCCEEDED:
                    task_status = TaskStatus.COMPLETED
                elif event.event_type is TaskEventType.RUN_FAILED:
                    task_status = TaskStatus.FAILED
                approval = self.approval
                if event.event_type is TaskEventType.ACTION_PROPOSED:
                    approval = None
                if event.event_type is TaskEventType.APPROVAL_RECORDED:
                    approval = ApprovalDecision.model_validate(payload["approval"])
                return replace(
                    self,
                    sequence=event.sequence,
                    status=task_status,
                    run=run,
                    approval=approval,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.OUTCOME_OBSERVED:
                if self.run is None:
                    raise EventStreamError("outcome requires an active run")
                outcome = ObservedOutcome.model_validate(payload["outcome"])
                return replace(
                    self,
                    sequence=event.sequence,
                    observed_outcome=outcome,
                    status=TaskStatus.VERIFYING,
                    last_event_id=event.event_id,
                )

            if event.event_type is TaskEventType.ARTIFACT_RECORDED:
                artifact_id = str(payload["artifact_id"])
                return replace(
                    self,
                    sequence=event.sequence,
                    artifacts=self.artifacts + (artifact_id,),
                    last_event_id=event.event_id,
                )
        except (KeyError, ValidationError, ScopeMismatchError) as exc:
            raise EventStreamError(
                f"invalid {event.event_type.value} payload: {exc}"
            ) from exc
        if event.event_type in {
            TaskEventType.SESSION_TURN_STARTED,
            TaskEventType.SESSION_TURN_COMPLETED,
            TaskEventType.SESSION_OPENED,
            TaskEventType.SESSION_MESSAGE_RECORDED,
            TaskEventType.SESSION_APPROVAL_PENDING,
            TaskEventType.SESSION_APPROVAL_EXECUTION_CLAIMED,
            TaskEventType.SESSION_APPROVAL_RESOLVED,
            TaskEventType.SESSION_TURN_CONTINUATION_CHECKPOINT,
            TaskEventType.SESSION_CONTEXT_COMPACTED,
            TaskEventType.SESSION_PERMISSION_MODE_SET,
            TaskEventType.POLICY_VERDICT_RECORDED,
            TaskEventType.SESSION_CLOSED,
            # Form B child-agent audit markers: durable records about a child
            # (digest-only), never a state transition of the parent aggregate.
            TaskEventType.CHILD_AGENT_SPAWNED,
            TaskEventType.CHILD_AGENT_FINISHED,
            TaskEventType.CHILD_AGENT_RECONCILED,
        }:
            # Chat-turn audit markers carry no aggregate state transition.
            return replace(
                self,
                sequence=event.sequence,
                last_event_id=event.event_id,
            )
        raise EventStreamError(f"unsupported task event: {event.event_type.value}")

    def _validate_commitment_bindings(
        self,
        commitment: Commitment,
        workflow: WorkflowGraph,
        expected_outcome: ExpectedOutcome,
    ) -> None:
        if self.goal is None:
            raise InvalidTransitionError("task has no goal")
        if (
            commitment.task_id != self.task_id
            or expected_outcome.task_id != self.task_id
        ):
            raise ScopeMismatchError("task binding mismatch")
        if commitment.goal_id != self.goal.goal_id:
            raise ScopeMismatchError("goal binding mismatch")
        scoped = (commitment, workflow, expected_outcome)
        if any(item.tenant_id != self.goal.tenant_id for item in scoped):
            raise ScopeMismatchError("tenant scope mismatch")
        if any(item.workspace_id != self.goal.workspace_id for item in scoped):
            raise ScopeMismatchError("workspace scope mismatch")
        evaluator_ref = (
            f"evaluator:{expected_outcome.evaluator_type}:"
            f"{expected_outcome.evaluator_version}"
        )
        if evaluator_ref not in workflow.evaluator_refs:
            raise ScopeMismatchError(
                "expected outcome evaluator is not bound to workflow"
            )

    def _validate_run_bindings(self, run: AgentRun) -> None:
        if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise ScopeMismatchError(
                "RUN_STARTED requires run status QUEUED or RUNNING"
            )
        self._validate_run_projection_bindings(run)

    def _validate_run_projection_bindings(self, run: AgentRun) -> None:
        if (
            self.commitment is None
            or self.workflow is None
            or self.expected_outcome is None
        ):
            raise InvalidTransitionError("task is missing committed contracts")
        if run.task_id != self.task_id:
            raise ScopeMismatchError("run task binding mismatch")
        if run.commitment_id != self.commitment.commitment_id:
            raise ScopeMismatchError("run commitment binding mismatch")
        if (
            run.workflow_id != self.workflow.workflow_id
            or run.workflow_version != self.workflow.version
        ):
            raise ScopeMismatchError("run workflow version binding mismatch")
        if run.workflow_digest != self.workflow.canonical_digest():
            raise ScopeMismatchError("run workflow digest mismatch")
        if run.expected_outcome_id != self.expected_outcome.expected_outcome_id:
            raise ScopeMismatchError("run expected outcome binding mismatch")
        if run.policy_version != self.workflow.policy_version:
            raise ScopeMismatchError("run policy version binding mismatch")
        if run.tenant_id != self.commitment.tenant_id:
            raise ScopeMismatchError("run tenant scope mismatch")
        if run.workspace_id != self.commitment.workspace_id:
            raise ScopeMismatchError("run workspace scope mismatch")
        snapshot = self.configuration_snapshot
        if snapshot is None:
            if (
                run.configuration_snapshot_id is not None
                or run.configuration_snapshot_digest is not None
            ):
                raise ScopeMismatchError(
                    "run cannot bind a missing configuration snapshot"
                )
            return
        if (
            run.configuration_snapshot_id != snapshot.snapshot_id
            or run.configuration_snapshot_digest != snapshot.snapshot_digest
            or run.run_id != snapshot.reserved_run_id
        ):
            raise ScopeMismatchError("run configuration snapshot binding mismatch")
        if run.provider_profile_id != snapshot.provider_profile.profile_id:
            raise ScopeMismatchError("run provider profile snapshot binding mismatch")

    def _validate_configuration_snapshot_bindings(
        self,
        snapshot: TaskConfigurationSnapshot,
    ) -> None:
        if (
            self.goal is None
            or self.commitment is None
            or self.workflow is None
            or self.expected_outcome is None
        ):
            raise InvalidTransitionError("task is missing committed contracts")
        if snapshot.consumer_task_id != self.task_id:
            raise ScopeMismatchError("configuration snapshot task binding mismatch")
        if snapshot.commitment_id != self.commitment.commitment_id:
            raise ScopeMismatchError(
                "configuration snapshot commitment binding mismatch"
            )
        if (
            snapshot.tenant_id != self.commitment.tenant_id
            or snapshot.workspace_id != self.commitment.workspace_id
        ):
            raise ScopeMismatchError("configuration snapshot scope mismatch")
        if (
            snapshot.principal_id != self.goal.created_by
            or snapshot.principal_id != self.commitment.accepted_by
        ):
            raise ScopeMismatchError(
                "configuration snapshot principal binding mismatch"
            )
        if snapshot.workflow != self.workflow:
            raise ScopeMismatchError("configuration snapshot workflow binding mismatch")
        if (
            snapshot.policy_version != self.workflow.policy_version
            or snapshot.policy_version != "policy-1"
            or snapshot.policy_digest != POLICY_KERNEL_V1_DIGEST
        ):
            raise ScopeMismatchError("configuration snapshot policy binding mismatch")
        if snapshot.expected_outcome != self.expected_outcome:
            raise ScopeMismatchError(
                "configuration snapshot expected outcome binding mismatch"
            )
