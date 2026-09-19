"""A correction that lands during a provider invocation still ENDS its turn.

Operator path this closes (measured on a real daemon, 2026-09-18): the TUI's
Esc key issues a correction; when it lands while the provider call is in flight
the loop raised `RunExecutionError("chat provider correction epoch changed
during invocation")` out of `run_turn`, so the worker thread died with only
`SESSION_TURN_STARTED` durable. The session then reported

    "a prior turn is still uncommitted for this session"

on every later begin-turn for the rest of its life, and `noem session show`
kept answering `ACTIVE` — an unrecoverable session with a success-looking state.

Fail-closed is unchanged and asserted here: the provider's answer is discarded
(no PROVIDER_RESPONDED, no assistant message) and nothing is dispatched. Only
the turn's terminal record changes: it is completed with the same frozen
stop_reason the pre-invocation halt already used (`correction_halted`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceClientRef,
    SurfaceOpenSessionCommand,
    SurfaceTurnCommand,
    TaskEventType,
)
from agent_os_core import DeterministicProvider

from apps.api_server.app import AgentOSApplication


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="cli-ts:sweep",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:sweep",
    )


class CorrectingProvider(DeterministicProvider):
    """Corrects the task from inside the provider invocation.

    That is exactly the interleaving the guard detects: the correction epoch is
    captured before the call and re-read after it.
    """

    def __init__(self, app: AgentOSApplication) -> None:
        super().__init__(
            scripted=(("reply that must never be recorded", ()),),
            invocation_binding=app.provider.invocation_binding,
        )
        self._app = app
        self.corrected = False

    def complete_streaming(self, request, **kwargs):  # type: ignore[override]
        if not self.corrected:
            self.corrected = True
            task_id = request.task_id
            self._app.correct_task(task_id, "operator interrupt (escape)")
        return super().complete_streaming(request, **kwargs)


def _chat_app(root: Path) -> tuple[AgentOSApplication, CorrectingProvider]:
    """The app's default provider stays in place: its invocation binding is what
    the correcting provider must reuse (a provider without the runtime binding is
    refused before it is ever called)."""

    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root,
    )
    provider = CorrectingProvider(app)
    app.provider = provider
    app.provider_configured = True
    return app, provider


def _open(app: AgentOSApplication):
    return app.surface.open_session(
        SurfaceOpenSessionCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            statement="sweep session",
            idempotency_key="idem:sweep:open",
            requested_at=datetime.now(timezone.utc),
        )
    )


def test_correction_during_provider_invocation_completes_the_turn(tmp_path: Path) -> None:
    app, provider = _chat_app(tmp_path)
    opened = _open(app)

    response = app.surface.run_turn(
        SurfaceTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=opened.session.session_id,
            text="inspect the fixture",
            expected_event_sequence=opened.event_sequence,
            idempotency_key="idem:sweep:turn",
            requested_at=datetime.now(timezone.utc),
        )
    )

    assert response.stop_reason == "correction_halted"
    # The turn is CLOSED durably: the next begin-turn is not refused for an
    # uncommitted turn (measured before the fix: SurfaceTurnInProgress forever).
    assert app.surface_has_uncommitted_turn(opened.session.session_id) is False

    task_id = opened.session.task_id
    events = tuple(app.store.read(task_id))
    starts = [
        event
        for event in events
        if event.event_type is TaskEventType.SESSION_TURN_STARTED
    ]
    completions = [
        event
        for event in events
        if event.event_type is TaskEventType.SESSION_TURN_COMPLETED
    ]
    assert len(starts) == 1
    assert len(completions) == 1
    assert completions[0].decoded_payload()["turn_id"] == starts[0].decoded_payload()[
        "turn_id"
    ]
    assert completions[0].decoded_payload()["stop_reason"] == "correction_halted"

    # Fail-closed: the discarded answer left no provider record and no message.
    assert not [
        event
        for event in events
        if event.event_type is TaskEventType.PROVIDER_RESPONDED
    ]
    assistant_messages = [
        event.decoded_payload()["message"]
        for event in events
        if event.event_type is TaskEventType.SESSION_MESSAGE_RECORDED
        and event.decoded_payload()["message"]["role"] == "ASSISTANT"
    ]
    assert assistant_messages == []


def test_later_begin_turn_is_not_refused_for_an_uncommitted_turn(
    tmp_path: Path,
) -> None:
    """The end-to-end half: after the correction the work surface is not stuck
    at SurfaceTurnInProgress (it is refused for the correction's own seal rule,
    which is a different, attributable refusal)."""

    app, provider = _chat_app(tmp_path)
    opened = _open(app)
    app.surface.run_turn(
        SurfaceTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=opened.session.session_id,
            text="inspect the fixture",
            expected_event_sequence=opened.event_sequence,
            idempotency_key="idem:sweep:turn",
            requested_at=datetime.now(timezone.utc),
        )
    )

    snapshot = app.surface.get_session(opened.session.session_id)
    with pytest.raises(Exception) as caught:
        app.surface.run_turn(
            SurfaceTurnCommand(
                protocol_version=SURFACE_PROTOCOL_VERSION,
                client=_client_ref(),
                session_id=opened.session.session_id,
                text="keep working",
                expected_event_sequence=snapshot.event_sequence,
                idempotency_key="idem:sweep:turn:2",
                requested_at=datetime.now(timezone.utc),
            )
        )
    assert "uncommitted" not in str(caught.value), (
        "the refusal must not be the uncommitted-turn dead end: "
        f"{caught.value}"
    )


def test_correction_control_command_is_unchanged_by_the_turn_ending(
    tmp_path: Path,
) -> None:
    """Record regression: the correction itself still halts the session and the
    control command still reports CORRECTION_HALTED (no weakening)."""

    app, provider = _chat_app(tmp_path)
    opened = _open(app)
    app.surface.run_turn(
        SurfaceTurnCommand(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            client=_client_ref(),
            session_id=opened.session.session_id,
            text="inspect the fixture",
            expected_event_sequence=opened.event_sequence,
            idempotency_key="idem:sweep:turn",
            requested_at=datetime.now(timezone.utc),
        )
    )
    assert provider.corrected is True
    snapshot = app.surface.get_session(opened.session.session_id)
    assert snapshot.status.value == "CORRECTION_HALTED"
