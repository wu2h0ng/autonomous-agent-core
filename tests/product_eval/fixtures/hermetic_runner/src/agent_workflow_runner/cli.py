"""Hermetic offline vendor of the ``agent_workflow_runner`` CLI surface.

Implements exactly the subcommands the product_eval qualification suite drives:

* ``team event-schema``
* ``init ...``
* ``permission request ...``
* ``permission decide ...``
* ``team event ...``

It writes the same ``.agent_runs/<run_id>/`` ledger layout (approval_requests.jsonl,
approvals.jsonl, agent_events.jsonl) the real runner writes, so the in-repo
consumer-side authority binding and JSON-schema qualification can run hermetically
with no sibling worktree checked out.

Timestamps are pinned to a fixed past instant so the qualification harness's
"wait until after the runner second" boundary returns immediately. This is a
recorded fixture, not the real runner implementation.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from .team_event_contract import build_team_event_record, get_team_event_schema

# Fixed past instant: the qualification harness waits until wall-clock exceeds the
# request ts; a 2026-07 instant is always in the past during CI, so no sleeping.
_REQUEST_TS = "2026-07-13T10:00:00+00:00"
_APPROVAL_TS = "2026-07-13T10:00:01+00:00"


def _parse_pairs(argv: Sequence[str]) -> dict[str, str]:
    """Parse ``--flag value`` pairs (value may be empty)."""

    out: dict[str, str] = {}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token.startswith("--"):
            key = token[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                out[key] = argv[i + 1]
                i += 2
            else:
                out[key] = ""
                i += 1
        else:
            i += 1
    return out


def _run_root(workspace_root: str, run_id: str) -> Path:
    root = Path(workspace_root) / ".agent_runs" / run_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read_single_jsonl(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    return rows[0]


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _cmd_team_event_schema() -> int:
    json.dump(get_team_event_schema(), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def _cmd_init(pairs: dict[str, str]) -> int:
    # The real runner scaffolds the run root; the hermetic version just ensures it.
    _run_root(pairs["workspace-root"], pairs["run-id"])
    return 0


def _cmd_permission_request(pairs: dict[str, str]) -> int:
    run_root = _run_root(pairs["workspace-root"], pairs["run-id"])
    request_id = f"request-{uuid.uuid4().hex[:12]}"
    row = {
        "request_id": request_id,
        "run_id": pairs["run-id"],
        "agent_id": pairs["agent-id"],
        "action": pairs["action"],
        "affected_paths": [pairs["affected-path"]],
        "evidence_refs": [pairs["evidence-ref"]],
        "source_decision_id": pairs["source-decision-id"],
        "source_goal_id": pairs["source-goal-id"],
        "source_decision_type": pairs["source-decision-type"],
        "risk_level": pairs.get("risk-level", "R2"),
        "note": pairs.get("note", ""),
        "ts": _REQUEST_TS,
    }
    _append_jsonl(run_root / "approval_requests.jsonl", row)
    json.dump({"request": {"request_id": request_id, "ts": _REQUEST_TS}}, sys.stdout)
    sys.stdout.write("\n")
    return 0


def _cmd_permission_decide(pairs: dict[str, str]) -> int:
    run_root = _run_root(pairs["workspace-root"], pairs["run-id"])
    request = _read_single_jsonl(run_root / "approval_requests.jsonl")
    # The approval inherits the request's source binding so the authority verifier
    # sees request/approval source identity.
    row = {
        "request_id": pairs["request-id"],
        "run_id": pairs["run-id"],
        "decision": pairs["decision"],
        "decided_by": pairs["decided-by"],
        "note": pairs.get("note", ""),
        "source_decision_id": request["source_decision_id"],
        "source_goal_id": request["source_goal_id"],
        "source_decision_type": request["source_decision_type"],
        "ts": _APPROVAL_TS,
    }
    _append_jsonl(run_root / "approvals.jsonl", row)
    return 0


def _cmd_team_event(pairs: dict[str, str]) -> int:
    run_root = _run_root(pairs["workspace-root"], pairs["run-id"])
    request = _read_single_jsonl(run_root / "approval_requests.jsonl")
    record = build_team_event_record(
        ts="2026-07-13T10:00:02+00:00",
        event_type=pairs["type"],
        agent_id=pairs["agent-id"],
        task_id=pairs.get("task-id") or None,
        summary=pairs["summary"],
        artifact=pairs.get("artifact") or None,
        stream_file=None,
        permission_action=request["action"],
        approval_request_id=pairs["approval-request-id"],
        evidence_refs=[pairs["evidence-ref"]],
        source_decision_id=pairs["source-decision-id"],
        source_goal_id=pairs["source-goal-id"],
        source_decision_type=pairs["source-decision-type"],
    )
    _append_jsonl(run_root / "agent_events.jsonl", record)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Structure: <domain> <verb> [--flag value ...]
    if len(args) < 2:
        print("usage: agent_workflow_runner <domain> <verb> [opts]", file=sys.stderr)
        return 2
    domain, verb = args[0], args[1]
    pairs = _parse_pairs(args[2:])
    if domain == "team" and verb == "event-schema":
        return _cmd_team_event_schema()
    if domain == "init":
        return _cmd_init(pairs)
    if domain == "permission" and verb == "request":
        return _cmd_permission_request(pairs)
    if domain == "permission" and verb == "decide":
        return _cmd_permission_decide(pairs)
    if domain == "team" and verb == "event":
        return _cmd_team_event(pairs)
    print(f"unknown command: {domain} {verb}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
