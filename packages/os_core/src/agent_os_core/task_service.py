from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from agent_os_contracts import (
    AgentRun,
    Commitment,
    ExpectedOutcome,
    Goal,
    RunStatus,
    TaskStatus,
    WorkflowGraph,
    TaskEventDraft,
    TaskEventType,
    ObservedOutcome,
)

from .errors import InvalidTransitionError, TaskNotFoundError
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
            RunStatus.WAITING_EVENT: {RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.CANCELLED, RunStatus.FAILED},
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
        return self.append_event(
            task_id,
            event_type,
            {"run": run.model_dump(mode="json")},
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
