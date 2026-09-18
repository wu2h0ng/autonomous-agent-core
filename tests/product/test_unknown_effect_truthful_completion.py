"""S2: a dispatched action whose effect is unknown must still conclude honestly.

Audit finding (P0, 2026-09-18): `workspace.read` on a non-UTF-8 file and
`workspace.edit` inside a read-only directory fail AFTER the durable reservation,
so the broker wraps them as `CapabilityEffectUnknown`. The loop then raised the
reason at itself: the model never received a tool result, the durable turn never
completed, the session sat PAUSED and the operator saw only a reason-less stall.

These tests pin the honest close-out:
  * the model gets a tool result naming the reason, the review requirement and
    the fact that nothing was retried;
  * the turn (non-deferred path) durably completes with
    `stop_reason=unknown_requires_review`, so the surface's durable-commit
    watcher resolves instead of stalling;
  * the parked-approval path is UNCHANGED - only a human APPROVE/REJECT owns its
    unanswered tool call, so that turn stays open and the approval stays pending;
  * fail-closed is untouched: one dispatch, no automatic retry, the Run stays
    PAUSED and every automatic resume is refused.

Each assertion is mutation-checked against the previous behaviour (no tool
reply, silent open turn, unredacted host path), which reddens exactly the test
that pins it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agent_os_contracts import (
    ApprovalDisposition,
    ProviderMessageRole,
    ProviderToolProposal,
    RunStatus,
    TaskEventType,
)
from agent_os_core import (
    AutoApproveGateway,
    DeferredApprovalGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SessionProjector,
)

from apps.api_server.app import AgentOSApplication
from apps.cli.turn_commit import await_turn_commit


def _proposal(
    call_id: str, capability_id: str, arguments: dict[str, object]
) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _chat_app(root: Path, scripted: tuple[Any, ...]) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


class _DurableReader:
    """The durable-read surface `await_turn_commit` needs, backed by the real
    application store (get_session + events only - no transient frames)."""

    def __init__(self, app: AgentOSApplication) -> None:
        self._app = app

    def get_session(self, session_id: str) -> Any:
        return self._app.surface_session_snapshot(session_id)

    def events(self, task_id: str, **_kwargs: object) -> Any:
        events = tuple(self._app.store.read(task_id))
        return SimpleNamespace(
            events=events,
            next_sequence=events[-1].sequence if events else 0,
        )


def _tool_messages(projected: Any) -> list[Any]:
    return [
        message
        for message in projected.history
        if message.role is ProviderMessageRole.TOOL
    ]


def _event_count(
    app: AgentOSApplication, task_id: str, event_type: TaskEventType
) -> int:
    return sum(event.event_type is event_type for event in app.store.read(task_id))


def _non_utf8_app(root: Path) -> AgentOSApplication:
    (root / "blob.txt").write_bytes(b"\xff\xfe\x00caf\xe9 binary-ish\n")
    return _chat_app(
        root,
        scripted=(
            ("", (_proposal("call-read", "workspace.read", {"path": "blob.txt"}),)),
            ("must not replan", ()),
        ),
    )


def test_non_utf8_read_concludes_with_a_model_visible_reason(tmp_path: Path) -> None:
    """Real `workspace.read` on a non-UTF-8 file: the decoded failure happens
    after the reservation, and the turn must both tell the model and resolve."""
    app = _non_utf8_app(tmp_path)
    session, loop = app.open_chat_session("non utf8 read", AutoApproveGateway())

    started = time.monotonic()
    result = loop.run_turn(session, "read the file")
    elapsed = time.monotonic() - started

    assert result.stop_reason == "unknown_requires_review"
    assert "UNKNOWN_REQUIRES_REVIEW" in result.text
    assert "POST_DISPATCH_UNCERTAIN" in result.text
    assert "a human must review and reconcile it" in result.text
    assert elapsed < 5.0
    # No replan and no second provider call: the loop stopped on the unknown.
    assert isinstance(app.provider, DeterministicProvider)
    assert len(app.provider.requests) == 1

    projected = SessionProjector(app.store).project(session.task_id, session.session_id)
    tools = _tool_messages(projected)
    assert [message.tool_call_id for message in tools] == ["call-read"]
    payload = json.loads(tools[0].content)
    assert payload["reason_code"] == "POST_DISPATCH_UNCERTAIN"
    assert payload["effect_unknown"] is True
    assert payload["dispatched"] is True
    assert payload["auto_retry"] is False
    assert payload["requires_human_review"] is True
    assert payload["stop_reason"] == "unknown_requires_review"
    assert payload["reservation_id"].startswith("reservation-")
    assert "UnicodeDecodeError" in payload["error"]

    # The durable outcome the surface waits for: the turn committed, so the
    # client's stall watcher resolves instead of timing out.
    assert _event_count(app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED) == 1
    assert projected.resumable_turn_id is None
    commit = await_turn_commit(
        _DurableReader(app),  # type: ignore[arg-type]
        session.session_id,
        stall_threshold_seconds=0.5,
        poll_interval_seconds=0.02,
    )
    assert commit == "COMMITTED"

    # Fail-closed: the Run stays PAUSED and cannot be resumed automatically.
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED
    with pytest.raises(InvalidTransitionError, match="UNKNOWN_REQUIRES_REVIEW"):
        app.resume_task(session.task_id)
    with pytest.raises(InvalidTransitionError):
        loop.run_turn(session, "carry on")


def test_read_only_directory_edit_keeps_the_human_decision_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """The parked-approval path: the effect is unknown after the human approved.

    That turn keeps its pending approval and its unanswered tool call (the
    session projection forbids completing a turn with either), so this test
    pins the UNCHANGED fail-closed shape plus the reason text the operator
    reads. Only the non-deferred path gained a durable completion.
    """
    read_only = tmp_path / "ro"
    read_only.mkdir()
    (read_only / "fixture.txt").write_text("stable\n", encoding="utf-8")
    os.chmod(read_only, 0o555)
    request.addfinalizer(lambda: os.chmod(read_only, 0o755))
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-edit",
                        "workspace.edit",
                        {
                            "path": "ro/fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "fixed\n",
                        },
                    ),
                ),
            ),
            ("must not replan", ()),
        ),
    )
    session, loop = app.open_chat_session("read only dir", DeferredApprovalGateway())
    dispatches = 0
    original_dispatch = app.sandbox._dispatch

    def counting_dispatch(*args: Any, **kwargs: Any) -> dict[str, object]:
        nonlocal dispatches
        dispatches += 1
        return original_dispatch(*args, **kwargs)

    monkeypatch.setattr(app.sandbox, "_dispatch", counting_dispatch)

    first = loop.run_turn(session, "edit the file")
    assert first.stop_reason == "approval_required"
    pending = app.tasks.project_session(
        session.task_id, session.session_id
    ).pending_continuation
    assert pending is not None

    result = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action.action_digest(),
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )
    assert result.stop_reason == "unknown_requires_review"
    assert "POST_DISPATCH_UNCERTAIN" in result.text
    assert "PermissionError" in result.text
    assert "not retried" in result.text
    assert dispatches == 1

    projected = SessionProjector(app.store).project(session.task_id, session.session_id)
    assert projected.pending_continuation == pending
    assert _tool_messages(projected) == []
    assert (
        _event_count(app, session.task_id, TaskEventType.SESSION_APPROVAL_RESOLVED) == 0
    )
    assert _event_count(app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED) == 0
    assert projected.resumable_turn_id == pending.turn_id
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED

    retry = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action.action_digest(),
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )
    assert retry.stop_reason == "unknown_requires_review"
    assert dispatches == 1
    assert isinstance(app.provider, DeterministicProvider)
    assert len(app.provider.requests) == 1
    with pytest.raises(InvalidTransitionError, match="UNKNOWN_REQUIRES_REVIEW"):
        app.resume_task(session.task_id)


def test_unknown_effect_inside_a_resolved_continuation_still_concludes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The continuation cursor path: an approval resolves proposal 1, and the
    proposal that follows it fails after dispatch.

    That reply must advance the durable continuation cursor (not just the
    in-memory history), or the projection and the transcript would disagree.
    """
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-edit",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "fixed\n",
                        },
                    ),
                    _proposal("call-read", "workspace.read", {"path": "fixture.txt"}),
                ),
            ),
            ("must not replan", ()),
        ),
    )
    session, loop = app.open_chat_session("continuation", DeferredApprovalGateway())
    dispatches = 0
    original_dispatch = app.sandbox._dispatch

    def dispatch_read_fails(
        capability_id: str, args: dict[str, object], action_key: str
    ) -> dict[str, object]:
        nonlocal dispatches
        dispatches += 1
        if capability_id == "workspace.read":
            raise RuntimeError("connector disconnected after effect")
        return original_dispatch(capability_id, args, action_key)

    monkeypatch.setattr(app.sandbox, "_dispatch", dispatch_read_fails)

    first = loop.run_turn(session, "edit then read")
    assert first.stop_reason == "approval_required"
    pending = app.tasks.project_session(
        session.task_id, session.session_id
    ).pending_continuation
    assert pending is not None

    result = app.decide_session_approval(
        session.session_id,
        action_digest=pending.action.action_digest(),
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact edit",
    )

    assert result.stop_reason == "unknown_requires_review"
    assert dispatches == 2
    projected = SessionProjector(app.store).project(session.task_id, session.session_id)
    tools = _tool_messages(projected)
    assert [message.tool_call_id for message in tools] == ["call-edit", "call-read"]
    assert json.loads(tools[1].content)["reason_code"] == "POST_DISPATCH_UNCERTAIN"
    assert projected.resolved_continuation is None
    assert projected.pending_continuation is None
    assert _event_count(app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED) == 1
    run = app.tasks.get_task(session.task_id).run
    assert run is not None
    assert run.status is RunStatus.PAUSED
    with pytest.raises(InvalidTransitionError, match="UNKNOWN_REQUIRES_REVIEW"):
        app.resume_task(session.task_id)


