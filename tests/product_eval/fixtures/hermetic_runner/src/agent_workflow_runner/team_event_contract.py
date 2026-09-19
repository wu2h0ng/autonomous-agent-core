"""Hermetic, offline vendor of the pinned ``TeamEvent`` contract.

This is a *recorded* (vendored) copy of the contract surface that the real
cross-repo workflow runner ``agent_workflow_runner`` exposes:

* :func:`get_team_event_schema` -- the closed Draft-07 subset the runner exports
  via ``team event-schema``.
* :func:`build_team_event_record` -- the public builder the runner exposes via
  ``agent_workflow_runner.team_event_contract``.

It exists ONLY so the product_eval suite can qualify the *consumer* side (the
fail-closed JSON-schema consumer and the authority binding) without checking out
the sibling worktree ``ai-agent-engineering-workflow/.worktrees/team-event-
contract-v1-20260713`` pinned at ``50eb4d27...``. The schema bytes are byte-
identical to ``product_evals/spine_e2e_4/runner_team_event_schema.json``.

This is a SHA-pinned fixture, not a re-implementation of the runner. If the real
runner contract ever changes, this fixture must be re-recorded from the pinned
commit and the consumer-side tests re-frozen.
"""

from __future__ import annotations

from typing import Any, Mapping

# Byte-identical to product_evals/spine_e2e_4/runner_team_event_schema.json.
TEAM_EVENT_SCHEMA: Mapping[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "additionalProperties": False,
    "properties": {
        "agent_id": {"minLength": 1, "type": "string"},
        "approval_request_id": {
            "minLength": 1,
            "type": ["string", "null"],
        },
        "artifact": {"type": ["string", "null"]},
        "evidence_refs": {
            "items": {"type": "string"},
            "type": "array",
        },
        "permission_action": {
            "minLength": 1,
            "type": ["string", "null"],
        },
        "schema_version": {"const": "team-event-v1", "type": "string"},
        "source_decision_id": {
            "minLength": 1,
            "pattern": "^[A-Za-z0-9_.-]+$",
            "type": "string",
        },
        "source_decision_type": {
            "minLength": 1,
            "pattern": "^[A-Za-z0-9_.-]+$",
            "type": "string",
        },
        "source_evidence_refs": {
            "items": {"type": "string"},
            "type": "array",
        },
        "source_goal_id": {
            "minLength": 1,
            "pattern": "^[A-Za-z0-9_.-]+$",
            "type": "string",
        },
        "stream_file": {"type": ["string", "null"]},
        "summary": {"type": "string"},
        "task_id": {
            "minLength": 1,
            "type": ["string", "null"],
        },
        "ts": {"minLength": 1, "type": "string"},
        "type": {
            "enum": [
                "AGENT_STARTED",
                "AGENT_STREAM_DELTA",
                "APPROVAL_DECIDED",
                "APPROVAL_REQUESTED",
                "ARTIFACT_PROPOSED",
                "BLOCKED",
                "EVIDENCE_APPENDED",
                "RISK_RAISED",
                "TASK_ASSIGNED",
                "TASK_CREATED",
                "TASK_DONE",
                "TASK_NOT_MET",
                "TEAM_SUMMARY",
            ],
            "minLength": 1,
            "type": "string",
        },
    },
    "required": [
        "schema_version",
        "ts",
        "type",
        "agent_id",
        "task_id",
        "summary",
        "artifact",
        "stream_file",
        "permission_action",
        "approval_request_id",
        "evidence_refs",
    ],
    "title": "team-event-v1",
    "type": "object",
}


def get_team_event_schema() -> dict[str, Any]:
    """Return a deep copy of the pinned TeamEvent schema."""

    import copy

    return copy.deepcopy(dict(TEAM_EVENT_SCHEMA))


def build_team_event_record(
    *,
    ts: str,
    event_type: str,
    agent_id: str,
    task_id: str | None,
    summary: str,
    artifact: str | None,
    stream_file: str | None,
    permission_action: str | None,
    approval_request_id: str | None,
    evidence_refs: list[str],
    source_decision_id: str,
    source_goal_id: str,
    source_decision_type: str,
    source_evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Build a governed TeamEvent record exactly as the runner would emit it."""

    record: dict[str, Any] = {
        "schema_version": "team-event-v1",
        "ts": ts,
        "type": event_type,
        "agent_id": agent_id,
        "task_id": task_id,
        "summary": summary,
        "artifact": artifact,
        "stream_file": stream_file,
        "permission_action": permission_action,
        "approval_request_id": approval_request_id,
        "evidence_refs": list(evidence_refs),
        "source_decision_id": source_decision_id,
        "source_goal_id": source_goal_id,
        "source_decision_type": source_decision_type,
    }
    # source_evidence_refs is optional in the pinned schema; emit it only when
    # the caller actually bound it (matches the runner's behaviour).
    if source_evidence_refs is not None:
        record["source_evidence_refs"] = list(source_evidence_refs)
    return record
