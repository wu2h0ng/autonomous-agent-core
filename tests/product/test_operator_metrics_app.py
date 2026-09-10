"""App-layer operator metrics emission tests (HCW-METRICS-0).

Emission lives in AgentOSApplication so CLI, Web and desktop surfaces share one
instrumentation point. These tests fail if a surface bypasses the shared layer
or if the event log silently stops being written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api_server.app import AgentOSApplication
from agent_os_core.operator_metrics import verify_operator_event_log


def _events(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _make_app(tmp_path: Path, name: str = "app.sqlite3") -> AgentOSApplication:
    return AgentOSApplication(database=tmp_path / name, workspace=tmp_path)


def test_create_task_emits_prompt_sent(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    statement = "修复 README 里的失效链接"
    task = app.create_task(
        {
            "goal_id": "goal:test",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": "2026-09-10T00:00:00+00:00",
            "statement": statement,
        }
    )
    events = _events(tmp_path / "app.sqlite3.operator-events.jsonl")
    assert [e["type"] for e in events] == ["prompt_sent"]
    assert events[0]["task_id"] == task.task_id
    assert events[0]["chars"] == len(statement)
    assert verify_operator_event_log(tmp_path / "app.sqlite3.operator-events.jsonl")


def test_failed_correction_emits_nothing(tmp_path: Path) -> None:
    """correct_task on a DRAFT task raises before any state change; the operator
    log must not record phantom corrections for rejected commands."""
    app = _make_app(tmp_path, "correct.sqlite3")
    task = app.create_task(
        {
            "goal_id": "goal:test",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": "2026-09-10T00:00:00+00:00",
            "statement": "s",
        }
    )
    with pytest.raises(ValueError, match="active committed run"):
        app.correct_task(task.task_id, "方向不对，重来")
    events = _events(tmp_path / "correct.sqlite3.operator-events.jsonl")
    assert [e["type"] for e in events] == ["prompt_sent"]


def test_memory_database_disables_operator_log(tmp_path: Path) -> None:
    app = AgentOSApplication(database=":memory:", workspace=tmp_path)
    assert app.operator_log is None
    app.create_task(
        {
            "goal_id": "goal:test",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": "2026-09-10T00:00:00+00:00",
            "statement": "s",
        }
    )
    assert not list(tmp_path.glob("*.operator-events.jsonl"))
