from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    CapabilityGrant,
    CapabilityGrantStatus,
    CorrectionEpochVector,
    PrincipalIdentity,
    PrincipalRole,
    ResourceBudget,
)
from agent_os_core import (
    CapabilityDenied,
    CapabilityEffectUnknown,
    ConcurrentWriteError,
    CorrectionAuthority,
    PolicyInput,
    PolicyKernel,
    SQLiteTaskEventStore,
    WorkspaceSandbox,
)


NOW = datetime.now(timezone.utc)


def _workspace_action(
    correction: CorrectionAuthority,
    *,
    capability_id: str,
    arguments: dict[str, object],
    idempotency_key: str,
) -> tuple[ActionContract, ActionPermit]:
    now = datetime.now(timezone.utc)
    action = ActionContract(
        action_id=f"action:{idempotency_key}",
        task_id="task:receipt-replay",
        run_id="run:receipt-replay",
        node_id=f"node:{idempotency_key}",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id=capability_id,
        capability_version="1",
        arguments_json=json.dumps(arguments),
        risk_tier=3 if capability_id == "workspace.shell" else 2,
        idempotency_key=idempotency_key,
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=30,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=correction.snapshot(
            "task:receipt-replay",
            "run:receipt-replay",
            capability_id,
        ),
        expected_outcome_id="expected:receipt-replay",
        candidate_envelope_id="envelope:receipt-replay",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id=f"permit:{idempotency_key}",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id=f"decision:{idempotency_key}",
        grant_id=f"grant:{idempotency_key}",
        correction_epochs=action.observed_correction_epochs,
        lease_fence=0,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return action, permit


class _CountingSandbox(WorkspaceSandbox):
    def __init__(
        self,
        root: Path,
        *,
        idempotency_store: object,
        shell_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(
            root,
            idempotency_store=idempotency_store,
            shell_allowlist=shell_allowlist,
        )
        self.dispatch_count = 0

    def _dispatch(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        self.dispatch_count += 1
        return super()._dispatch(capability_id, args, action_key)


class _CrashBeforeOutcomeStore:
    def __init__(self, delegate: SQLiteTaskEventStore) -> None:
        self.delegate = delegate
        self.crashed = False

    def get_idempotency(self, scope: str, key: str) -> dict[str, Any] | None:
        return self.delegate.get_idempotency(scope, key)

    def put_idempotency(
        self,
        scope: str,
        key: str,
        response: dict[str, Any],
        created_at: str,
    ) -> bool:
        if scope == "capability-outcome.v1" and not self.crashed:
            self.crashed = True
            raise RuntimeError("simulated crash before outcome seal")
        return self.delegate.put_idempotency(scope, key, response, created_at)


class _EffectThenRaiseSandbox(_CountingSandbox):
    def _dispatch(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        self.dispatch_count += 1
        (self.root / "effect.txt").write_text("applied\n", encoding="utf-8")
        raise RuntimeError("connector lost after effect")


class _NonCanonicalOutputSandbox(_CountingSandbox):
    def _dispatch(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        self.dispatch_count += 1
        (self.root / "effect.txt").write_text("applied\n", encoding="utf-8")
        return {"non_json": object()}


class _BlockingSandbox(_CountingSandbox):
    def __init__(
        self,
        root: Path,
        *,
        idempotency_store: object,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        super().__init__(root, idempotency_store=idempotency_store)
        self.entered = entered
        self.release = release

    def _dispatch(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        self.dispatch_count += 1
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("test did not release blocked dispatch")
        return WorkspaceSandbox._dispatch(self, capability_id, args, action_key)


def test_sqlite_idempotency_survives_reopen(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    first = SQLiteTaskEventStore(path)
    assert first.put_idempotency("scope", "key", {"value": "one"}, NOW.isoformat())
    first.close()
    second = SQLiteTaskEventStore(path)
    assert second.get_idempotency("scope", "key") == {"value": "one"}
    assert not second.put_idempotency("scope", "key", {"value": "two"}, NOW.isoformat())


def test_active_execution_lease_owner_blocks_takeover(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    first = SQLiteTaskEventStore(database)
    second = SQLiteTaskEventStore(database)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    assert first.acquire_lease_if_idempotency_absent(
        "run:approval",
        "runtime:first",
        expires_at,
        "capability-reservation.v1",
        "approval-action",
    ) == 1

    with pytest.raises(ConcurrentWriteError, match="leased|owner|progress"):
        second.acquire_lease_if_idempotency_absent(
            "run:approval",
            "runtime:second",
            expires_at,
            "capability-reservation.v1",
            "approval-action",
        )


def test_stale_execution_lease_fence_cannot_insert_reservation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    first = SQLiteTaskEventStore(database)
    second = SQLiteTaskEventStore(database)
    first_expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    first_fence = first.acquire_lease_if_idempotency_absent(
        "run:approval",
        "runtime:first",
        first_expiry,
        "capability-reservation.v1",
        "approval-action",
    )
    assert first.release_lease("run:approval", "runtime:first")
    second_expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    assert second.acquire_lease_if_idempotency_absent(
        "run:approval",
        "runtime:second",
        second_expiry,
        "capability-reservation.v1",
        "approval-action",
    ) == first_fence + 1

    with pytest.raises(ConcurrentWriteError, match="stale|lease|owner"):
        first.put_idempotency_guarded_by_lease(
            "run:approval",
            "runtime:first",
            first_fence,
            first_expiry,
            "capability-reservation.v1",
            "approval-action",
            {"state": "RESERVED"},
            NOW.isoformat(),
        )
    assert first.get_idempotency(
        "capability-reservation.v1", "approval-action"
    ) is None


def test_existing_reservation_permanently_blocks_execution_takeover(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    first = SQLiteTaskEventStore(database)
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    fence = first.acquire_lease_if_idempotency_absent(
        "run:approval",
        "runtime:first",
        expires_at,
        "capability-reservation.v1",
        "approval-action",
    )
    assert first.put_idempotency_guarded_by_lease(
        "run:approval",
        "runtime:first",
        fence,
        expires_at,
        "capability-reservation.v1",
        "approval-action",
        {"state": "RESERVED"},
        NOW.isoformat(),
    )
    first.close()
    restarted = SQLiteTaskEventStore(database)

    with pytest.raises(ConcurrentWriteError, match="reservation|dispatch|review"):
        restarted.acquire_lease_if_idempotency_absent(
            "run:approval",
            "runtime:restarted",
            expires_at,
            "capability-reservation.v1",
            "approval-action",
        )


def test_expired_execution_lease_allows_takeover_only_before_reservation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    first = SQLiteTaskEventStore(database)
    second = SQLiteTaskEventStore(database)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    first_fence = first.acquire_lease_if_idempotency_absent(
        "run:approval",
        "runtime:expired-owner",
        expired,
        "capability-reservation.v1",
        "expired-owner-action",
    )
    assert first_fence == 1

    second_fence = second.acquire_lease_if_idempotency_absent(
        "run:approval",
        "runtime:restarted",
        (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "capability-reservation.v1",
        "expired-owner-action",
    )
    assert second_fence == first_fence + 1

    with pytest.raises(ConcurrentWriteError, match="stale|lease|owner"):
        first.put_idempotency_guarded_by_lease(
            "run:approval",
            "runtime:expired-owner",
            first_fence,
            expired,
            "capability-reservation.v1",
            "expired-owner-action",
            {"state": "RESERVED"},
            NOW.isoformat(),
        )
    assert first.get_idempotency(
        "capability-reservation.v1", "expired-owner-action"
    ) is None


def test_guarded_reservation_codec_binds_exact_execution_lease(
    tmp_path: Path,
) -> None:
    store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
    correction = CorrectionAuthority(store)
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.read",
        arguments={"path": "fixture.txt"},
        idempotency_key="lease-bound-reservation",
    )
    (tmp_path / "fixture.txt").write_text("bound\n", encoding="utf-8")
    sandbox = _CountingSandbox(tmp_path, idempotency_store=store)
    lease = sandbox.acquire_execution_lease(action, "runtime:owner")
    guarded_permit = permit.model_copy(update={"lease_fence": lease.fence})

    result = sandbox.invoke(
        action,
        guarded_permit,
        correction,
        execution_lease=lease,
    )

    reservation = store.get_idempotency(
        "capability-reservation.v1",
        action.idempotency_key,
    )
    assert reservation is not None
    assert reservation["execution_lease"] == lease.payload()
    assert result.permit.lease_fence == lease.fence
    assert sandbox.dispatch_count == 1


def test_known_capability_outcome_replays_original_receipt_and_output_without_dispatch(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    first_store = SQLiteTaskEventStore(database)
    first_correction = CorrectionAuthority(first_store)
    action, permit = _workspace_action(
        first_correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key="receipt-replay-edit",
    )
    first_sandbox = _CountingSandbox(
        tmp_path,
        idempotency_store=first_store,
    )
    first = first_sandbox.invoke(action, permit, first_correction)
    assert first_sandbox.dispatch_count == 1
    first_store.close()

    restarted_store = SQLiteTaskEventStore(database)
    restarted_correction = CorrectionAuthority(restarted_store)
    restarted_sandbox = _CountingSandbox(
        tmp_path,
        idempotency_store=restarted_store,
    )
    replay = restarted_sandbox.invoke(action, permit, restarted_correction)

    assert replay == first
    assert replay.receipt.receipt_id == first.receipt.receipt_id
    assert replay.output == first.output
    assert restarted_sandbox.dispatch_count == 0
    assert target.read_text(encoding="utf-8") == "after\n"


def test_sealed_historical_replay_does_not_depend_on_mutable_workspace_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    store = SQLiteTaskEventStore(database)
    correction = CorrectionAuthority(store)
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key="immutable-history-edit",
    )
    first_sandbox = _CountingSandbox(tmp_path, idempotency_store=store)
    first = first_sandbox.invoke(action, permit, correction)
    target.write_text("later external state\n", encoding="utf-8")

    replay_sandbox = _CountingSandbox(tmp_path, idempotency_store=store)
    replay = replay_sandbox.invoke(action, permit, correction)

    assert replay == first
    assert replay_sandbox.dispatch_count == 0
    assert target.read_text(encoding="utf-8") == "later external state\n"


@pytest.mark.parametrize(
    "sandbox_type",
    (_EffectThenRaiseSandbox, _NonCanonicalOutputSandbox),
)
def test_post_dispatch_uncertainty_never_seals_a_failed_outcome(
    tmp_path: Path,
    sandbox_type: type[_CountingSandbox],
) -> None:
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
    correction = CorrectionAuthority(store)
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key=f"unknown-{sandbox_type.__name__}",
    )
    sandbox = sandbox_type(tmp_path, idempotency_store=store)

    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW") as caught:
        sandbox.invoke(action, permit, correction)

    assert caught.value.__class__.__name__ == "CapabilityEffectUnknown"
    assert sandbox.dispatch_count == 1
    assert (tmp_path / "effect.txt").read_text(encoding="utf-8") == "applied\n"
    assert store.get_idempotency(
        "capability-reservation.v1", action.idempotency_key
    ) is not None
    assert store.get_idempotency(
        "capability-outcome.v1", action.idempotency_key
    ) is None

    restarted = _CountingSandbox(tmp_path, idempotency_store=store)
    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW") as replay:
        restarted.invoke(action, permit, correction)
    assert replay.value.__class__.__name__ == "CapabilityEffectUnknown"
    assert restarted.dispatch_count == 0


def test_two_sqlite_connections_allow_only_one_reserved_dispatch(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    first_store = SQLiteTaskEventStore(database)
    second_store = SQLiteTaskEventStore(database)
    first_correction = CorrectionAuthority(first_store)
    second_correction = CorrectionAuthority(second_store)
    action, permit = _workspace_action(
        first_correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key="two-connection-reservation",
    )
    entered = threading.Event()
    release = threading.Event()
    first = _BlockingSandbox(
        tmp_path,
        idempotency_store=first_store,
        entered=entered,
        release=release,
    )
    second = _CountingSandbox(tmp_path, idempotency_store=second_store)
    first_results: list[object] = []
    first_errors: list[BaseException] = []

    def invoke_first() -> None:
        try:
            first_results.append(first.invoke(action, permit, first_correction))
        except BaseException as exc:  # pragma: no cover - asserted below
            first_errors.append(exc)

    thread = threading.Thread(target=invoke_first)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW"):
        second.invoke(action, permit, second_correction)
    assert second.dispatch_count == 0
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert first_errors == []
    assert len(first_results) == 1
    replay = second.invoke(action, permit, second_correction)
    assert replay == first_results[0]
    assert first.dispatch_count == 1
    assert second.dispatch_count == 0
    assert target.read_text(encoding="utf-8") == "after\n"


@pytest.mark.parametrize("tamper_kind", ("digest", "binding"))
def test_capability_outcome_tamper_fails_closed_without_dispatch(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    database = tmp_path / "state.sqlite3"
    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    store = SQLiteTaskEventStore(database)
    correction = CorrectionAuthority(store)
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key=f"tamper-{tamper_kind}",
    )
    _CountingSandbox(tmp_path, idempotency_store=store).invoke(
        action, permit, correction
    )
    stored = store.get_idempotency("capability-outcome.v1", action.idempotency_key)
    assert stored is not None
    if tamper_kind == "digest":
        stored["output"] = {"tampered": True}
    else:
        stored["action_id"] = "action:forged"
        without_digest = {
            key: value for key, value in stored.items() if key != "record_digest"
        }
        stored["record_digest"] = hashlib.sha256(
            json.dumps(
                without_digest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE idempotency_keys SET response_json = ? WHERE scope = ? AND key = ?",
            (
                json.dumps(stored, sort_keys=True),
                "capability-outcome.v1",
                action.idempotency_key,
            ),
        )
        connection.commit()

    replay = _CountingSandbox(tmp_path, idempotency_store=store)
    with pytest.raises(CapabilityDenied, match="capability|outcome|digest") as caught:
        replay.invoke(action, permit, correction)
    assert caught.value.__class__.__name__ == "CapabilityEffectUnknown"
    assert replay.dispatch_count == 0


def test_shell_dispatch_window_becomes_unknown_and_never_resends(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    script = tmp_path / "bump.py"
    script.write_text(
        "from pathlib import Path\n"
        "path = Path('counter.txt')\n"
        "value = int(path.read_text()) if path.exists() else 0\n"
        "path.write_text(str(value + 1))\n",
        encoding="utf-8",
    )
    store = SQLiteTaskEventStore(database)
    correction = CorrectionAuthority(store)
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.shell",
        arguments={"command": "python3 bump.py"},
        idempotency_key="unknown-shell",
    )
    crashing_store = _CrashBeforeOutcomeStore(store)
    first_sandbox = _CountingSandbox(
        tmp_path,
        idempotency_store=crashing_store,
        shell_allowlist=("python3 bump.py",),
    )

    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW") as caught:
        first_sandbox.invoke(action, permit, correction)
    assert caught.value.__class__.__name__ == "CapabilityEffectUnknown"

    assert first_sandbox.dispatch_count == 1
    assert (tmp_path / "counter.txt").read_text(encoding="utf-8") == "1"
    store.close()

    restarted_store = SQLiteTaskEventStore(database)
    restarted_correction = CorrectionAuthority(restarted_store)
    restarted_sandbox = _CountingSandbox(
        tmp_path,
        idempotency_store=restarted_store,
        shell_allowlist=("python3 bump.py",),
    )
    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW"):
        restarted_sandbox.invoke(action, permit, restarted_correction)

    assert restarted_sandbox.dispatch_count == 0
    assert (tmp_path / "counter.txt").read_text(encoding="utf-8") == "1"


def test_capability_dispatch_requires_a_durable_reservation_store(
    tmp_path: Path,
) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    correction = CorrectionAuthority()
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key="missing-durable-store",
    )

    with pytest.raises(CapabilityDenied, match="durable idempotency store"):
        WorkspaceSandbox(tmp_path).invoke(action, permit, correction)

    assert target.read_text(encoding="utf-8") == "before\n"


def test_workspace_denies_path_escape_and_unallowlisted_command(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)
    with pytest.raises(PermissionError):
        sandbox._safe_path("../outside")
    with pytest.raises(PermissionError):
        sandbox._dispatch("workspace.run_tests", {"command": "sh -c id"}, "key")


def test_workspace_compensation_removes_a_new_file(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)
    sandbox._dispatch(
        "workspace.apply_patch", {"path": "new.txt", "content": "created"}, "action:new"
    )
    assert (tmp_path / "new.txt").exists()
    sandbox.compensate("action:new", "new.txt")
    assert not (tmp_path / "new.txt").exists()


def test_correction_epoch_blocks_a_previously_observed_action() -> None:
    correction = CorrectionAuthority()
    initial = correction.snapshot("task-1", "run-1", "workspace.read")
    correction.correct("task", "task-1", "principal pause")
    assert correction.snapshot("task-1", "run-1", "workspace.read") != initial
    assert correction.halted("task-1", "run-1", "workspace.read")


def test_correction_epoch_survives_authority_restart(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    store = SQLiteTaskEventStore(path)
    first = CorrectionAuthority(store)
    first.correct("task", "task-1", "stop")
    second = CorrectionAuthority(SQLiteTaskEventStore(path))
    assert second.halted("task-1", "run-1", "workspace.read")
    assert second.snapshot("task-1", "run-1", "workspace.read").task_epoch == 1


def test_correction_after_permit_blocks_actual_dispatch(tmp_path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)
    correction = CorrectionAuthority()
    now = NOW
    epochs = correction.snapshot("task-1", "run-1", "workspace.read")
    action = ActionContract(
        action_id="action:race",
        task_id="task-1",
        run_id="run-1",
        node_id="read",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.read",
        capability_version="1",
        arguments_json='{"path":"fixture.txt"}',
        risk_tier=0,
        idempotency_key="race-key",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=epochs,
        expected_outcome_id="expected-1",
        candidate_envelope_id="envelope-1",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id="permit:race",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:race",
        grant_id="grant:race",
        correction_epochs=epochs,
        lease_fence=0,
        issued_at=now,
        expires_at=now + timedelta(minutes=1),
    )
    correction.correct("task", "task-1", "operator pause")
    with pytest.raises(CapabilityDenied, match="halted"):
        sandbox.invoke(action, permit, correction)


def test_reentrant_correction_at_dispatch_linearizes_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
    correction = CorrectionAuthority(store)
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key="reentrant-correction",
    )
    sandbox = WorkspaceSandbox(tmp_path, idempotency_store=store)
    original_dispatch = sandbox._dispatch

    def correct_then_dispatch(
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        correction.correct(
            "task",
            action.task_id,
            "operator correction at dispatch entry",
        )
        return original_dispatch(capability_id, args, action_key)

    monkeypatch.setattr(sandbox, "_dispatch", correct_then_dispatch)

    with pytest.raises(CapabilityEffectUnknown, match="UNKNOWN_REQUIRES_REVIEW"):
        sandbox.invoke(action, permit, correction)

    assert target.read_text(encoding="utf-8") == "before\n"
    assert correction.halted(action.task_id, action.run_id, action.capability_id)
    assert (
        correction.snapshot(action.task_id, action.run_id, action.capability_id)
        .task_epoch
        == 1
    )
    with pytest.raises(CapabilityEffectUnknown, match="UNKNOWN_REQUIRES_REVIEW"):
        sandbox.replay(action)


def test_cross_thread_correction_linearizes_after_inflight_dispatch(
    tmp_path: Path,
) -> None:
    store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
    correction = CorrectionAuthority(store)
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    action, permit = _workspace_action(
        correction,
        capability_id="workspace.edit",
        arguments={
            "path": "fixture.txt",
            "old_string": "before\n",
            "new_string": "after\n",
        },
        idempotency_key="cross-thread-correction",
    )
    dispatch_entered = threading.Event()
    release_dispatch = threading.Event()
    sandbox = _BlockingSandbox(
        tmp_path,
        idempotency_store=store,
        entered=dispatch_entered,
        release=release_dispatch,
    )
    invoke_results: list[object] = []
    invoke_errors: list[BaseException] = []
    correction_started = threading.Event()
    correction_done = threading.Event()
    correction_errors: list[BaseException] = []

    def invoke() -> None:
        try:
            invoke_results.append(sandbox.invoke(action, permit, correction))
        except BaseException as exc:  # pragma: no cover - asserted below
            invoke_errors.append(exc)

    def correct() -> None:
        correction_started.set()
        try:
            correction.correct(
                "task",
                action.task_id,
                "operator correction racing active dispatch",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            correction_errors.append(exc)
        finally:
            correction_done.set()

    dispatcher = threading.Thread(target=invoke)
    dispatcher.start()
    assert dispatch_entered.wait(timeout=5)
    corrector = threading.Thread(target=correct)
    corrector.start()
    assert correction_started.wait(timeout=5)
    try:
        assert not correction_done.wait(timeout=0.2)
        assert target.read_text(encoding="utf-8") == "before\n"
    finally:
        release_dispatch.set()
        dispatcher.join(timeout=5)
        corrector.join(timeout=5)

    assert not dispatcher.is_alive()
    assert not corrector.is_alive()
    assert invoke_errors == []
    assert correction_errors == []
    assert len(invoke_results) == 1
    assert target.read_text(encoding="utf-8") == "after\n"
    assert correction_done.is_set()
    assert correction.halted(action.task_id, action.run_id, action.capability_id)


def test_policy_denies_budget_and_scope_mismatch() -> None:
    correction = CorrectionAuthority()
    policy = PolicyKernel(correction)
    principal = PrincipalIdentity(
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )
    from agent_os_contracts import CapabilitySpec, SideEffectGuarantee

    capability = CapabilitySpec(
        capability_id="workspace.read",
        version="1",
        display_name="read",
        input_contract="json",
        output_contract="json",
        side_effect_guarantee=SideEffectGuarantee.READ_ONLY,
        idempotency_supported=True,
        credential_class="none",
        data_boundary="workspace",
        risk_tier=1,
        timeout_seconds=30,
        cancellation_supported=True,
        compensation_supported=False,
        audit_policy="all",
        created_by="system",
        created_at=NOW,
    )
    grant = CapabilityGrant(
        grant_id="grant-1",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.read",
        capability_version="1",
        max_risk_tier=1,
        budget_limit=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=0,
        ),
        status=CapabilityGrantStatus.ACTIVE,
        granted_by="system",
        granted_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    action = ActionContract(
        action_id="action-1",
        task_id="task-1",
        run_id="run-1",
        node_id="read",
        principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="workspace.read",
        capability_version="1",
        arguments_json="{}",
        risk_tier=1,
        idempotency_key="key",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=2,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected-1",
        candidate_envelope_id="envelope-1",
        created_at=NOW,
    )
    decision = policy.decide(
        action,
        PolicyInput(principal=principal, grant=grant, capability=capability, now=NOW),
    )
    assert decision.verdict.value == "DENY"
    assert "BUDGET_EXCEEDED" in decision.reason_codes
