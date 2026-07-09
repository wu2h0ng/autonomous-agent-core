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

    def start_run(self, task_id: str) -> TaskAggregate:
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
            status=RunStatus.RUNNING,
            created_at=self._clock(),
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
