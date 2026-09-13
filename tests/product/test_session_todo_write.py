"""GC-SESSION-TODO-WRITE red tests (test-first, CTO gate conditions C1/C2).

These tests are written BEFORE the implementation. Every test here must fail
(red) against the pre-implementation tree, and the constant-return bypass
test must demonstrably fail when the executor is swapped for a stub that
ignores its input (C2: 先红留证).

Design under test (CP-AB-SESSION-TODO-WRITE-2026-09-11):
- `session.todo_write` — tier 1 session-scratchpad capability, full-replace
  semantics, no filesystem/process/network effects, no new event types.
- Durable truth = the existing ACTION_PROPOSED/ACTION_RECEIPT chain; the
  current todo list is the normalized arguments of the latest SUCCEEDED
  invocation.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from agent_os_contracts import PermissionMode

from agent_os_core.agent_loop import CHAT_CAPABILITY_IDS, CHAT_GRANT_MAX_RISK_TIERS
from agent_os_core.capability import CapabilityDenied
from agent_os_core.permission_gate import (
    ACTION_RISK_TIERS,
    PermissionGateOutcome,
    evaluate_permission_gate,
)
from agent_os_core import provider as provider_module
from domain_packs.developer_agent import DeveloperWorkspaceAdapter

TODO_CAPABILITY = "session.todo_write"
ALL_MODES: tuple[PermissionMode, ...] = ("ASK", "ACCEPT_READ_ONLY", "ACCEPT_IN_WORKSPACE")


def _todos(*items: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"id": i, "content": c, "status": s} for i, c, s in items]


def _dispatch(
    adapter: DeveloperWorkspaceAdapter, args: dict[str, object], key: str
) -> dict[str, Any]:
    return cast("dict[str, Any]", adapter._dispatch(TODO_CAPABILITY, args, key))


# --- C1: tier consistency locked across all registration surfaces ---------


def test_tier1_consistency_across_gate_chat_grant_provider_adapter(tmp_path) -> None:
    assert ACTION_RISK_TIERS[TODO_CAPABILITY] == 1
    assert TODO_CAPABILITY in CHAT_CAPABILITY_IDS
    assert CHAT_GRANT_MAX_RISK_TIERS[TODO_CAPABILITY] == 1
    schema = provider_module._WORKSPACE_TOOL_PARAMETERS[TODO_CAPABILITY]
    assert schema["type"] == "object"
    assert "todos" in schema["required"]
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    spec = adapter.specs()[TODO_CAPABILITY]
    assert spec.risk_tier == 1
    assert spec.idempotency_supported is True


# --- A-G2: tier 1 auto-pass in every mode ----------------------------------


@pytest.mark.parametrize("mode", ALL_MODES)
def test_todo_write_auto_pass_in_every_mode(mode: PermissionMode) -> None:
    decision = evaluate_permission_gate(
        capability_id=TODO_CAPABILITY, mode=mode, mode_event_id=None
    )
    assert decision.outcome is PermissionGateOutcome.TIER_DEFAULT_AUTO_PASS
    assert decision.risk_tier == 1


# --- Regression: the new session.* namespace stays fail-closed -------------


@pytest.mark.parametrize("mode", ALL_MODES)
def test_unregistered_session_capability_fail_closed(mode: PermissionMode) -> None:
    decision = evaluate_permission_gate(
        capability_id="session.delete", mode=mode, mode_event_id=None
    )
    assert decision.outcome is PermissionGateOutcome.DENY_OUT_OF_ALLOWLIST


# --- Executor semantics (full-replace, validation, typed failures) --------


def test_dispatch_normalizes_and_returns_full_list(tmp_path) -> None:
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    todos = _todos(("a", " write tests ", "pending"), ("b", "run them", "done"))
    output = _dispatch(adapter, {"todos": todos}, "key:1")
    assert output["ok"] is True
    assert output["count"] == 2
    assert output["todos"][0]["content"] == "write tests"  # trimmed
    assert output["todos"][1]["status"] == "done"


def test_dispatch_empty_list_is_legal_clear(tmp_path) -> None:
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    output = _dispatch(adapter, {"todos": []}, "key:2")
    assert output == {"ok": True, "todos": [], "count": 0}


@pytest.mark.parametrize(
    "todos",
    (
        [{"content": "x", "status": "pending"}],  # missing id
        [{"id": "a", "content": "x"}],  # missing status
        [{"id": "  ", "content": "x", "status": "pending"}],  # blank id
        [{"id": "a", "content": "   ", "status": "pending"}],  # blank content
        [{"id": "a", "content": "x", "status": "doing"}],  # illegal status
        _todos(("a", "x", "pending"), ("a", "y", "done")),  # duplicate id
        _todos(*[(f"t{i}", f"task {i}", "pending") for i in range(101)]),  # >100
    ),
)
def test_dispatch_invalid_input_typed_deny(tmp_path, todos) -> None:
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    with pytest.raises(CapabilityDenied):
        adapter.preflight(TODO_CAPABILITY, {"todos": todos}, "key:3")


# --- C2: constant-return bypass detection -----------------------------------


def test_bypass_detector_output_must_reflect_input(tmp_path) -> None:
    """An executor swapped for a constant-return stub FAILS this test: two
    different writes must yield two different, input-derived outputs."""
    adapter = DeveloperWorkspaceAdapter(tmp_path)
    first = _dispatch(
        adapter, {"todos": _todos(("a", "alpha", "pending"))}, "key:4"
    )
    second = _dispatch(
        adapter,
        {"todos": _todos(("b", "beta", "in_progress"), ("c", "gamma", "done"))},
        "key:5",
    )
    assert first["todos"] != second["todos"]
    assert second["count"] == 2
    assert [t["id"] for t in second["todos"]] == ["b", "c"]
