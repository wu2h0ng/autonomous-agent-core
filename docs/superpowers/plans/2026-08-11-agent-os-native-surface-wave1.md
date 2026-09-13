# Agent OS Native Surface Wave 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one supervised local Agent Core Runtime that owns durable chat/session truth and can be used interchangeably by the terminal and a future macOS Surface protocol client.

**Architecture:** Extend the existing Task event stream with typed session/transcript events, then make `AgentLoop` restartable and approval-continuable from those events. Place a concurrency-safe `SurfaceRuntime` application service over that state, expose it through authenticated versioned HTTP plus resumable SSE cursors, and migrate terminal chat to a loopback `SurfaceClient` instead of constructing a second `AgentOSApplication`.

**Tech Stack:** Python 3.11, Pydantic v2 contracts, SQLite/WAL, stdlib `ThreadingHTTPServer`, stdlib `urllib`, SSE, pytest 9, Ruff, Pyright.

## Global Constraints

- Implement in a new isolated worktree created from reconciled exact head `7bfb1753`; suggested branch `codex/native-surface-wave1-20260811`.
- Preserve the current pure-Python product dependency boundary; Wave 1 adds no Tauri, React, Google, Chrome, PostgreSQL, cloud-sync, or Worker code.
- Wave 1 supports exactly one configured workspace per Runtime daemon. Multi-workspace Runtime hosting belongs to Wave 2.
- `AgentOSApplication`, not the CLI, HTTP handler, or renderer client, remains the composition root for Task, provider, policy, capability, evidence, and correction behavior.
- The CLI must never open the daemon-owned SQLite database directly.
- Provider keys remain environment-resolved by the daemon and never appear in the runtime descriptor, protocol payloads, SQLite, logs, or tests.
- Every state-changing protocol request requires protocol version, authenticated local bearer token, `SurfaceClientRef`, and idempotency key. Commands against existing state also require the exact expected event sequence; opening a new session has no prior Task sequence.
- Local authentication protects every `/v1/*` route when the server runs in daemon mode; direct test/development composition may explicitly omit the token.
- A provider/tool timeout or process interruption must never synthesize success or silently resend an unresolved external effect.
- A pending approval is durable. A restart must recover the exact action digest and either continue with a matching decision or remain fail-closed.
- Wave 1 event delivery uses resumable SSE with `Last-Event-ID` and bounded long-poll. The envelope is transport-neutral so Wave 2 may add WebSocket delivery without changing event meaning.
- Tests must be written first and observed failing for the expected missing behavior before implementation.
- No push, merge, release, signing, notarization, live-provider request, or current-state completion claim is authorized by this plan.

## File Structure

### New files

- `packages/contracts/src/agent_os_contracts/surface.py` — closed Surface protocol contracts and protocol version.
- `packages/os_core/src/agent_os_core/session_projection.py` — strict projection of durable session state and transcript from Task events.
- `packages/os_core/src/agent_os_core/surface_runtime.py` — per-session locking, idempotent commands, restartable turns, approval continuation, and protocol projections.
- `apps/api_server/surface_routes.py` — authenticated Surface HTTP/SSE route parsing and response mapping kept out of the existing large handler.
- `apps/cli/surface_client.py` — stdlib loopback client for versioned commands, queries, and SSE cursor reads.
- `apps/runtime_daemon/__init__.py` — daemon package marker.
- `apps/runtime_daemon/descriptor.py` — private runtime descriptor creation, validation, and stale-process checks.
- `apps/runtime_daemon/__main__.py` — foreground server and signal-safe lifecycle.
- `tests/product/test_surface_contracts.py` — closed-schema and digest/version contract tests.
- `tests/product/test_session_projection.py` — transcript/session rehydration and corruption tests.
- `tests/product/test_surface_runtime.py` — durable turn, restart, concurrency, approval, correction, and idempotency tests.
- `tests/product/test_surface_api.py` — authenticated HTTP and resumable SSE protocol tests.
- `tests/product/test_surface_client.py` — loopback client parsing, protocol, and typed-error tests.
- `tests/product/test_runtime_daemon.py` — descriptor permissions, lifecycle, stale descriptor, and secret-exclusion tests.
- `tests/product/test_surface_wave1_e2e.py` — CLI/HTTP/daemon restart continuity and governed coding loop.

### Modified files

- `packages/contracts/src/agent_os_contracts/runtime.py` — add session lifecycle event types.
- `packages/contracts/src/agent_os_contracts/__init__.py` — export Surface contracts.
- `packages/os_core/src/agent_os_core/task_aggregate.py` — explicitly accept non-aggregate-mutating session events.
- `packages/os_core/src/agent_os_core/task_service.py` — typed session-event writers.
- `packages/os_core/src/agent_os_core/agent_loop.py` — durable message sink, restored history, and deferred-approval continuation.
- `packages/os_core/src/agent_os_core/__init__.py` — export session projection and Surface Runtime.
- `apps/api_server/app.py` — compose and expose one `SurfaceRuntime` over the existing application.
- `apps/api_server/server.py` — delegate Surface routes and enforce daemon-mode local authentication.
- `apps/api_server/__main__.py` — accept optional runtime token and descriptor-friendly bound port.
- `apps/cli/__main__.py` — use `SurfaceClient` for daemon and chat/session commands.
- `pyproject.toml` — register `agent-os` and `agent-os-runtime` console scripts.
- `docs/CURRENT_STATE.yaml` — record only exact tested/reviewed Wave 1 state and explicit exclusions after implementation verification.

---

### Task 1: Freeze the Surface protocol contracts

