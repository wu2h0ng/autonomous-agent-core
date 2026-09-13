"""Surface read-only session listing (C2): minimal, bounded, no-leak."""

from __future__ import annotations

from pathlib import Path

from agent_os_core import AutoApproveGateway, DeterministicProvider

from apps.api_server.app import AgentOSApplication

FORBIDDEN = (
    "statement",
    "envelope_id",
    "expected_outcome_id",
    "token",
    "credential",
    "pending_approval",
)


def _app(root: Path) -> AgentOSApplication:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=(("hi", ()),),
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def test_sessions_listing_minimal_bounded_and_no_leak(tmp_path: Path) -> None:
    app = _app(tmp_path)
    first, _ = app.open_chat_session("first session", AutoApproveGateway())
    second, _ = app.open_chat_session("second session", AutoApproveGateway())

    response = app.surface_sessions_listing(10, None)
    ids = [summary.session_id for summary in response.sessions]
    assert set(ids) == {first.session_id, second.session_id}
    assert ids == sorted(ids)  # stable order
    summary = response.sessions[0]
    assert summary.task_id
    assert summary.status.value == "ACTIVE"
    assert summary.permission_mode == "ASK"
    assert summary.message_count >= 0
    assert summary.updated_at is not None

    # no-leak: the serialized payload carries none of the sensitive fields
    dumped = response.model_dump(mode="json")
    text = str(dumped)
    for forbidden in FORBIDDEN:
        assert forbidden not in text, f"leaked field: {forbidden}"


def test_sessions_listing_pagination_cursor(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.open_chat_session("a", AutoApproveGateway())
    app.open_chat_session("b", AutoApproveGateway())
    app.open_chat_session("c", AutoApproveGateway())

    page1 = app.surface_sessions_listing(2, None)
    assert len(page1.sessions) == 2
    assert page1.next_cursor == page1.sessions[-1].session_id

    page2 = app.surface_sessions_listing(2, page1.next_cursor)
    assert len(page2.sessions) == 1
    assert page2.next_cursor is None
    # pages are disjoint and cover all sessions
    seen = {s.session_id for s in page1.sessions} | {s.session_id for s in page2.sessions}
    assert len(seen) == 3
