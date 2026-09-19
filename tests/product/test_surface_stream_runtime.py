"""E1 begin-turn runtime tests (M2, test-first).

Frozen source: GC §E1 turn-start protocol — begin-turn is the only turn_id
source; invalid stream fails typed STREAM_GONE with the provider never started;
one in-flight turn per session (second begin fails typed TURN_IN_PROGRESS);
idempotency binds the canonical command digest (same digest replays without
provider re-invocation, different digest fails typed IDEMPOTENCY_CONFLICT with
no re-bind).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

import pytest
from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    PrincipalIdentity,
    PrincipalRole,
    SurfaceBeginTurnCommand,
    SurfaceBeginTurnResponse,
    SurfaceClientRef,
    SurfaceSessionSnapshot,
    SurfaceSessionStatus,
    SurfaceStreamBinding,
)

from agent_os_core import (
    STALL_THRESHOLD_DEFAULT_SECONDS,
    SessionStreamRegistry,
    SurfaceApplicationPort,
    SurfaceIdempotencyConflict,
    SurfaceRuntime,
    SurfaceStreamGone,
    SurfaceTurnInProgress,
)


def _principal() -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=datetime.now(timezone.utc),
    )


def _client() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="tui-1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:local",
    )


class FakeStreamApplication:
    """Minimal SurfaceApplicationPort recording begin-turn side effects."""

    def __init__(self) -> None:
        self.principal = _principal()
        self.task_id = "task-1"
        self.begin_turn_calls: list[SurfaceBeginTurnCommand] = []
        self.uncommitted_turns: set[str] = set()
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._turn_counter = 0

    # --- surface runtime port ---

    def surface_task_for_session(self, session_id: str) -> str:
        return self.task_id

    def surface_current_sequence(self, task_id: str) -> int:
        return 0

    def surface_session_snapshot(self, session_id: str) -> SurfaceSessionSnapshot:
        return SurfaceSessionSnapshot(
            protocol_version=SURFACE_PROTOCOL_VERSION,
            session={
                "session_id": session_id,
                "task_id": self.task_id,
                "run_id": "run-1",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
            },  # type: ignore[arg-type]
            envelope_id="env-1",
            expected_outcome_id="out-1",
            status=SurfaceSessionStatus.ACTIVE,
            event_sequence=0,
            message_count=0,
            updated_at=datetime.now(timezone.utc),
        )

    def surface_idempotency_record(self, scope: str, key: str) -> dict[str, Any] | None:
        return self._idempotency.get(f"{scope}:{key}")

    def surface_store_idempotency(
        self, scope: str, key: str, record: dict[str, Any]
    ) -> bool:
        self._idempotency[f"{scope}:{key}"] = record
        return True

    # --- E1 extension port ---

    def surface_has_uncommitted_turn(self, session_id: str) -> bool:
        return session_id in self.uncommitted_turns

    def surface_open_turn_id(self, session_id: str) -> str | None:
        if session_id not in self.uncommitted_turns:
            return None
        return f"turn-uncommitted-{session_id}"

    def surface_begin_turn(
        self, command: SurfaceBeginTurnCommand
    ) -> SurfaceBeginTurnResponse:
        """Durable turn-start record + asynchronous execution trigger."""
        self.begin_turn_calls.append(command)
        self._turn_counter += 1
        self.uncommitted_turns.add(command.session_id)
        return SurfaceBeginTurnResponse(
            turn_id=f"turn-{self._turn_counter}-{uuid4().hex[:8]}",
            stream_id=command.stream.stream_id,
        )


def _begin_turn(
    stream: SurfaceStreamBinding, *, key: str = "key-1", text: str = "edit the file"
) -> SurfaceBeginTurnCommand:
    return SurfaceBeginTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=_client(),
        session_id="sess-1",
        text=text,
        stream=stream,
        expected_event_sequence=0,
        idempotency_key=key,
        requested_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def rig() -> tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]:
    app = FakeStreamApplication()
    registry = SessionStreamRegistry(runtime_boot_id="boot-1")
    # The fake implements the subset the begin-turn path consumes; cast to
    # the port so the runtime sees its declared composition-root authority.
    runtime = SurfaceRuntime(
        cast(SurfaceApplicationPort, app), stream_registry=registry
    )
    return app, registry, runtime


class TestStreamSubscriptionFirst:
    def test_begin_turn_with_unknown_stream_fails_stream_gone(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, _, runtime = rig
        command = _begin_turn(
            SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id="never-subscribed")
        )
        with pytest.raises(SurfaceStreamGone):
            runtime.begin_turn(command)
        assert app.begin_turn_calls == []

    def test_begin_turn_with_stale_generation_fails_stream_gone(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, registry, runtime = rig
        stream_id = registry.subscribe("sess-1")
        command = _begin_turn(
            SurfaceStreamBinding(runtime_boot_id="boot-0", stream_id=stream_id)
        )
        with pytest.raises(SurfaceStreamGone):
            runtime.begin_turn(command)
        assert app.begin_turn_calls == []

    def test_begin_turn_with_live_stream_records_turn_start(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, registry, runtime = rig
        stream_id = registry.subscribe("sess-1")
        response = runtime.begin_turn(
            _begin_turn(
                SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id=stream_id)
            )
        )
        assert len(app.begin_turn_calls) == 1
        assert response.turn_id
        assert response.stream_id == stream_id


class TestInFlightTurn:
    def test_second_begin_turn_fails_turn_in_progress(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, registry, runtime = rig
        stream_id = registry.subscribe("sess-1")
        binding = SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id=stream_id)
        runtime.begin_turn(_begin_turn(binding, key="key-1"))
        with pytest.raises(SurfaceTurnInProgress):
            runtime.begin_turn(_begin_turn(binding, key="key-2"))
        assert len(app.begin_turn_calls) == 1

    def test_begin_turn_after_commit_succeeds(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, registry, runtime = rig
        stream_id = registry.subscribe("sess-1")
        binding = SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id=stream_id)
        runtime.begin_turn(_begin_turn(binding, key="key-1"))
        app.uncommitted_turns.discard("sess-1")
        second = runtime.begin_turn(_begin_turn(binding, key="key-2"))
        assert len(app.begin_turn_calls) == 2
        assert second.turn_id


class TestIdempotency:
    def test_same_key_same_digest_replays_without_reinvocation(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, registry, runtime = rig
        stream_id = registry.subscribe("sess-1")
        binding = SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id=stream_id)
        at = datetime.now(timezone.utc)
        first = runtime.begin_turn(
            _begin_turn(binding, key="key-1").model_copy(update={"requested_at": at})
        )
        replay = runtime.begin_turn(
            _begin_turn(binding, key="key-1").model_copy(update={"requested_at": at})
        )
        assert replay == first
        assert len(app.begin_turn_calls) == 1

    def test_same_key_different_digest_fails_idempotency_conflict(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, registry, runtime = rig
        stream_id = registry.subscribe("sess-1")
        binding = SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id=stream_id)
        runtime.begin_turn(_begin_turn(binding, key="key-1", text="edit the file"))
        with pytest.raises(SurfaceIdempotencyConflict):
            runtime.begin_turn(_begin_turn(binding, key="key-1", text="different text"))
        assert len(app.begin_turn_calls) == 1

    def test_conflict_replay_does_not_rebind_stream(
        self, rig: tuple[FakeStreamApplication, SessionStreamRegistry, SurfaceRuntime]
    ) -> None:
        app, registry, runtime = rig
        stream_id = registry.subscribe("sess-1")
        binding = SurfaceStreamBinding(runtime_boot_id="boot-1", stream_id=stream_id)
        runtime.begin_turn(_begin_turn(binding, key="key-1", text="edit the file"))
        with pytest.raises(SurfaceIdempotencyConflict):
            runtime.begin_turn(_begin_turn(binding, key="key-1", text="different text"))
        bound_turns = registry.turns_bound("sess-1", stream_id)
        assert len(bound_turns) == 1


class TestStallThreshold:
    def test_default_stall_threshold_is_30_seconds(self) -> None:
        assert STALL_THRESHOLD_DEFAULT_SECONDS == 30.0

    def test_threshold_is_a_named_finite_positive_constant(self) -> None:
        assert isinstance(STALL_THRESHOLD_DEFAULT_SECONDS, float)
        assert STALL_THRESHOLD_DEFAULT_SECONDS > 0