**Files:**
- Create: `packages/contracts/src/agent_os_contracts/surface.py`
- Modify: `packages/contracts/src/agent_os_contracts/runtime.py:50-86`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Test: `tests/product/test_surface_contracts.py`

**Interfaces:**
- Consumes: `ContractModel`, `NonEmptyStr`, `UtcDateTime`, `SessionRef`, `ProviderMessage`, `TaskEvent`, `ApprovalDisposition`.
- Produces: `SURFACE_PROTOCOL_VERSION`, `SurfaceClientRef`, `SurfaceSessionStatus`, `SurfaceOpenSessionCommand`, `SurfaceTurnCommand`, `SurfaceApprovalCommand`, `SurfaceCorrectionCommand`, `PendingSurfaceApproval`, `SurfaceSessionSnapshot`, `SurfaceTurnResponse`, `SurfaceEventBatch`.

- [ ] **Step 1: Write the closed-schema contract tests**

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceClientRef,
    SurfaceTurnCommand,
)


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def client() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:cli:1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:mac:1",
    )


def test_surface_turn_requires_version_sequence_and_idempotency() -> None:
    command = SurfaceTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client(),
        session_id="session:1",
        text="inspect the failing test",
        expected_event_sequence=12,
        idempotency_key="idem:turn:1",
        requested_at=NOW,
    )
    assert command.expected_event_sequence == 12
    with pytest.raises(ValidationError):
        SurfaceTurnCommand.model_validate(
            command.model_dump() | {"protocol_version": "2.0"}
        )


def test_surface_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SurfaceClientRef.model_validate(client().model_dump() | {"admin": True})
```

- [ ] **Step 2: Run the contract test and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_surface_contracts.py -q`

Expected: collection fails because `agent_os_contracts.surface` exports do not exist.

- [ ] **Step 3: Implement the exact contract family**

```python
SURFACE_PROTOCOL_VERSION = "1.0"


class SurfaceClientRef(ContractModel):
    client_id: NonEmptyStr
    client_type: Literal["DESKTOP", "CLI", "TEST"]
    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    device_id: NonEmptyStr


class SurfaceSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    CORRECTION_HALTED = "CORRECTION_HALTED"
    CLOSED = "CLOSED"


class SurfaceTurnCommand(ContractModel):
    protocol_version: Literal["1.0"]
    client: SurfaceClientRef
    session_id: NonEmptyStr
    text: NonEmptyStr
    expected_event_sequence: int = Field(ge=0)
    idempotency_key: NonEmptyStr
    requested_at: UtcDateTime
```

Implement the other protocol contracts with these exact fields:

- `SurfaceOpenSessionCommand`: `protocol_version`, `client`, `statement`, `idempotency_key`, `requested_at`.
- `SurfaceApprovalCommand`: `protocol_version`, `client`, `session_id`, `action_digest`, `disposition` restricted to `APPROVE|REJECT`, `reason`, `expected_event_sequence`, `idempotency_key`, `requested_at`.
- `SurfaceCorrectionCommand`: `protocol_version`, `client`, `session_id`, `reason`, `expected_event_sequence`, `idempotency_key`, `requested_at`.
- `PendingSurfaceApproval`: `action_digest`, `capability_id`, `proposal_id`, `preview`, `requested_at`.
- `SurfaceSessionSnapshot`: `protocol_version`, `session`, `envelope_id`, `expected_outcome_id`, `status`, `event_sequence`, `message_count`, `pending_approval`, `updated_at`.
- `SurfaceTurnResponse`: `protocol_version`, `snapshot`, nullable `turn_id`, `text`, `steps`, `stop_reason`, `total_tokens`.
- `SurfaceEventBatch`: `protocol_version`, `task_id`, `after_sequence`, `next_sequence`, and `events: tuple[TaskEvent, ...]`.

Validate that every event in `SurfaceEventBatch` belongs to the task and has a strictly increasing sequence above `after_sequence`.

Add `SESSION_OPENED`, `SESSION_MESSAGE_RECORDED`, `SESSION_APPROVAL_PENDING`, `SESSION_APPROVAL_RESOLVED`, and `SESSION_CLOSED` to `TaskEventType`. Export every public type through `agent_os_contracts.__init__`.

- [ ] **Step 4: Run the contract tests and adjacent schema tests**

Run: `uv run --extra product-test pytest tests/product/test_surface_contracts.py tests/product/test_task_service.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add packages/contracts/src/agent_os_contracts/surface.py packages/contracts/src/agent_os_contracts/runtime.py packages/contracts/src/agent_os_contracts/__init__.py tests/product/test_surface_contracts.py
git commit -m "feat(surface): define local protocol contracts"
```

---

### Task 2: Persist and strictly project session transcripts

