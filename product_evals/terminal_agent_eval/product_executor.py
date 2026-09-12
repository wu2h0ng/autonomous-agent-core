"""Real product executor for TERMINAL-AGENT-EVAL-0.

Drives the product's own surface client (``apps/cli/surface_client.py``) — the
same protocol the terminal CLI uses — to run one frozen task per session and
read back the real durable events for metric projection. The daemon/provider
bring-up (hermetic scripted provider) is the harness's responsibility, matching
the repo's existing wave-1 e2e pattern; this adapter contains no mocked
product logic.

Approvals: the executor NEVER auto-approves. If a turn pauses at
WAITING_APPROVAL it is left pending (fail-closed): the task then fails its
acceptance command, and any unapproved tier>=3 receipt is counted unsafe by the
projector.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .models import EvalTask


class SurfaceSessionClient(Protocol):
    def open_session(self, statement: str) -> Any: ...
    def run_turn(self, session_id: str, text: str) -> Any: ...
    def events(self, task_id: str, *, after_sequence: int = ...) -> Any: ...


def _event_to_mapping(event: Any) -> Mapping[str, Any]:
    event_type = getattr(event, "event_type", "")
    payload_json = getattr(event, "payload_json", "{}")
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else {}
    except json.JSONDecodeError:
        payload = {}
    return {
        "event_type": str(getattr(event_type, "value", event_type)),
        "sequence": getattr(event, "sequence", 0),
        "occurred_at": str(getattr(event, "occurred_at", "")),
        "payload": payload,
    }


class ProductTurnExecutor:
    """One session per task; real durable events; no auto-approval."""

    def __init__(
        self,
        client: SurfaceSessionClient,
        *,
        workspace_dir: str | Path,
        verify_timeout_seconds: float = 120.0,
    ) -> None:
        self._client = client
        self._workspace = Path(workspace_dir)
        self._verify_timeout = verify_timeout_seconds

    def run_task(self, task: EvalTask) -> tuple[Sequence[Mapping[str, Any]], bool]:
        snapshot = self._client.open_session(f"TERMINAL-AGENT-EVAL-0 {task.task_id}")
        session_id = snapshot.session.session_id
        task_id = snapshot.session.task_id

        # Active turn only if the session did not immediately pause; either way
        # we never approve. A paused turn simply leaves no successful receipt.
        self._client.run_turn(session_id, task.input)

        events = self._collect_events(task_id)
        return events, self._verify(task)

    def _collect_events(self, task_id: str) -> list[Mapping[str, Any]]:
        collected: list[Mapping[str, Any]] = []
        after = 0
        while True:
            batch = self._client.events(task_id, after_sequence=after)
            collected.extend(_event_to_mapping(event) for event in getattr(batch, "events", ()))
            next_sequence = int(getattr(batch, "next_sequence", after))
            if next_sequence <= after:
                break
            after = next_sequence
        return collected

    def _verify(self, task: EvalTask) -> bool:
        try:
            completed = subprocess.run(
                list(task.verify_command),
                cwd=self._workspace,
                capture_output=True,
                timeout=self._verify_timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0
