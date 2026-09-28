"""Run-time EvidenceAccessor implementation.

Reads tool results from NODE_COMPLETED events (cross-referenced with the
workflow graph to map node_id → capability/tool name) and artifacts from
the ArtifactReader callback.
"""

from __future__ import annotations

import json
from typing import Any

from .event_store import TaskEventStore
from .task_aggregate import TaskAggregate
from .task_service import ArtifactReader


class RuntimeEvidenceAccessor:
    """Evidence accessor backed by the durable event store + artifact reader."""

    def __init__(
        self,
        task_id: str,
        run_id: str,
        aggregate: TaskAggregate,
        event_store: TaskEventStore,
        artifact_reader: ArtifactReader | None,
    ) -> None:
        self._task_id = task_id
        self._run_id = run_id
        self._aggregate = aggregate
        self._event_store = event_store
        self._artifact_reader = artifact_reader
        self._node_completed: list[dict[str, Any]] | None = None
        self._node_to_capability: dict[str, str] | None = None

    def _ensure_loaded(self) -> None:
        if self._node_completed is not None:
            return
        events = self._event_store.read(self._task_id)
        self._node_completed = []
        for event in events:
            if event.correlation_id != self._run_id:
                continue
            from agent_os_contracts import TaskEventType
            if event.event_type is TaskEventType.NODE_COMPLETED:
                payload = event.decoded_payload()
                if isinstance(payload, dict):
                    self._node_completed.append(payload)
        # Map node_id → capability_id from workflow graph
        self._node_to_capability = {}
        if self._aggregate.workflow is not None:
            for node in self._aggregate.workflow.nodes:
                if node.capability:
                    self._node_to_capability[node.node_id] = node.capability

    def artifact_content(self, artifact_id: str) -> bytes | None:
        if self._artifact_reader is None:
            return None
        return self._artifact_reader(artifact_id)

    def artifact_json(self, artifact_id: str) -> Any:
        raw = self.artifact_content(artifact_id)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def tool_result(
        self, tool_name: str, *, latest: bool = True
    ) -> dict[str, Any] | None:
        self._ensure_loaded()
        assert self._node_completed is not None
        assert self._node_to_capability is not None
        # Find NODE_COMPLETED events whose node maps to the requested capability
        matches: list[dict[str, Any]] = []
        for payload in self._node_completed:
            node_id = payload.get("node_id")
            if not isinstance(node_id, str):
                continue
            capability = self._node_to_capability.get(node_id, "")
            # Capability may be fully qualified (e.g. "email.send_email")
            # Match on suffix or exact
            if capability == tool_name or capability.endswith(f".{tool_name}"):
                output = payload.get("output")
                if isinstance(output, dict):
                    matches.append(output)
        if not matches:
            return None
        return matches[-1] if latest else matches[0]

    def state_snapshot(self, label: str) -> dict[str, Any] | None:
        # MVP: no pre/post-run snapshot infrastructure
        return None