**Files:**
- Create: `packages/os_core/src/agent_os_core/session_projection.py`
- Modify: `packages/os_core/src/agent_os_core/task_service.py:320-430`
- Modify: `packages/os_core/src/agent_os_core/task_aggregate.py:430-445`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_session_projection.py`

**Interfaces:**
- Consumes: `TaskEventStore.read(task_id)`, `SessionRef`, `ProviderMessage`, and the four session event types.
- Produces: `ProjectedSession`; `SessionProjectionError`; `SessionProjector.project(task_id: str, session_id: str) -> ProjectedSession`; and the typed writers `TaskService.open_session`, `TaskService.record_session_message`, `TaskService.close_session` shown below.

- [ ] **Step 1: Write projection tests for restart and corruption**

```python
def test_projector_restores_exact_ordered_transcript(tmp_path: Path) -> None:
    store, tasks, task, run, expected = committed_running_task(tmp_path)
    ref = SessionRef(
        session_id="session:durable",
        task_id=task.task_id,
        run_id=run.run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
    )
    tasks.open_session(ref, "envelope:1", expected.expected_outcome_id)
    tasks.record_session_message(
        task.task_id,
        ref.session_id,
        0,
        ProviderMessage(role=ProviderMessageRole.SYSTEM, content="system"),
        turn_id=None,
    )
    tasks.record_session_message(
        task.task_id,
        ref.session_id,
        1,
        ProviderMessage(role=ProviderMessageRole.USER, content="inspect"),
        turn_id="turn:1",
    )

    projected = SessionProjector(store).project(task.task_id, ref.session_id)

    assert projected.ref == ref
    assert [message.content for message in projected.history] == ["system", "inspect"]
    assert projected.next_message_index == 2


def test_projector_rejects_message_index_gap(tmp_path: Path) -> None:
    store = malformed_session_stream(tmp_path, message_indexes=(0, 2))
    with pytest.raises(SessionProjectionError, match="contiguous"):
        SessionProjector(store).project("task:1", "session:1")
```

- [ ] **Step 2: Run the projection tests and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_session_projection.py -q`

Expected: collection fails because the projector and typed writers do not exist.

- [ ] **Step 3: Add typed session writers**

```python
def record_session_message(
    self,
    task_id: str,
    session_id: str,
    message_index: int,
    message: ProviderMessage,
    *,
    turn_id: str | None,
) -> TaskAggregate:
    if message_index < 0:
        raise ValueError("message_index must be non-negative")
    return self._append_event(
        task_id,
        TaskEventType.SESSION_MESSAGE_RECORDED,
        {
            "session_id": session_id,
            "message_index": message_index,
            "message": message.model_dump(mode="json"),
            "turn_id": turn_id,
        },
        correlation_id=session_id,
    )
```

Implement `open_session` and `close_session` as equally narrow typed writers. Validate Task/Run/tenant/workspace binding before append. Update `TaskAggregate` to accept these events only as non-aggregate-mutating provenance; malformed payloads still fail projection.

- [ ] **Step 4: Implement strict projection**

```python
@dataclass(frozen=True)
class ProjectedSession:
    ref: SessionRef
    envelope_id: str
    expected_outcome_id: str
    history: tuple[ProviderMessage, ...]
    next_message_index: int
    opened_sequence: int
    last_sequence: int
    closed: bool
    pending_approval: PendingSurfaceApproval | None


class SessionProjector:
    def __init__(self, event_store: TaskEventStore) -> None:
        self._event_store = event_store

    def project(self, task_id: str, session_id: str) -> ProjectedSession:
        events = self._event_store.read(task_id)
        session_events = tuple(
            event for event in events
            if event.decoded_payload().get("session_id") == session_id
        )
        if not session_events:
            raise SessionProjectionError("session not found")
        return _strict_project(session_events)
```

`_strict_project` must reject duplicate open, scope mismatch, non-contiguous indexes, invalid message/tool bindings, more than one unresolved pending approval, message records after close, and a pending action digest that does not match its persisted action.

- [ ] **Step 5: Run projection, event-store, and aggregate tests**

Run: `uv run --extra product-test pytest tests/product/test_session_projection.py tests/product/test_task_service.py tests/product/test_task_aggregate.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add packages/os_core/src/agent_os_core/session_projection.py packages/os_core/src/agent_os_core/task_service.py packages/os_core/src/agent_os_core/task_aggregate.py packages/os_core/src/agent_os_core/__init__.py tests/product/test_session_projection.py
git commit -m "feat(surface): persist session transcripts"
```

---

### Task 3: Make AgentLoop history durable and restartable

**Files:**
- Modify: `packages/os_core/src/agent_os_core/agent_loop.py:163-260`
- Modify: `apps/api_server/app.py:1285-1418`
- Test: `tests/product/test_surface_runtime.py`
- Test: `tests/product/test_terminal_chat_loop.py`

**Interfaces:**
- Consumes: `ProjectedSession.history`, `TaskService.record_session_message`.
- Produces: the `AgentLoop` constructor parameters `initial_history` and `message_sink`; `AgentLoop.resume_turn(session: ChatSession, turn_id: TurnId) -> TurnResult`; and `AgentOSApplication.restore_chat_session(session_id: str, gateway: ConfirmationGateway) -> tuple[ChatSession, AgentLoop]`.

- [ ] **Step 1: Write a restart test with a deterministic provider**

```python
def test_restart_reuses_durable_history_without_replaying_first_turn(tmp_path: Path) -> None:
    app1 = chat_app(tmp_path, scripted=(("first", ()),))
    session, loop = app1.open_chat_session("durable", AutoApproveGateway())
    assert loop.run_turn(session, "first request").text == "first"
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("second", ()),))
    restored, restored_loop = app2.restore_chat_session(
        session.session_id, AutoApproveGateway()
    )
    result = restored_loop.run_turn(restored, "second request")

    assert result.text == "second"
    request_messages = app2.provider.requests[0].messages
    assert [message.content for message in request_messages if message.content] == [
        AgentLoopConfig().system_prompt,
        "first request",
        "first",
        "second request",
    ]
```

