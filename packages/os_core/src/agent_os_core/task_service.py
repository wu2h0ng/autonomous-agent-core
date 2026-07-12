from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    AgentRun,
    ApprovalDecision,
    Commitment,
    ExpectedOutcome,
    ExternalSignal,
    Goal,
    NodeKind,
    NodeSpec,
    RunPlanRebound,
    RunStatus,
    TaskStatus,
    WorkflowGraph,
    WaitCondition,
    TaskEventDraft,
    TaskEventType,
    ObservedOutcome,
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
from .task_aggregate import TaskAggregate


IdFactory = Callable[[str], str]
Clock = Callable[[], datetime]


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
    ) -> None:
        self._event_store = event_store
        self._id_factory = id_factory
        self._clock = clock

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

    def start_run(self, task_id: str, *, provider_profile_id: str = "provider-profile:unbound") -> TaskAggregate:
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

        run = AgentRun(
            run_id=self._id_factory("run"),
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
            provider_profile_id=provider_profile_id,
            policy_version=aggregate.workflow.policy_version,
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

    def append_event(
        self,
        task_id: str,
        event_type: TaskEventType,
        payload: dict[str, object],
        *,
        correlation_id: str | None = None,
    ) -> TaskAggregate:
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

    def record_outcome(self, task_id: str, outcome: ObservedOutcome) -> TaskAggregate:
        return self.append_event(
            task_id,
            TaskEventType.OUTCOME_OBSERVED,
            {"outcome": outcome.model_dump(mode="json")},
            correlation_id=outcome.run_id,
        )

    def record_artifact(self, task_id: str, artifact_id: str) -> TaskAggregate:
        return self.append_event(
            task_id,
            TaskEventType.ARTIFACT_RECORDED,
            {"artifact_id": artifact_id},
        )