def test_unknown_effect_answers_the_remaining_proposals_without_running_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider rejects unanswered tool_calls, so the proposals that will not
    run get their own honest reply - and are never executed."""
    (tmp_path / "one.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / "two.txt").write_text("two\n", encoding="utf-8")
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal("call-1", "workspace.read", {"path": "one.txt"}),
                    _proposal("call-2", "workspace.read", {"path": "two.txt"}),
                ),
            ),
            ("must not replan", ()),
        ),
    )
    session, loop = app.open_chat_session("two proposals", AutoApproveGateway())
    dispatches = 0
    original_dispatch = app.sandbox._dispatch

    def dispatch_disconnects_first(*args: Any, **kwargs: Any) -> dict[str, object]:
        nonlocal dispatches
        dispatches += 1
        if dispatches == 1:
            raise RuntimeError("connector disconnected after effect")
        return original_dispatch(*args, **kwargs)

    monkeypatch.setattr(app.sandbox, "_dispatch", dispatch_disconnects_first)

    result = loop.run_turn(session, "read both")

    assert result.stop_reason == "unknown_requires_review"
    assert dispatches == 1
    projected = SessionProjector(app.store).project(session.task_id, session.session_id)
    tools = _tool_messages(projected)
    assert [message.tool_call_id for message in tools] == ["call-1", "call-2"]
    first_payload = json.loads(tools[0].content)
    second_payload = json.loads(tools[1].content)
    assert first_payload["reason_code"] == "POST_DISPATCH_UNCERTAIN"
    assert second_payload["not_executed"] is True
    assert "not executed" in second_payload["error"]
    assert _event_count(app, session.task_id, TaskEventType.SESSION_TURN_COMPLETED) == 1


def test_model_visible_unknown_detail_carries_no_host_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core loop must not depend on a domain pack to redact.

    `WorkspaceSandbox.execute` redacts the paths of its own `_dispatch` errors,
    but the broker's contract only says "the connector's exception text is copied
    into the model-visible tool result" - so the loop itself has to guarantee
    that no host absolute path reaches the model. The connector here raises an
    unredacted failure, exactly like a connector without that nicety.
    """
    (tmp_path / "fixture.txt").write_text("stable\n", encoding="utf-8")
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-read", "workspace.read", {"path": "fixture.txt"}),)),
            ("must not replan", ()),
        ),
    )
    session, loop = app.open_chat_session("host path", AutoApproveGateway())
    host_path = "/private/var/secret-host-root/ws/ro/.fixture.txt-abc123"

    def execute_permission_denied(_action: Any) -> Any:
        raise PermissionError(13, "Permission denied", host_path)

    monkeypatch.setattr(app.sandbox, "execute", execute_permission_denied)

    result = loop.run_turn(session, "read")

    assert result.stop_reason == "unknown_requires_review"
    assert host_path in result.text  # operator-facing: the exact path is useful
    projected = SessionProjector(app.store).project(session.task_id, session.session_id)
    payload = json.loads(_tool_messages(projected)[0].content)
    assert host_path not in payload["error"]
    assert "/private/var/secret-host-root" not in json.dumps(payload)
    assert "[host-path]/.fixture.txt-abc123" in payload["error"]