- [ ] **Step 2: Run the restart test and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_surface_runtime.py::test_restart_reuses_durable_history_without_replaying_first_turn -q`

Expected: fails because `restore_chat_session` and durable initial history do not exist.

- [ ] **Step 3: Refactor all history appends through one durable method**

```python
def _append_message(
    self,
    session: ChatSession,
    message: ProviderMessage,
    *,
    turn_id: str | None,
) -> None:
    index = len(self._history)
    self._message_sink(session, index, message, turn_id)
    self._history.append(message)
```

Add constructor parameters:

```python
initial_history: tuple[ProviderMessage, ...] | None = None
message_sink: Callable[[ChatSession, int, ProviderMessage, str | None], None]
```

Validate that restored history begins with exactly one SYSTEM message whose content equals the frozen loop config system prompt. Replace every direct `_history.append` in `run_turn`, `_drive`, and recovery completion paths with `_append_message`. Persist before mutating memory so a process crash never exposes a message that lacks durable truth.

- [ ] **Step 4: Add application restoration**

`restore_chat_session` locates the Task by scanning durable `SESSION_OPENED` records, projects the exact session, validates that the current configuration snapshot and provider profile still bind the Run, and constructs `AgentLoop` with projected history and the same chat-scoped grants. It must reject a closed, corrupt, scope-mismatched, or terminal-Run session.

- [ ] **Step 5: Run restart and existing terminal suites**

Run: `uv run --extra product-test pytest tests/product/test_surface_runtime.py tests/product/test_terminal_chat_loop.py -q`

Expected: all selected tests pass; existing terminal behavior remains unchanged.

- [ ] **Step 6: Commit Task 3**

```bash
git add packages/os_core/src/agent_os_core/agent_loop.py apps/api_server/app.py tests/product/test_surface_runtime.py tests/product/test_terminal_chat_loop.py
git commit -m "feat(surface): restore durable chat sessions"
```

---

### Task 4: Replace blocking approval with a durable continuation

**Files:**
- Modify: `packages/os_core/src/agent_os_core/agent_loop.py`
- Modify: `packages/os_core/src/agent_os_core/session_projection.py`
- Modify: `packages/os_core/src/agent_os_core/task_service.py`
- Modify: `apps/api_server/app.py`
- Test: `tests/product/test_surface_runtime.py`
- Test: `tests/product/test_terminal_chat_loop.py`

**Interfaces:**
- Consumes: persisted assistant tool calls, `ActionContract`, `ApprovalDecision`, pending-approval projection.
- Produces: `DeferredApprovalGateway`; `AgentLoop.resume_pending_approval(session: ChatSession, approval: ApprovalDecision) -> TurnResult`; and `AgentOSApplication.decide_session_approval(session_id: str, action_digest: str, disposition: ApprovalDisposition, reason: str) -> TurnResult`.

- [ ] **Step 1: Write approval restart, mismatch, denial, and C7 tests**

```python
def test_pending_approval_survives_restart_and_executes_once(tmp_path: Path) -> None:
    app1 = chat_app(tmp_path, scripted=edit_then_done())
    session, loop = app1.open_chat_session("edit", DeferredApprovalGateway())
    waiting = loop.run_turn(session, "edit fixture")
    assert waiting.stop_reason == "approval_required"
    pending = app1.session_snapshot(session.session_id).pending_approval
    assert pending is not None
    app1.store.close()

    app2 = chat_app(tmp_path, scripted=(("done", ()),))
    resumed = app2.decide_session_approval(
        session.session_id,
        action_digest=pending.action_digest,
        disposition=ApprovalDisposition.APPROVE,
        reason="reviewed exact diff",
    )

    assert resumed.stop_reason == "completed"
    assert (tmp_path / "fixture.txt").read_text() == "fixed\n"
    assert receipt_count(app2, session.task_id) == 1


def test_stale_approval_digest_does_not_execute(tmp_path: Path) -> None:
    app, session, pending = pending_edit(tmp_path)
    with pytest.raises(InvalidTransitionError, match="digest"):
        app.decide_session_approval(
            session.session_id,
            action_digest="0" * 64,
            disposition=ApprovalDisposition.APPROVE,
            reason="wrong action",
        )
    assert receipt_count(app, session.task_id) == 0
```

Also test rejection appends a TOOL denial reply and allows the provider to replan, process restart before execution, process restart after receipt before provider continuation, and correction between approval and execution.

- [ ] **Step 2: Run the approval tests and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_surface_runtime.py -k 'approval or stale or correction' -q`

Expected: tests fail because deferred approval and continuation do not exist.

- [ ] **Step 3: Introduce the deferred gateway and pending event**

```python
class DeferredApprovalGateway:
    def confirm(self, action: ActionContract, preview: str) -> bool:
        raise ApprovalRequired(action=action, preview=preview)


@dataclass(frozen=True)
class ApprovalRequired(Exception):
    action: ActionContract
    preview: str
```

Catch `ApprovalRequired` only inside `_drive`. Append `SESSION_APPROVAL_PENDING` with session, turn, provider proposal, exact action, preview, action digest, assistant message index, and request time; move the Run to `WAITING_APPROVAL`; return `TurnResult(stop_reason="approval_required")`. Do not append `SESSION_TURN_COMPLETED` until the approval path completes or is explicitly rejected/cancelled.

- [ ] **Step 4: Implement exact continuation**

`resume_pending_approval` must:

1. re-project the pending record and current transcript;
2. verify Task/Run/session/config/provider/action digest and C7 epochs;
3. record the exact `ApprovalDecision` through the existing typed writer;
4. execute the already persisted `ActionContract` without rebuilding it;
5. append exactly one TOOL message bound to the persisted provider tool-call ID;
6. clear the pending state with an append-only resolution event;
7. resume remaining unanswered tool calls and provider steps;
8. use action receipt identity to return the prior result rather than execute again after a crash.

