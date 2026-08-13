from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    CapabilitySpec,
    CollaborationDisposition,
    CoordinationAuthorityContext,
    CorrectionEpochVector,
    ReceiptStatus,
    ResourceBudget,
    ResourceScope,
    ScopeSelector,
    WorkLease,
    WorkspaceActorKind,
    WorkspaceEvent,
    WorkspaceEventImpact,
    WorkspaceEventKind,
    WorkspaceWriteDecision,
)
from agent_os_core import (
    CapabilityBroker,
    CapabilityDenied,
    CapabilityEffect,
    ExecutionLease,
    ReplanRequired,
    WorkspaceWriteRejected,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _authority(
    *, principal_id: str = "user:local", scopes: tuple[ResourceScope, ...] | None = None
) -> CoordinationAuthorityContext:
    now = _now()
    return CoordinationAuthorityContext(
        authorization_id="auth:1",
        principal_id=principal_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        authorized_scopes=scopes
        or (ResourceScope(resource_uri="file:///ws/a.txt"),),
        evidence_refs=("ev:1",),
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _lease(
    *,
    run_id: str = "run:long",
    holder_id: str = "test:worker",
    fence_token: int = 1,
    scopes: tuple[ResourceScope, ...] | None = None,
    event_cursor: int = 0,
    authority_scopes: tuple[ResourceScope, ...] | None = None,
) -> WorkLease:
    now = _now()
    return WorkLease(
        lease_id="lease:1",
        lease_version=1,
        fence_token=fence_token,
        task_id="task:long",
        run_id=run_id,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        holder_id=holder_id,
        plan_version=1,
        event_cursor=event_cursor,
        scopes=scopes or (ResourceScope(resource_uri="file:///ws/a.txt"),),
        authority_context=_authority(
            principal_id=holder_id,
            scopes=authority_scopes
            or (ResourceScope(resource_uri="file:///ws/a.txt"),),
        ),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _claim(
    run_id: str = "run:long", owner: str = "test:worker", fence: int = 1
) -> ExecutionLease:
    return ExecutionLease(
        run_id=run_id,
        owner=owner,
        fence=fence,
        expires_at=_now() + timedelta(minutes=5),
    )


def _action(
    capability_id: str = "workspace.edit",
    *,
    arguments: dict | None = None,
    run_id: str = "run:long",
    idempotency_key: str = "run:edit",
) -> ActionContract:
    now = _now()
    return ActionContract(
        action_id="action:edit",
        task_id="task:long",
        run_id=run_id,
        node_id="node:edit",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        capability_id=capability_id,
        capability_version="1",
        arguments_json=json.dumps(arguments or {"path": "a.txt"}),
        risk_tier=2,
        idempotency_key=idempotency_key,
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"), max_duration_seconds=10, max_provider_tokens=0, max_tool_calls=1
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:1",
        candidate_envelope_id="envelope:1",
        created_at=now,
    )


def _permit(action: ActionContract) -> ActionPermit:
    now = _now()
    return ActionPermit(
        permit_id=f"permit:{action.action_id}",
        action_id=action.action_id,
        action_digest=action.action_digest(),
        principal_id=action.principal_id,
        tenant_id=action.tenant_id,
        workspace_id=action.workspace_id,
        policy_decision_id="decision:1",
        grant_id="grant:1",
        correction_epochs=action.observed_correction_epochs,
        lease_fence=1,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


class _NoopCorrection:
    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
        return False

    def snapshot(
        self, task_id: str, run_id: str, capability_id: str
    ) -> CorrectionEpochVector:
        return CorrectionEpochVector(task_epoch=0, run_epoch=0, capability_epoch=0)

    def guard_unchanged(self, *args: object, **kwargs: object):
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            yield True

        return _ctx()


class _FakeConnector:
    """Minimal CapabilityPort for seam tests; counts execute calls."""

    def __init__(
        self,
        *,
        collaboration_required: bool = False,
        outcomes_repo=None,
    ) -> None:
        self.execute_calls = 0
        self.collaboration_required = collaboration_required
        self._outcomes = outcomes_repo

    def specs(self, now=None, *, include_internal: bool = False):
        from agent_os_contracts import SideEffectGuarantee

        return {
            "workspace.edit": CapabilitySpec(
                capability_id="workspace.edit",
                version="1",
                display_name="Edit workspace file",
                input_contract="json:object:1",
                output_contract="json:object:1",
                side_effect_guarantee=SideEffectGuarantee.SANDBOX_COMPENSATABLE,
                idempotency_supported=True,
                cancellation_supported=True,
                compensation_supported=True,
                credential_class="none",
                data_boundary="workspace-local",
                risk_tier=2,
                timeout_seconds=120,
                audit_policy="event-and-artifact",
                created_by="system",
                created_at=_now(),
                collaboration_required=self.collaboration_required,
            )
        }

    def execute(self, action):
        self.execute_calls += 1
        return _FakeEffect()

    def replay(self, action):
        return None

    def outcomes(self):
        return self._outcomes

    def preflight(self, capability_id, args, action_key):
        return None

    def acquire_execution_lease(self, action, owner):
        raise NotImplementedError

    def release_execution_lease(self, lease):
        return False


class _FakeEffect(CapabilityEffect):
    def __init__(self) -> None:
        super().__init__(status=ReceiptStatus.SUCCEEDED, output={})


class _DecisionPreflight:
    """Returns a fixed disposition; records the claim it was handed."""

    def __init__(self, disposition: CollaborationDisposition) -> None:
        self.disposition = disposition
        self.seen_claim: ExecutionLease | None = None

    def preflight(self, action, claim):
        self.seen_claim = claim
        return _decision(disposition=self.disposition, action_id=action.action_id)


def _decision(
    *,
    disposition: CollaborationDisposition,
    action_id: str = "action:edit",
    write_scopes: tuple[ResourceScope, ...] | None = None,
) -> WorkspaceWriteDecision:
    return WorkspaceWriteDecision(
        lease_id="lease:1",
        action_id=action_id,
        plan_version=1,
        disposition=disposition,
        checked_event_cursor=0,
        relevant_event_ids=(),
        event_batch_provenance_ref="batch:1",
        write_scopes=write_scopes or (ResourceScope(resource_uri="file:///ws/a.txt"),),
        reason="test",
        decided_at=_now(),
    )


# ---------------------------------------------------------------------------
# Contract invariants
# ---------------------------------------------------------------------------


def test_resource_scope_selector_aware_overlap() -> None:
    file_a = ResourceScope(resource_uri="file:///ws/a.txt")
    file_b = ResourceScope(resource_uri="file:///ws/b.txt")
    sym_x = ResourceScope(
        resource_uri="file:///ws/a.txt", selectors=(ScopeSelector(dimension="symbol", value="x"),)
    )
    sym_y = ResourceScope(
        resource_uri="file:///ws/a.txt", selectors=(ScopeSelector(dimension="symbol", value="y"),)
    )
    assert not file_a.overlaps(file_b)
    assert file_a.overlaps(sym_x)
    assert sym_x.overlaps(file_a)
    assert not sym_x.overlaps(sym_y)
    assert file_a.covers(sym_x)


def test_work_lease_same_origin_identity() -> None:
    lease = _lease()
    assert lease.run_id == "run:long"
    assert lease.holder_id == "test:worker"
    assert lease.fence_token == 1


def test_work_lease_scope_must_be_covered_by_authority() -> None:
    with pytest.raises(ValueError, match="scope"):
        _lease(
            scopes=(ResourceScope(resource_uri="file:///ws/other.txt"),),
            authority_scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),),
        )


def test_workspace_event_requires_version_advance() -> None:
    now = _now()
    with pytest.raises(ValueError, match="advance"):
        WorkspaceEvent(
            event_id="ev:1",
            workspace_id="workspace:local",
            sequence=1,
            actor_id="user:local",
            actor_kind=WorkspaceActorKind.HUMAN,
            kind=WorkspaceEventKind.MUTATION,
            impact=WorkspaceEventImpact.CONTEXT_CHANGED,
            affected_scopes=(ResourceScope(resource_uri="file:///ws/a.txt"),),
            base_version="v1",
            resulting_version="v1",
            provenance_refs=("p:1",),
            occurred_at=now,
        )


# ---------------------------------------------------------------------------
# Broker seam: disposition routing must block dispatch with zero side effects
# ---------------------------------------------------------------------------


def test_conflict_denies_dispatch_with_zero_connector_calls() -> None:
    connector = _FakeConnector(collaboration_required=True)
    broker = CapabilityBroker(
        connector, _NoopCorrection(), collaboration_preflight=_DecisionPreflight(CollaborationDisposition.CONFLICT)
    )
    action = _action()
    permit = _permit(action)
    with pytest.raises(WorkspaceWriteRejected):
        broker.invoke(action, permit, execution_claim=_claim())
    assert connector.execute_calls == 0


def test_cancel_denies_dispatch_with_zero_connector_calls() -> None:
    connector = _FakeConnector(collaboration_required=True)
    broker = CapabilityBroker(
        connector, _NoopCorrection(), collaboration_preflight=_DecisionPreflight(CollaborationDisposition.CANCEL)
    )
    action = _action()
    with pytest.raises(WorkspaceWriteRejected):
        broker.invoke(action, _permit(action), execution_claim=_claim())
    assert connector.execute_calls == 0


def test_replan_blocks_dispatch_with_zero_connector_calls() -> None:
    connector = _FakeConnector(collaboration_required=True)
    broker = CapabilityBroker(
        connector, _NoopCorrection(), collaboration_preflight=_DecisionPreflight(CollaborationDisposition.REPLAN)
    )
    action = _action()
    with pytest.raises(ReplanRequired):
        broker.invoke(action, _permit(action), execution_claim=_claim())
    assert connector.execute_calls == 0


def _held_claim(
    outcomes, action: ActionContract
) -> ExecutionLease:
    return outcomes.acquire_execution_lease(action, "test:worker")


def test_continue_reaches_connector(tmp_path: Path) -> None:
    from agent_os_core import DurableActionOutcomeRepository, SQLiteTaskEventStore

    store = SQLiteTaskEventStore(tmp_path / "store.sqlite3")
    outcomes = DurableActionOutcomeRepository(store)
    connector = _FakeConnector(
        collaboration_required=True,
        outcomes_repo=outcomes,
    )
    broker = CapabilityBroker(
        connector, _NoopCorrection(), collaboration_preflight=_DecisionPreflight(CollaborationDisposition.CONTINUE)
    )
    action = _action()
    broker.invoke(action, _permit(action), execution_claim=_held_claim(outcomes, action))
    assert connector.execute_calls == 1


def test_preflight_receives_the_execution_claim(tmp_path: Path) -> None:
    from agent_os_core import DurableActionOutcomeRepository, SQLiteTaskEventStore

    store = SQLiteTaskEventStore(tmp_path / "store.sqlite3")
    outcomes = DurableActionOutcomeRepository(store)
    connector = _FakeConnector(
        collaboration_required=True,
        outcomes_repo=outcomes,
    )
    preflight = _DecisionPreflight(CollaborationDisposition.CONTINUE)
    broker = CapabilityBroker(connector, _NoopCorrection(), collaboration_preflight=preflight)
    action = _action()
    claim = _held_claim(outcomes, action)
    broker.invoke(action, _permit(action), execution_claim=claim)
    assert preflight.seen_claim is not None
    assert preflight.seen_claim.run_id == claim.run_id
    assert preflight.seen_claim.fence == claim.fence


def test_non_collaboration_capability_skips_preflight(tmp_path: Path) -> None:
    from agent_os_core import DurableActionOutcomeRepository, SQLiteTaskEventStore

    store = SQLiteTaskEventStore(tmp_path / "store.sqlite3")
    outcomes = DurableActionOutcomeRepository(store)
    connector = _FakeConnector(
        collaboration_required=False,
        outcomes_repo=outcomes,
    )
    broker = CapabilityBroker(connector, _NoopCorrection(), collaboration_preflight=None)
    action = _action()
    broker.invoke(action, _permit(action), execution_claim=_held_claim(outcomes, action))
    assert connector.execute_calls == 1


# P2 debt 1: caller cannot downgrade collaboration_required from the trusted registry
def test_collaboration_required_reads_trusted_registry_not_caller_args() -> None:
    connector = _FakeConnector(collaboration_required=True)
    broker = CapabilityBroker(connector, _NoopCorrection(), collaboration_preflight=None)
    # The action's arguments claim nothing about collaboration; the trusted spec
    # marks the capability collaboration_required=True, so dispatch must fail-closed.
    action = _action(arguments={"path": "a.txt", "collaboration_required": False})
    with pytest.raises(CapabilityDenied, match="collaboration"):
        broker.invoke(action, _permit(action), execution_claim=_claim())
    assert connector.execute_calls == 0


# P2 debt 2: replay outcome is not rewritten by new events; new action still fenced
def test_replay_before_preflight_returns_sealed_outcome_unchanged() -> None:
    from agent_os_contracts import ActionReceipt, ReceiptStatus
    from agent_os_core import CapabilityResult

    action = _action()
    permit = _permit(action)
    sealed = CapabilityResult(
        receipt=ActionReceipt(
            receipt_id="receipt:sealed",
            action_id=action.action_id,
            action_digest=action.action_digest(),
            permit_id=permit.permit_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            connector_id="workspace.edit",
            status=ReceiptStatus.SUCCEEDED,
            idempotency_key="run:edit",
            attempt=1,
            occurred_at=_now(),
        ),
        output={},
        permit=permit,
    )

    class ReplayConnector(_FakeConnector):
        def replay(self, action):  # type: ignore[override]
            return sealed

    connector = ReplayConnector(collaboration_required=True)
    # A hostile preflight would try to block; replay must return before preflight runs.
    hostile = _DecisionPreflight(CollaborationDisposition.CONFLICT)
    broker = CapabilityBroker(connector, _NoopCorrection(), collaboration_preflight=hostile)
    result = broker.invoke(action, permit, execution_claim=_claim())
    assert result is sealed
    assert hostile.seen_claim is None
    assert connector.execute_calls == 0


def test_new_action_still_fenced_after_replay_of_other_action() -> None:
    connector = _FakeConnector(collaboration_required=True)
    broker = CapabilityBroker(
        connector, _NoopCorrection(), collaboration_preflight=_DecisionPreflight(CollaborationDisposition.CONFLICT)
    )
    action = _action(idempotency_key="run:new")
    with pytest.raises(WorkspaceWriteRejected):
        broker.invoke(action, _permit(action), execution_claim=_claim())
    assert connector.execute_calls == 0
