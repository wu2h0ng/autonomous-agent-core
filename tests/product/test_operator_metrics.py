"""Operator-side HCW metrics event log tests (HCW-METRICS-0 Goal Card).

The log is the Agent OS-side instrumentation surface: append-only JSONL with a
sha256 hash chain, consumed by the external deterministic aggregator
(tools/hcw/aggregate.py). These tests fail if the schema drifts from the Goal
Card contract or if tamper evidence breaks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_os_core.operator_metrics import (
    OPERATOR_EVENT_TYPES,
    OperatorEventLog,
    verify_operator_event_log,
)


def _read_lines(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_append_writes_goal_card_schema_with_hash_chain(tmp_path: Path) -> None:
    log_path = tmp_path / "operator-events.jsonl"
    log = OperatorEventLog(log_path)
    log.append("prompt_sent", task_id="t1", chars=42)
    log.append("approval_action", task_id="t1", verdict="approve", n=7)

    events = _read_lines(log_path)
    assert len(events) == 2
    for ev in events:
        assert ev["v"] == 1
        assert ev["type"] in OPERATOR_EVENT_TYPES
        assert "T" in ev["ts"]  # ISO-8601
        assert ev["prev_hash"]
        assert ev["hash"]
    assert events[1]["prev_hash"] == events[0]["hash"]
    assert events[0]["task_id"] == "t1"
    assert events[0]["chars"] == 42
    assert events[1]["verdict"] == "approve"


def test_verify_detects_tampering(tmp_path: Path) -> None:
    log_path = tmp_path / "operator-events.jsonl"
    log = OperatorEventLog(log_path)
    log.append("prompt_sent", task_id="t1", chars=10)
    log.append("intervention", task_id="t1")
    assert verify_operator_event_log(log_path) is True

    events = _read_lines(log_path)
    events[0]["chars"] = 9999  # tamper
    log_path.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n",
        encoding="utf-8",
    )
    assert verify_operator_event_log(log_path) is False


def test_append_reopens_existing_log_and_continues_chain(tmp_path: Path) -> None:
    log_path = tmp_path / "operator-events.jsonl"
    OperatorEventLog(log_path).append("prompt_sent", task_id="t1", chars=1)
    OperatorEventLog(log_path).append("correction", task_id="t1", chars=2)
    events = _read_lines(log_path)
    assert events[1]["prev_hash"] == events[0]["hash"]
    assert verify_operator_event_log(log_path) is True


def test_append_rejects_unknown_event_type(tmp_path: Path) -> None:
    log = OperatorEventLog(tmp_path / "operator-events.jsonl")
    with pytest.raises(ValueError):
        log.append("model_reasoning")  # not an operator event


def test_timestamps_are_monotonic(tmp_path: Path) -> None:
    log_path = tmp_path / "operator-events.jsonl"
    log = OperatorEventLog(log_path)
    for _ in range(3):
        log.append("prompt_sent", task_id="t1", chars=1)
    stamps = [ev["ts"] for ev in _read_lines(log_path)]
    assert stamps == sorted(stamps)