Use the already frozen `SESSION_APPROVAL_RESOLVED` event type for the resolution and add it to projector/aggregate handling.

- [ ] **Step 5: Run approval, restart, governance, and terminal regressions**

Run: `uv run --extra product-test pytest tests/product/test_surface_runtime.py tests/product/test_terminal_chat_loop.py tests/product/test_spine0_security_and_persistence.py tests/product/test_external_security_boundaries.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add packages/contracts/src/agent_os_contracts/runtime.py packages/os_core/src/agent_os_core/agent_loop.py packages/os_core/src/agent_os_core/session_projection.py packages/os_core/src/agent_os_core/task_service.py packages/os_core/src/agent_os_core/task_aggregate.py apps/api_server/app.py tests/product/test_surface_runtime.py tests/product/test_terminal_chat_loop.py
git commit -m "feat(surface): persist approval continuations"
```

---

### Task 5: Add the concurrency-safe SurfaceRuntime application service

**Files:**
- Create: `packages/os_core/src/agent_os_core/surface_runtime.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Modify: `apps/api_server/app.py`
- Test: `tests/product/test_surface_runtime.py`

**Interfaces:**
- Consumes: Surface commands, `AgentOSApplication` session methods, SQLite idempotency store, `SessionProjector`.
- Produces: `SurfaceRuntime.open_session`, `get_session`, `run_turn`, `decide_approval`, `pause`, `resume`, `correct`, `event_batch`.

- [ ] **Step 1: Write ownership, sequence, concurrency, and idempotency tests**

```python
def test_same_idempotency_key_returns_same_turn_response(tmp_path: Path) -> None:
    runtime, command = runtime_with_turn_command(tmp_path)
    first = runtime.run_turn(command)
    second = runtime.run_turn(command)
    assert second == first
    assert provider_request_count(runtime) == 1


def test_stale_expected_sequence_fails_before_provider_call(tmp_path: Path) -> None:
    runtime, command = runtime_with_turn_command(tmp_path)
    runtime.run_turn(command)
    with pytest.raises(SurfaceSequenceConflict):
        runtime.run_turn(command.model_copy(update={"idempotency_key": "idem:new"}))
    assert provider_request_count(runtime) == 1
```

Add tests for mismatched tenant/workspace/principal/device client scopes, concurrent turns on one session, independent turns on two sessions, and idempotency-key reuse with a different canonical command digest.

- [ ] **Step 2: Run the service tests and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_surface_runtime.py -k 'idempotency or sequence or concurrent or scope' -q`

Expected: tests fail because `SurfaceRuntime` does not exist.

- [ ] **Step 3: Implement per-session serialization and command guards**

```python
class SurfaceApplicationPort(Protocol):
    def surface_open_session(self, command: SurfaceOpenSessionCommand) -> SurfaceSessionSnapshot:
        pass

    def surface_run_turn(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse:
        pass

    def surface_decide_approval(self, command: SurfaceApprovalCommand) -> SurfaceTurnResponse:
        pass


class SurfaceRuntime:
    def __init__(self, application: SurfaceApplicationPort) -> None:
        self._application = application
        self._locks: dict[str, RLock] = {}
        self._locks_guard = RLock()

    def _session_lock(self, session_id: str) -> RLock:
        with self._locks_guard:
            return self._locks.setdefault(session_id, RLock())

    def run_turn(self, command: SurfaceTurnCommand) -> SurfaceTurnResponse:
        with self._session_lock(command.session_id):
            return self._idempotent(
                scope=f"surface:turn:{command.session_id}",
                key=command.idempotency_key,
                command=command,
                operation=lambda: self._run_turn_once(command),
            )
```

`_idempotent` stores both canonical command digest and serialized response. Same key plus different digest raises `SurfaceIdempotencyConflict`. `_run_turn_once` verifies protocol, client scope, exact current event sequence, session status, and correction state before provider invocation.

- [ ] **Step 4: Implement projections and control commands**

Return `SurfaceSessionSnapshot` from the projector plus current Task/Run status. `pause`, `resume`, and `correct` call the existing application authority methods and never append replacement Surface-only truth. `event_batch` returns only events after the requested sequence and validates strict task ownership.

- [ ] **Step 5: Run the full Surface Runtime suite**

Run: `uv run --extra product-test pytest tests/product/test_surface_runtime.py -q`

