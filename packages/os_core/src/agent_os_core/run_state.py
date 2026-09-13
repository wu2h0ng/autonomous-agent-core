from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    RunStatus,
    TaskEventType,
)

from .errors import ConcurrentWriteError, RunExecutionError


class RunStateMachine:
    """Lease acquisition, status transitions, and early-exit guards for a run."""

    def __init__(self, tasks: Any) -> None:
        self._tasks = tasks

    def acquire_lease(
        self, run_id: str, recover_stale: bool
    ) -> tuple[int, str | None]:
        store = getattr(self._tasks._event_store, "acquire_lease", None)
        if store is None:
            return 0, None
        owner = f"worker:{uuid4()}"
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        try:
            fence = store(run_id, owner, expiry)
        except ConcurrentWriteError:
            if not recover_stale:
                raise
            recover = getattr(
                self._tasks._event_store, "recover_lease", None
            )
            if recover is None:
                raise
            fence = recover(run_id, owner, expiry)
        return fence, owner

    def release_lease(self, run_id: str, owner: str | None) -> None:
        if owner is None:
            return
        release = getattr(
            self._tasks._event_store, "release_lease", None
        )
        if release is not None:
            release(run_id, owner)

    def check_waiting_event(
        self, task_id: str, run: Any, aggregate: Any
    ) -> Any | None:
        if run.status is not RunStatus.WAITING_EVENT:
            return None
        condition = run.wait_condition
        if condition is None:
            raise RunExecutionError(
                "WAITING_EVENT run is missing its durable wait condition"
            )
        now = self._tasks.now()
        if now >= aggregate.commitment.expires_at:
            return self._tasks.expire_commitment(task_id)
        if now >= condition.deadline:
            return self._tasks.expire_wait(task_id)
        return self._tasks.get_task(task_id)

    def check_commitment_expiry(
        self, task_id: str, aggregate: Any
    ) -> Any | None:
        if self._tasks.now() >= aggregate.commitment.expires_at:
            return self._tasks.expire_commitment(task_id)
        return None

    def transition_to_running(
        self, task_id: str, run: Any, lease_fence: int
    ) -> Any:
        resume_states = {
            RunStatus.WAITING_APPROVAL,
            RunStatus.PAUSED,
            RunStatus.FAILED,
        }
        return self._tasks.update_run_status(
            task_id,
            RunStatus.RUNNING,
            event_type=(
                TaskEventType.RUN_RESUMED
                if run.status in resume_states
                else TaskEventType.RUN_QUEUED
            ),
            lease_fence=lease_fence,
        )
