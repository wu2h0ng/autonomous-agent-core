from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    CapabilitySpec,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
    ReceiptStatus,
    ResourceBudget,
)
from agent_os_core import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityEffect,
    CapabilityEffectUnknown,
    CorrectionAuthority,
    ExecutionLease,
    SQLiteTaskEventStore,
)


class SpyCapabilityPort:
    """ADR-0059 connector contract: outcomes/replay/preflight/execute."""

    def __init__(self, tmp_path: Path) -> None:
        self.execute_count = 0
        self.store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
        from agent_os_core._action_outcome import DurableActionOutcomeRepository

        self._outcomes = DurableActionOutcomeRepository(self.store)

    def specs(
        self,
        now: datetime | None = None,
        *,
        include_internal: bool = False,
    ) -> dict[str, CapabilitySpec]:
        from agent_os_contracts import SideEffectGuarantee

        at = now or datetime.now(timezone.utc)
        return {
            "capability:spy": CapabilitySpec(
                capability_id="capability:spy",
                version="1",
                display_name="Spy capability",
                input_contract="json:object:1",
                output_contract="json:object:1",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_IDEMPOTENT,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=False,
                credential_class="none",
                data_boundary="workspace-local",
                risk_tier=0,
                timeout_seconds=120,
                audit_policy="event-and-artifact",
                created_by="system",
                created_at=at,
                collaboration_required=False,
            )
        }

    def outcomes(self):
        return self._outcomes

    def replay(self, action: ActionContract):
        return self._outcomes.replay(action)

    def preflight(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> None:
        return None

    def acquire_execution_lease(
        self,
        action: ActionContract,
        owner: str,
    ) -> ExecutionLease:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        fence = self.store.acquire_lease(action.run_id, owner, expires_at.isoformat())
        return ExecutionLease(
            run_id=action.run_id,
            owner=owner,
            fence=fence,
            expires_at=expires_at,
        )

    def release_execution_lease(self, lease: ExecutionLease) -> bool:
        return self.store.release_lease(lease.run_id, lease.owner)

    def execute(self, action: ActionContract) -> CapabilityEffect:
        self.execute_count += 1
        return CapabilityEffect(
            status=ReceiptStatus.SUCCEEDED,
            output={
                "artifact_ids": ("artifact:" + "a" * 64,),
                "compensation_ref": "detail:spy",
            },
            error_code="error:none",
            detail_ref="detail:spy",
        )


class FailingSpyCapabilityPort(SpyCapabilityPort):
    def execute(self, action: ActionContract) -> CapabilityEffect:
        self.execute_count += 1
        raise CapabilityDenied("spy effect failed after dispatch")


def action_and_permit(
    correction: CorrectionAuthority,
) -> tuple[ActionContract, ActionPermit]:
    now = datetime.now(timezone.utc)
    epochs = correction.snapshot("task:boundary", "run:boundary", "capability:spy")
    action = ActionContract(
        action_id="action:boundary",
        task_id="task:boundary",
        run_id="run:boundary",
        node_id="node:boundary",
        principal_id="principal:boundary",
        tenant_id="tenant:boundary",
        workspace_id="workspace:boundary",
        capability_id="capability:spy",
        capability_version="1",
        arguments_json="{}",
        risk_tier=0,
        idempotency_key="idempotency:boundary",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=epochs,
        expected_outcome_id="expected:boundary",
        candidate_envelope_id="envelope:boundary",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id="permit:boundary",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:boundary",
        grant_id="grant:boundary",
        correction_epochs=epochs,
        lease_fence=1,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return action, permit


def _held_claim(port: SpyCapabilityPort, run_id: str) -> ExecutionLease:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    fence = port.store.acquire_lease(run_id, "test:worker", expiry.isoformat())
    return ExecutionLease(
        run_id=run_id,
        owner="test:worker",
        fence=fence,
        expires_at=expiry,
    )


def test_broker_creates_receipt_after_one_port_execution(tmp_path: Path) -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort(tmp_path)
    action, permit = action_and_permit(correction)

    result = CapabilityBroker(port, correction).invoke(
        action, permit, execution_claim=_held_claim(port, action.run_id)
    )

    assert port.execute_count == 1
    assert result.receipt.action_digest == action.action_digest()
    assert result.receipt.permit_id == permit.permit_id
    assert result.receipt.connector_id == action.capability_id
    assert result.receipt.idempotency_key == action.idempotency_key
    assert result.receipt.status is ReceiptStatus.SUCCEEDED
    assert result.receipt.output_artifact_ids == ("artifact:" + "a" * 64,)
    assert result.receipt.detail_ref == "detail:spy"


def test_broker_marks_post_dispatch_failure_as_unknown_requires_review(
    tmp_path: Path,
) -> None:
    correction = CorrectionAuthority()
    port = FailingSpyCapabilityPort(tmp_path)
    action, permit = action_and_permit(correction)

    with pytest.raises(CapabilityEffectUnknown, match="UNKNOWN_REQUIRES_REVIEW"):
        CapabilityBroker(port, correction).invoke(
            action, permit, execution_claim=_held_claim(port, action.run_id)
        )

    assert port.execute_count == 1


def test_broker_rejects_digest_mismatch_before_port_execution(tmp_path: Path) -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort(tmp_path)
    action, permit = action_and_permit(correction)
    forged = permit.model_copy(update={"action_digest": "0" * 64})

    with pytest.raises(CapabilityDenied, match="digest mismatch"):
        CapabilityBroker(port, correction).invoke(
            action, forged, execution_claim=_held_claim(port, action.run_id)
        )

    assert port.execute_count == 0


def test_broker_rejects_expired_permit_before_port_execution(tmp_path: Path) -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort(tmp_path)
    action, permit = action_and_permit(correction)
    expired = permit.model_copy(
        update={
            "issued_at": permit.issued_at - timedelta(minutes=10),
            "expires_at": permit.issued_at - timedelta(minutes=5),
        }
    )

    with pytest.raises(CapabilityDenied, match="expired"):
        CapabilityBroker(port, correction).invoke(
            action, expired, execution_claim=_held_claim(port, action.run_id)
        )

    assert port.execute_count == 0


def test_broker_rejects_c7_halt_before_port_execution(tmp_path: Path) -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort(tmp_path)
    action, permit = action_and_permit(correction)
    correction.correct("task", action.task_id, "operator halt")

    with pytest.raises(CapabilityDenied, match="halted"):
        CapabilityBroker(port, correction).invoke(
            action, permit, execution_claim=_held_claim(port, action.run_id)
        )

    assert port.execute_count == 0


def test_broker_rejects_stale_epoch_before_port_execution(tmp_path: Path) -> None:
    correction = CorrectionAuthority()
    port = SpyCapabilityPort(tmp_path)
    action, permit = action_and_permit(correction)
    correction.correct("run", action.run_id, "epoch advance")
    correction.resume("run", action.run_id)

    with pytest.raises(CapabilityDenied, match="stale correction epoch"):
        CapabilityBroker(port, correction).invoke(
            action, permit, execution_claim=_held_claim(port, action.run_id)
        )

    assert port.execute_count == 0


def workspace_action_and_permit(
    correction: CorrectionAuthority,
    capability_id: str,
    arguments: dict[str, object],
    *,
    idempotency_key: str = "idempotency:workspace",
) -> tuple[ActionContract, ActionPermit]:
    now = datetime.now(timezone.utc)
    epochs = correction.snapshot("task:workspace", "run:workspace", capability_id)
    action = ActionContract(
        action_id="action:workspace",
        task_id="task:workspace",
        run_id="run:workspace",
        node_id="node:workspace",
        principal_id="principal:workspace",
        tenant_id="tenant:workspace",
        workspace_id="workspace:workspace",
        capability_id=capability_id,
        capability_version="1",
        arguments_json=json.dumps(arguments),
        risk_tier=0,
        idempotency_key=idempotency_key,
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=1,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=epochs,
        expected_outcome_id="expected:workspace",
        candidate_envelope_id="envelope:workspace",
        created_at=now,
    )
    permit = ActionPermit(
        permit_id="permit:workspace",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:workspace",
        grant_id="grant:workspace",
        correction_epochs=epochs,
        lease_fence=1,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    return action, permit


def test_developer_adapter_dispatches_read_through_broker(tmp_path: Path) -> None:
    from domain_packs.developer_agent import DeveloperWorkspaceAdapter

    (tmp_path / "fixture.txt").write_text("before\n", encoding="utf-8")
    store = SQLiteTaskEventStore(tmp_path / "state.sqlite3")
    adapter = DeveloperWorkspaceAdapter(tmp_path, idempotency_store=store)
    correction = CorrectionAuthority()
    action, permit = workspace_action_and_permit(
        correction,
        "workspace.read",
        {"path": "fixture.txt"},
    )
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    fence = store.acquire_lease(action.run_id, "test:worker", expiry.isoformat())

    result = CapabilityBroker(adapter, correction).invoke(
        action,
        permit,
        execution_claim=ExecutionLease(
            run_id=action.run_id,
            owner="test:worker",
            fence=fence,
            expires_at=expiry,
        ),
    )

    assert result.receipt.status is ReceiptStatus.SUCCEEDED
    assert result.receipt.connector_id == "workspace.read"
    assert result.output["content"] == "before\n"


def test_developer_adapter_specs_match_capability_ids(tmp_path: Path) -> None:
    from domain_packs.developer_agent import DeveloperWorkspaceAdapter

    adapter = DeveloperWorkspaceAdapter(tmp_path)

    assert tuple(sorted(adapter.specs())) == (
        "artifact.write",
        "workspace.apply_patch",
        "workspace.edit",
        "workspace.read",
        "workspace.run_tests",
        "workspace.search",
        "workspace.shell",
    )
    assert tuple(sorted(adapter.specs(include_internal=True))) == (
        "artifact.write",
        "workspace.apply_patch",
        "workspace.compensate_patch",
        "workspace.edit",
        "workspace.read",
        "workspace.run_tests",
        "workspace.search",
        "workspace.shell",
    )


def test_agent_core_does_not_import_developer_adapter() -> None:
    root = Path(__file__).parents[2] / "packages" / "os_core" / "src" / "agent_os_core"
    offenders = [
        path
        for path in root.glob("*.py")
        if "domain_packs.developer_agent" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_capability_core_has_no_workspace_concrete_type() -> None:
    root = Path(__file__).parents[2] / "packages" / "os_core" / "src" / "agent_os_core"
    capability_source = (root / "capability.py").read_text(encoding="utf-8")
    exports_source = (root / "__init__.py").read_text(encoding="utf-8")

    assert "class WorkspaceSandbox" not in capability_source
    assert '"WorkspaceSandbox"' not in exports_source


def test_only_broker_dispatches_the_capability_port() -> None:
    repo = Path(__file__).parents[2]
    capability_source = (
        repo / "packages/os_core/src/agent_os_core/capability.py"
    ).read_text(encoding="utf-8")
    execution_source = (
        repo / "packages/os_core/src/agent_os_core/execution.py"
    ).read_text(encoding="utf-8")
    app_source = (repo / "apps/api_server/app.py").read_text(encoding="utf-8")

    assert capability_source.count("self.connector.execute(action)") == 1
    assert "self.sandbox.execute" not in execution_source
    assert "self.capabilities.execute" not in execution_source
    assert "self.sandbox.execute" not in app_source
    assert "self.capabilities.execute" not in app_source


def test_execution_core_has_no_workspace_concrete_type_or_patch_prompt() -> None:
    root = Path(__file__).parents[2] / "packages" / "os_core" / "src" / "agent_os_core"
    execution_source = (root / "execution.py").read_text(encoding="utf-8")

    assert "WorkspaceSandbox" not in execution_source
    assert "Repository task:" not in execution_source
    assert "workspace.apply_patch tool" not in execution_source
    assert "def _parse_patch_json" not in execution_source
    assert "def _tool_arguments" not in execution_source


class MinimalExecutionProfile:
    generator_id = "minimal-profile"
    generator_version = "1"

    def build_provider_request(
        self,
        *,
        task_id: str,
        run_id: str,
        provider_profile: ProviderProfile,
        provider_capability: str,
        context: Mapping[str, Any],
        now: datetime,
    ) -> ProviderRequest:
        raise NotImplementedError

    def bind_provider_response(
        self,
        response: ProviderResponse,
        *,
        context: Mapping[str, Any],
    ) -> tuple[ProviderToolProposal, ...]:
        return ()

    def tool_arguments(
        self,
        capability_id: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {}

    def requires_provider_bound_action(self, capability_id: str) -> bool:
        return False

    def verification_exit_code(self, context: Mapping[str, Any]) -> int | None:
        return None


def test_run_coordinator_constructs_with_generic_ports_only(tmp_path: Path) -> None:
    from agent_os_core import (
        DeterministicProvider,
        PolicyKernel,
        RunCoordinator,
        SQLiteTaskEventStore,
        TaskService,
    )

    correction = CorrectionAuthority()
    now = datetime.now(timezone.utc)
    runner = RunCoordinator(
        TaskService(SQLiteTaskEventStore(tmp_path / "state.sqlite3")),
        SpyCapabilityPort(tmp_path),
        MinimalExecutionProfile(),
        DeterministicProvider(),
        ProviderProfile(
            profile_id="provider-profile:boundary",
            provider_id="deterministic",
            model_id="deterministic-v1",
            endpoint_class="test",
            credential_ref_id="credential:boundary",
            capabilities=("chat",),
            max_context_tokens=16000,
            request_timeout_seconds=60,
            created_at=now,
        ),
        PolicyKernel(correction),
        correction,
        {},
    )

    assert runner.execution_profile.generator_id == "minimal-profile"
    assert isinstance(runner.broker, CapabilityBroker)