Expected: all Surface Runtime tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add packages/os_core/src/agent_os_core/surface_runtime.py packages/os_core/src/agent_os_core/__init__.py apps/api_server/app.py tests/product/test_surface_runtime.py
git commit -m "feat(surface): add serialized runtime service"
```

---

### Task 6: Expose authenticated HTTP commands and resumable SSE

**Files:**
- Create: `apps/api_server/surface_routes.py`
- Modify: `apps/api_server/server.py:331-967`
- Modify: `apps/api_server/__main__.py`
- Test: `tests/product/test_surface_api.py`

**Interfaces:**
- Consumes: `SurfaceRuntime`, bearer token, protocol header, JSON command contracts.
- Produces: `/v1/surface/sessions`, `/v1/surface/sessions/{id}`, `/turns`, `/approvals`, `/pause`, `/resume`, `/correction`, and `/v1/surface/tasks/{task_id}/events`.

- [ ] **Step 1: Write unauthenticated, protocol, command, and cursor tests**

```python
def test_daemon_mode_rejects_missing_token_before_body_parse(server_url: str) -> None:
    request = urllib.request.Request(
        server_url + "/v1/surface/sessions",
        data=b"not-json",
        method="POST",
        headers={"X-Agent-OS-Protocol": "1.0"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 401


def test_events_resume_after_last_event_id(surface_server) -> None:
    task_id, last_sequence = surface_server.seed_three_events()
    request = surface_server.request(
        f"/v1/surface/tasks/{task_id}/events?wait_ms=0",
        headers={"Last-Event-ID": str(last_sequence - 1)},
    )
    body = surface_server.open(request).read().decode()
    assert f"id: {last_sequence}\n" in body
    assert f"id: {last_sequence - 1}\n" not in body
```

Also test wrong token, wrong protocol, stale sequence `409`, idempotency conflict `409`, validation `422`, correction `403/409`, `wait_ms` bounds `0..25000`, and that daemon-mode auth protects existing `/v1/tasks` mutation routes too.

- [ ] **Step 2: Run API tests and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_surface_api.py -q`

Expected: tests fail because Surface routes and daemon authentication do not exist.

- [ ] **Step 3: Implement route delegation and error mapping**

```python
class SurfaceRoutes:
    def __init__(self, runtime: SurfaceRuntime, bearer_token: str) -> None:
        self._runtime = runtime
        self._bearer_token = bearer_token

    def authenticate(self, authorization: str | None) -> None:
        supplied = "" if authorization is None else authorization.removeprefix("Bearer ")
        if not secrets.compare_digest(supplied, self._bearer_token):
            raise SurfaceAuthenticationError("local runtime authentication failed")
```

Parse closed Pydantic commands before dispatch. Map authentication to `401`, scope to `403`, not found to `404`, stale sequence/idempotency to `409`, validation to `422`, and Runtime/provider unavailability to `503`. Do not return tracebacks, secret-bearing exception values, or Python reprs.

- [ ] **Step 4: Implement bounded resumable SSE**

Honor `Last-Event-ID` before the `after` query parameter; reject disagreement. Poll `SurfaceRuntime.event_batch` until at least one event exists or `wait_ms` expires. Encode each event with its Task sequence as SSE `id`, closed event type as `event`, and canonical JSON as `data`; end with an `event: cursor` record containing `next_sequence`.

- [ ] **Step 5: Run API and existing API regression tests**

Run: `uv run --extra product-test pytest tests/product/test_surface_api.py tests/product/test_api_surface.py tests/product/test_task_configuration_api.py -q`

Expected: all selected tests pass; existing direct server composition remains compatible when no daemon token is supplied.

- [ ] **Step 6: Commit Task 6**

```bash
git add apps/api_server/surface_routes.py apps/api_server/server.py apps/api_server/__main__.py tests/product/test_surface_api.py
git commit -m "feat(surface): expose authenticated local protocol"
```

---

### Task 7: Migrate terminal chat to the shared Runtime client

**Files:**
- Create: `apps/runtime_daemon/__init__.py`
- Create: `apps/runtime_daemon/descriptor.py`
- Create: `apps/cli/surface_client.py`
- Modify: `apps/cli/__main__.py`
- Modify: `pyproject.toml`
- Test: `tests/product/test_surface_client.py`
- Test: `tests/product/test_cli_surface.py`

**Interfaces:**
- Consumes: Surface HTTP/SSE contracts.
- Produces: the closed `RuntimeDescriptor` schema, `SurfaceClient`, `agent-os chat`, `session-show`, `session-pause`, `session-resume`, `session-correct`, and interactive approval continuation.

- [ ] **Step 1: Write client protocol and CLI routing tests**

```python
def test_chat_uses_surface_client_not_application(monkeypatch, capsys) -> None:
    fake = FakeSurfaceClient()
    monkeypatch.setattr(cli, "load_surface_client", lambda args: fake)
    monkeypatch.setattr(
        cli,
        "AgentOSApplication",
        lambda **kwargs: pytest.fail("CLI must not open daemon SQLite"),
    )
    monkeypatch.setattr(sys, "argv", ["agent-os", "chat", "-p", "inspect"])
    cli.main()
    assert fake.calls == [("open", "inspect"), ("turn", "session:1", "inspect")]
    assert "completed" in capsys.readouterr().out


def test_client_rejects_response_protocol_mismatch(fake_http_server) -> None:
    fake_http_server.respond_json(200, {"protocol_version": "2.0"})
    with pytest.raises(SurfaceProtocolMismatch):
        SurfaceClient(fake_http_server.descriptor).get_session("session:1")
```

- [ ] **Step 2: Run client and CLI tests and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_surface_client.py tests/product/test_cli_surface.py -q`

Expected: tests fail because the client and shared-Runtime chat routing do not exist.

- [ ] **Step 3: Freeze the private runtime descriptor schema and implement the stdlib Surface client**

```python
class RuntimeDescriptor(ContractModel):
    protocol_version: Literal["1.0"]
    pid: int = Field(gt=0)
    boot_id: NonEmptyStr
    host: Literal["127.0.0.1"]
    port: int = Field(ge=1, le=65535)
    bearer_token: NonEmptyStr
    database_path: NonEmptyStr
    workspace_path: NonEmptyStr
    created_at: UtcDateTime

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"
```

```python
class SurfaceClient:
    def __init__(self, descriptor: RuntimeDescriptor) -> None:
        self._base_url = descriptor.base_url
        self._token = descriptor.bearer_token

    def _request(self, method: str, path: str, payload: ContractModel | None) -> dict[str, object]:
        data = None if payload is None else canonical_json(payload).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-Agent-OS-Protocol": SURFACE_PROTOCOL_VERSION,
            },
        )
        return self._decode_response(request)
