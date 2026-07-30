from __future__ import annotations

import json
from typing import Any

from agent_os_contracts import (
    ActionContract,
    RunPlanRebound,
    TaskEventType,
)


class ContextRestorer:
    """Reconstruct execution context from durable event history."""

    def __init__(self, read_events: Any) -> None:
        self._read_events = read_events

    def restore(
        self, task_id: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        context = dict(inputs)
        completed: set[str] = set()
        proposal_capabilities: set[str] = set()
        evidence: list[tuple[str, str | None]] = []
        for event in self._read_events(task_id):
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.NODE_COMPLETED:
                output = payload.get("output")
                node_id = payload.get("node_id")
                if isinstance(node_id, str):
                    completed.add(node_id)
                    if isinstance(output, dict):
                        context[node_id] = output
            elif event.event_type is TaskEventType.PROVIDER_RESPONDED:
                provider_output = payload.get("provider_output")
                node_id = payload.get("node_id")
                if isinstance(node_id, str) and isinstance(provider_output, dict):
                    context[node_id] = provider_output
                    proposals = provider_output.get("tool_proposals", ())
                    if isinstance(proposals, list):
                        for proposal in proposals:
                            if isinstance(proposal, dict):
                                capability_id = proposal.get("capability_id")
                                arguments_json = proposal.get("arguments_json")
                                if isinstance(capability_id, str) and isinstance(
                                    arguments_json, str
                                ):
                                    arguments = json.loads(arguments_json)
                                    if isinstance(arguments, dict):
                                        context[capability_id] = arguments
                                        proposal_capabilities.add(capability_id)
            elif event.event_type is TaskEventType.ACTION_PROPOSED:
                action_payload = payload.get("action")
                if isinstance(action_payload, dict):
                    action = ActionContract.model_validate(action_payload)
                    context[f"action:{action.capability_id}"] = action
            elif event.event_type is TaskEventType.RUN_PLAN_REBOUND:
                rebound_payload = payload.get("rebound")
                if not isinstance(rebound_payload, dict):
                    raise RuntimeError("run plan rebound payload is missing")
                rebound = RunPlanRebound.model_validate(rebound_payload)
                invalidated = set(rebound.invalidated_node_ids)
                for node_id in invalidated:
                    context.pop(node_id, None)
                for key, value in tuple(context.items()):
                    if not key.startswith("action:") or not isinstance(
                        value, ActionContract
                    ):
                        continue
                    context.pop(key, None)
                    context.pop(value.capability_id, None)
                for capability_id in proposal_capabilities:
                    context.pop(capability_id, None)
                proposal_capabilities.clear()
                evidence = [
                    (artifact_id, node_id)
                    for artifact_id, node_id in evidence
                    if node_id is not None and node_id in completed
                ]
            elif event.event_type is TaskEventType.ARTIFACT_RECORDED:
                artifact_id = payload.get("artifact_id")
                if isinstance(artifact_id, str):
                    node_id = payload.get("node_id")
                    evidence.append(
                        (artifact_id, node_id if isinstance(node_id, str) else None)
                    )
        if evidence:
            context["evidence_refs"] = tuple(
                artifact_id for artifact_id, _ in evidence
            )
        return context

    def completed_nodes(self, task_id: str) -> set[str]:
        completed: set[str] = set()
        for event in self._read_events(task_id):
            if event.event_type is TaskEventType.NODE_COMPLETED:
                node_id = event.decoded_payload().get("node_id")
                if isinstance(node_id, str):
                    completed.add(node_id)
        return completed
