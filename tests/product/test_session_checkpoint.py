"""Append-only session checkpoints and forward replay recovery (P0).

The evidence spine is append-only: a real "rewind" (deleting history) is
forbidden. So the checkpoint form here is forward:

* a checkpoint is an append-only, operator-named marker that REFERENCES the
  existing stream ``(sequence, turn_id, state_digest)``;
* recovery after a crash re-projects the stream FORWARD from that sequence in a
  brand-new process on the same database - no history is deleted or rewritten.

These tests pin: a checkpoint can be written, a turn continues across it, and a
fresh process reconstructs the same state by replaying forward from it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceClientRef,
    SurfaceCorrectionCommand,
    SurfaceSessionStatus,
)
from agent_os_core import DeferredApprovalGateway, DeterministicProvider
from apps.api_server.app import AgentOSApplication


def _app(root: Path, scripted: tuple = ()) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3", workspace=root
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _client_ref() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


def _checkpoint_command(app: AgentOSApplication, session_id: str, label: str):
    return SurfaceCorrectionCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client_ref(),
        session_id=session_id,
        reason=label,
        expected_event_sequence=app.surface_current_sequence(
            app.surface_task_for_session(session_id)
        ),
        idempotency_key=f"idem:checkpoint:{label}",
        requested_at=datetime.now(timezone.utc),
    )


def test_checkpoint_is_written_and_a_turn_continues_across_it(tmp_path: Path) -> None:
    app = _app(
        tmp_path,
        scripted=(
            ("first reply", ()),
            ("second reply after the checkpoint", ()),
        ),
    )
    session, loop = app.open_chat_session("work", DeferredApprovalGateway())
    loop.run_turn(session, "first request")

    # Mark a checkpoint after the first turn.
    app.surface_write_checkpoint(_checkpoint_command(app, session.session_id, "after-first"))

    checkpoints = app.surface_list_checkpoints(session.session_id)
    assert len(checkpoints) == 1
    assert checkpoints[0]["label"] == "after-first"
    assert isinstance(checkpoints[0]["sequence"], int)

    # The session stays usable after the checkpoint: a second turn runs.
    loop.run_turn(session, "second request")
    assert app.surface.get_session(session.session_id).status is SurfaceSessionStatus.ACTIVE


def test_crash_then_forward_replay_reconstructs_session_state(tmp_path: Path) -> None:
    db = tmp_path / "agent-os.sqlite3"
    writer = _app(
        tmp_path,
        scripted=(
            ("first reply", ()),
            ("second reply after crash point", ()),
        ),
    )
    session, loop = writer.open_chat_session("work", DeferredApprovalGateway())
    loop.run_turn(session, "first request")

    # Mark a checkpoint at the end of the first turn.
    writer.surface_write_checkpoint(
        _checkpoint_command(writer, session.session_id, "crash-point")
    )
    cp = writer.surface_list_checkpoints(session.session_id)[0]
    checkpoint_sequence = cp["sequence"]

    # The process "crashes": a brand-new process opens the SAME database.
    recovered = AgentOSApplication(database=db, workspace=tmp_path)
    replay = recovered.surface_replay_checkpoint(session.session_id, checkpoint_sequence)

    # The forward replay reconstructed the durable events from the checkpoint.
    assert replay["from_sequence"] == checkpoint_sequence
    assert replay["event_count"] >= 1
    # The checkpoint event itself is in the forward projection.
    assert replay["last_event_type"] == "SESSION_CHECKPOINT_RECORDED"
    # No history was deleted: the pre-checkpoint events are still readable.
    total_events = len(recovered.store.read(session.task_id))
    assert total_events >= checkpoint_sequence