```

Map HTTP errors to closed client exceptions without exposing bearer token or raw request headers. Parse every success through the matching Pydantic response contract.

- [ ] **Step 4: Route interactive terminal behavior through the client**

`agent-os chat -p TEXT` opens a session and submits one turn. Interactive `agent-os chat` accepts `--session SESSION_ID`; without it, it opens a new session. `/status`, `/pause`, `/resume`, `/correct REASON`, and `/exit` call protocol commands. On `WAITING_APPROVAL`, print capability and exact preview, read `y/N`, submit the exact action digest, and display the resumed turn result.

Do not retain `TerminalConfirmationGateway` in the CLI. Approval decisions are durable protocol commands.

- [ ] **Step 5: Run client, CLI, and terminal-loop regressions**

Run: `uv run --extra product-test pytest tests/product/test_surface_client.py tests/product/test_cli_surface.py tests/product/test_terminal_chat_loop.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 7**

```bash
git add apps/runtime_daemon/__init__.py apps/runtime_daemon/descriptor.py apps/cli/surface_client.py apps/cli/__main__.py pyproject.toml tests/product/test_surface_client.py tests/product/test_cli_surface.py
git commit -m "feat(cli): use shared local runtime"
```

---

### Task 8: Add safe daemon lifecycle and private runtime descriptor

**Files:**
- Modify: `apps/runtime_daemon/__init__.py`
- Modify: `apps/runtime_daemon/descriptor.py`
- Create: `apps/runtime_daemon/__main__.py`
- Modify: `apps/api_server/server.py`
- Modify: `pyproject.toml`
- Test: `tests/product/test_runtime_daemon.py`

**Interfaces:**
- Consumes: `AgentOSApplication`, authenticated `serve`, configured database/workspace/provider environment.
- Produces: `RuntimeDescriptor`, `agent-os-runtime serve`, `agent-os daemon-start`, `daemon-status`, `daemon-stop`.

- [ ] **Step 1: Write descriptor and lifecycle tests**

```python
def test_descriptor_is_private_and_contains_no_provider_secret(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    descriptor = RuntimeDescriptor(
        protocol_version="1.0",
        pid=123,
        boot_id="boot:1",
        host="127.0.0.1",
        port=18787,
        bearer_token="local-token",
        database_path=str(tmp_path / "agent-os.sqlite3"),
        workspace_path=str(tmp_path / "workspace"),
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    write_descriptor(path, descriptor)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    serialized = path.read_text()
    assert "OPENAI_API_KEY" not in serialized
    assert "sk-" not in serialized


def test_second_daemon_refuses_live_descriptor(tmp_path: Path) -> None:
    running = start_test_daemon(tmp_path)
    with pytest.raises(RuntimeAlreadyRunning):
        start_runtime(running.config)
```

Also test stale PID/boot identity replacement, symlink descriptor rejection, non-loopback host rejection, SIGTERM cleanup, database/workspace path mismatch, health timeout, and that stop verifies descriptor boot identity before signaling.

- [ ] **Step 2: Run daemon tests and verify RED**

Run: `uv run --extra product-test pytest tests/product/test_runtime_daemon.py -q`

Expected: collection fails because descriptor persistence and daemon lifecycle functions do not exist.

- [ ] **Step 3: Implement atomic private descriptor handling**

```python
def write_descriptor(path: Path, descriptor: RuntimeDescriptor) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise RuntimeDescriptorError("runtime descriptor cannot be a symlink")
    temporary = path.with_name(path.name + f".{descriptor.boot_id}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600)
    try:
        os.write(fd, canonical_json(descriptor).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
```

Use a random 256-bit bearer token and UUID boot identity. The descriptor contains only loopback URL, PID, boot ID, protocol version, token, database path, workspace path, and creation time.

- [ ] **Step 4: Implement foreground daemon and CLI lifecycle commands**

Add `build_server(application, host, port, local_token) -> ThreadingHTTPServer` to `apps/api_server/server.py`; `serve` delegates to it for backward compatibility. Bind `127.0.0.1` on an explicitly configured or kernel-selected port, compose one `AgentOSApplication`, write the descriptor only after the authenticated health route is ready, handle SIGTERM/SIGINT, close SQLite, and remove only a descriptor whose boot ID still matches. `daemon-start` uses `subprocess.Popen` with `start_new_session=True`, waits up to ten seconds for authenticated health, and reports typed startup failure. `daemon-stop` sends SIGTERM only after PID, boot ID, executable, workspace, and database identity checks.

- [ ] **Step 5: Run daemon, server, and CLI tests**

