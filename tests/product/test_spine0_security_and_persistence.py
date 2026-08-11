from __future__ import annotations

import json
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


def test_sqlite_idempotency_survives_reopen(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    first = SQLiteTaskEventStore(path)
    assert first.put_idempotency("scope", "key", {"value": "one"}, NOW.isoformat())
    first.close()
    second = SQLiteTaskEventStore(path)
    assert second.get_idempotency("scope", "key") == {"value": "one"}
    assert not second.put_idempotency("scope", "key", {"value": "two"}, NOW.isoformat())


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

    with pytest.raises(RuntimeError, match="simulated crash before outcome seal"):
        first_sandbox.invoke(action, permit, correction)

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
