"""Wave 2a renderer conformance (I5): the TS Surface client and the Python
client must parse the SAME fixture corpus to identical semantics. This test
runs the Python side; Vitest runs the TS side on the same files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_os_contracts import SurfaceTurnResponse

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "macos"
    / "renderer"
    / "tests"
    / "fixtures"
    / "surface_contract"
)


def test_python_client_accepts_shared_valid_turn_fixture() -> None:
    payload = json.loads(
        (FIXTURES / "turn_response_valid.json").read_text(encoding="utf-8")
    )
    turn = SurfaceTurnResponse.model_validate(payload)
    assert turn.text == "completed reply"
    assert turn.stop_reason == "completed"
    assert turn.snapshot.status.value == "ACTIVE"
    assert turn.snapshot.event_sequence == 1


def test_python_client_rejects_shared_protocol_mismatch_fixture() -> None:
    payload = json.loads(
        (FIXTURES / "turn_response_protocol_mismatch.json").read_text(
            encoding="utf-8"
        )
    )
    with pytest.raises(Exception):
        SurfaceTurnResponse.model_validate(payload)


def test_python_client_parses_shared_sse_fixture() -> None:
    from apps.cli.surface_client import SurfaceClient

    body = (FIXTURES / "sse_events.txt").read_text(encoding="utf-8")
    batch = SurfaceClient._decode_sse(None, "task:1", 2, body.encode("utf-8"))
    assert batch.task_id == "task:1"
    assert batch.after_sequence == 2
    assert batch.next_sequence == 3
    assert len(batch.events) == 1
    assert batch.events[0].sequence == 3
    assert batch.events[0].event_type.value == "SESSION_MESSAGE_RECORDED"