Run: `uv run --extra product-test pytest tests/product/test_runtime_daemon.py tests/product/test_surface_api.py tests/product/test_surface_client.py tests/product/test_cli_surface.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit Task 8**

```bash
git add apps/runtime_daemon apps/api_server/server.py apps/cli/__main__.py pyproject.toml tests/product/test_runtime_daemon.py tests/product/test_surface_api.py tests/product/test_surface_client.py tests/product/test_cli_surface.py
git commit -m "feat(runtime): supervise the local Agent OS daemon"
```

---

### Task 9: Prove the Wave 1 end-to-end loop and finalize exact evidence

**Files:**
- Create: `tests/product/test_surface_wave1_e2e.py`
- Create: `.agent_runs/native-surface-wave1-20260811/verification.md`
- Create: `.agent_runs/native-surface-wave1-20260811/messages.jsonl`
- Modify: `docs/CURRENT_STATE.yaml`

**Interfaces:**
- Consumes: packaged console entry points, Runtime descriptor, authenticated Surface client, deterministic provider, real SQLite, isolated workspace.
- Produces: restart-continuity and governed coding-loop evidence; exact status with claim ceiling.

- [ ] **Step 1: Write the full end-to-end verification test**

```python
def test_cli_and_protocol_client_share_one_restartable_coding_session(tmp_path: Path) -> None:
    workspace = prepare_failing_workspace(tmp_path)
    daemon = start_runtime_process(tmp_path, workspace, provider_script=repair_script())
    client = SurfaceClient(load_descriptor(daemon.descriptor_path))

    opened = client.open_session("repair the failing fixture")
    first = client.run_turn(opened.session.session_id, "inspect and repair")
    assert first.snapshot.status is SurfaceSessionStatus.WAITING_APPROVAL

    stop_runtime_process(daemon)
    daemon = start_runtime_process(tmp_path, workspace, provider_script=finish_script())
    restored = SurfaceClient(load_descriptor(daemon.descriptor_path)).get_session(
        opened.session.session_id
    )
    completed = client_for(daemon).decide_approval(
        restored.session.session_id,
        restored.pending_approval.action_digest,
        ApprovalDisposition.APPROVE,
        "reviewed exact edit",
    )

    assert completed.stop_reason == "completed"
    assert (workspace / "fixture.txt").read_text() == "fixed\n"
    assert exactly_one_effect_receipt(client_for(daemon), opened.task_id)
    assert cli_session_show(daemon, opened.session.session_id)["event_sequence"] == (
        completed.snapshot.event_sequence
    )
```

- [ ] **Step 2: Run the E2E test as an integration gate**

Run: `uv run --extra product-test pytest tests/product/test_surface_wave1_e2e.py -q`

Expected: PASS after Tasks 1-8. If it fails, classify the failure by owning task, add a focused failing regression test to that task's test file, observe the focused RED, implement the minimal correction, then rerun both the focused test and this E2E gate.

- [ ] **Step 3: Verify the final composition and console-script wiring**

Confirm these exact bindings exist and are exercised by the E2E test:

```toml
[project.scripts]
agent-os = "apps.cli.__main__:main"
agent-os-runtime = "apps.runtime_daemon.__main__:main"
```

Confirm `AgentOSApplication.__init__` exposes one `SurfaceRuntime` adapter, `agent-os chat` reads the private descriptor, and `agent-os-runtime` passes the bearer token into daemon-mode `serve`. Do not add Wave 2 features or weaken the E2E assertions.

- [ ] **Step 4: Run focused and full verification**

Run focused:

```bash
uv run --extra product-test pytest \
  tests/product/test_surface_contracts.py \
  tests/product/test_session_projection.py \
  tests/product/test_surface_runtime.py \
  tests/product/test_surface_api.py \
  tests/product/test_surface_client.py \
  tests/product/test_runtime_daemon.py \
  tests/product/test_cli_surface.py \
  tests/product/test_terminal_chat_loop.py \
  tests/product/test_surface_wave1_e2e.py -q
```

Run full Product regression:

```bash
uv run --extra product-test pytest tests/product tests/product_eval -q
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
uv run --extra product-test pyright apps packages/contracts/src packages/os_core/src tests/product
git diff --check
```

Record exact pass/fail counts. Any unrelated baseline failures must be reproduced at the exact Wave 1 base before being classified as pre-existing; do not call the full suite green if it is not green.

- [ ] **Step 5: Write durable verification and current state**

The verification report must contain base SHA, implementation SHA, commands, exact counts, failure classification, daemon restart transcript, no-live-provider boundary, and remaining risks. Append task decisions, blockers, verification, and handoff records to `messages.jsonl` using the project message schema. Update `docs/CURRENT_STATE.yaml` with `IMPLEMENTED`, `TESTED`, `INTEGRATED`, `REVIEWED`, `PUSHED`, `RELEASED`, and `DAILY_USABLE` as separate fields; unset states remain explicitly false or not established.

- [ ] **Step 6: Request independent exact-head review**

Review scope must include contract closure, session corruption, approval restart, duplicate-effect prevention, local authentication, descriptor attacks, CLI database bypass, C7, and claim language. The reviewer does not edit writer files. A repaired SHA requires a fresh independent exact-head verdict.

- [ ] **Step 7: Commit the verified Wave 1 evidence**

```bash
git add tests/product/test_surface_wave1_e2e.py .agent_runs/native-surface-wave1-20260811/verification.md .agent_runs/native-surface-wave1-20260811/messages.jsonl docs/CURRENT_STATE.yaml
git commit -m "test(surface): verify unified local runtime wave 1"
```

Do not push or merge without explicit authorization.

## Plan Self-Review Checklist

- Wave 1 implements only the approved local Runtime, protocol, CLI continuity, durable session, approval, recovery, and local coding loop.
- Every new state-changing interface has a failing test, typed contract, scope check, idempotency rule, failure status, and bypass test.
- Session messages are persisted before entering in-memory history.
- Pending approvals and effects survive restart without rebuilding a different action.
- CLI chat cannot instantiate or write through a second `AgentOSApplication`.
- Daemon-mode HTTP authentication covers legacy `/v1/*` mutations as well as new Surface routes.
- Event cursors are monotonic and resumable; SSE is explicitly a Wave 1 transport, not a semantic fork.
- The plan introduces no desktop shell, Personal Work connector, cloud sync, Worker, enterprise, autonomy, release, or daily-usability claim.
