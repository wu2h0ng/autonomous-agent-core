"""QA verification tests for the Rollback Infrastructure MVP.

Independent test suite created by QA Engineer (Edward) to verify:
1. OperationStateMachine boundary conditions
2. ActionConnectorRegistry edge cases
3. ActionGovernance dynamic filling
4. ApprovalLiteRuntime lifecycle
5. ManualReviewConnector complete interface
6. TrustedLoopRuntime end-to-end integration
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    ActionProposal,
    MetricContract,
    OperationContract,
    OperationState,
    ProviderContract,
    ProviderKind,
    RiskLevel,
    SQLTemplate,
)
from agent_os_core.action_connectors.base import ActionConnector  # noqa: E402
from agent_os_core.action_connectors.registry import ActionConnectorRegistry  # noqa: E402
from agent_os_core.action_governance import (  # noqa: E402
    ActionGovernance,
    RiskCeilingExceeded,
    UnsupportedActionType,
)
from agent_os_core.approval_lite import ApprovalLiteRuntime  # noqa: E402
from agent_os_core.operation_state_machine import (  # noqa: E402
    InvalidStateTransition,
    OperationStateMachine,
)
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core import TrustedLoopRuntime, SemanticRegistry, ProviderRegistry  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402


def _build_default_connector_registry() -> ActionConnectorRegistry:
    """Build a connector registry with ManualReviewConnector.

    Caller-side construction: OS Core never imports action connectors.
    """
    registry = ActionConnectorRegistry()
    connector = ManualReviewConnector()
    contract = ActionConnectorContract(
        connector_name="manual_review",
        display_name="Manual Review",
        supported_action_types=("propose", "execute"),
        supports_snapshot=False,
        supports_rollback=False,
        compensating_action_description=None,
        risk_ceiling="R5",
        owner="system",
    )
    registry.register(connector, contract)
    return registry


# ──────────────────────────────────────────────────────────────────────
# 1. OperationStateMachine boundary tests
# ──────────────────────────────────────────────────────────────────────


class OperationStateMachineBoundaryTest(unittest.TestCase):
    """Exhaustive boundary tests for the state machine."""

    def setUp(self) -> None:
        self.sm = OperationStateMachine()

    # --- Terminal states have no allowed transitions ---
    def test_rejected_has_no_allowed_transitions(self) -> None:
        self.assertEqual(self.sm.allowed_transitions(OperationState.REJECTED), ())

    def test_observed_has_no_allowed_transitions(self) -> None:
        self.assertEqual(self.sm.allowed_transitions(OperationState.OBSERVED), ())

    def test_failed_has_no_allowed_transitions(self) -> None:
        self.assertEqual(self.sm.allowed_transitions(OperationState.FAILED), ())

    # --- Every illegal transition triggers InvalidStateTransition ---
    def test_executed_to_proposed_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.EXECUTED, OperationState.PROPOSED)

    def test_rejected_to_approved_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.REJECTED, OperationState.APPROVED)

    def test_failed_to_rolling_back_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.FAILED, OperationState.ROLLING_BACK)

    def test_observed_to_executed_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.OBSERVED, OperationState.EXECUTED)

    def test_proposed_to_executed_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.PROPOSED, OperationState.EXECUTED)

    def test_proposed_to_snapshotting_raises(self) -> None:
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.PROPOSED, OperationState.SNAPSHOTTING)

    def test_approved_to_rejected_raises(self) -> None:
        """APPROVED can only go to SNAPSHOTTING or EXECUTED, not REJECTED."""
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.APPROVED, OperationState.REJECTED)

    # --- InvalidStateTransition has correct attributes ---
    def test_exception_has_current_attribute(self) -> None:
        try:
            self.sm.transition(OperationState.EXECUTED, OperationState.PROPOSED)
        except InvalidStateTransition as e:
            self.assertEqual(e.current, OperationState.EXECUTED)

    def test_exception_has_target_attribute(self) -> None:
        try:
            self.sm.transition(OperationState.EXECUTED, OperationState.PROPOSED)
        except InvalidStateTransition as e:
            self.assertEqual(e.target, OperationState.PROPOSED)

    def test_exception_has_message_attribute(self) -> None:
        try:
            self.sm.transition(OperationState.EXECUTED, OperationState.PROPOSED)
        except InvalidStateTransition as e:
            self.assertIsInstance(e.message, str)
            self.assertIn("executed", e.message)
            self.assertIn("proposed", e.message)

    def test_exception_custom_message(self) -> None:
        """Verify that a custom message can be passed and is preserved."""
        exc = InvalidStateTransition(OperationState.FAILED, OperationState.APPROVED, "custom msg")
        self.assertEqual(exc.message, "custom msg")
        self.assertEqual(exc.current, OperationState.FAILED)
        self.assertEqual(exc.target, OperationState.APPROVED)

    def test_exception_default_message_format(self) -> None:
        exc = InvalidStateTransition(OperationState.REJECTED, OperationState.APPROVED)
        self.assertEqual(exc.message, "Invalid state transition: rejected -> approved")

    # --- Additional boundary: same-state transition ---
    def test_same_state_transition_raises(self) -> None:
        """Transitioning to the same state is not allowed (no self-loops)."""
        with self.assertRaises(InvalidStateTransition):
            self.sm.transition(OperationState.PROPOSED, OperationState.PROPOSED)

    # --- Verify all terminal states cannot transition anywhere ---
    def test_all_terminal_state_transitions_raise(self) -> None:
        """For every terminal state, every possible target raises."""
        terminal_states = [OperationState.REJECTED, OperationState.OBSERVED, OperationState.FAILED]
        all_states = list(OperationState)
        for terminal in terminal_states:
            for target in all_states:
                with self.assertRaises(
                    InvalidStateTransition,
                    msg=f"Terminal {terminal.value} should not transition to {target.value}",
                ):
                    self.sm.transition(terminal, target)


# ──────────────────────────────────────────────────────────────────────
# 2. ActionConnectorRegistry boundary tests
# ──────────────────────────────────────────────────────────────────────


class ActionConnectorRegistryBoundaryTest(unittest.TestCase):
    """Edge-case tests for the connector registry."""

    def _make_connector(self, name: str = "test_connector") -> ActionConnector:
        """Create a minimal concrete connector for testing."""

        class _Stub(ActionConnector):
            @property
            def connector_name(self) -> str:
                return name

            def take_snapshot(self, operation):
                return None

            def execute(self, operation, parameters):
                return {"status": "ok"}

            def rollback(self, snapshot):
                return {"status": "ok"}

            def can_rollback(self):
                return False

            def compensating_action(self):
                return None

        return _Stub()

    def _make_contract(self, name: str = "test_connector") -> ActionConnectorContract:
        return ActionConnectorContract(
            connector_name=name,
            display_name=f"Test {name}",
            supported_action_types=("propose", "execute"),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R5",
            owner="test",
        )

    def test_register_name_mismatch_raises_valueerror(self) -> None:
        """Connector name != contract name must raise ValueError."""
        connector = self._make_connector("connector_a")
        contract = self._make_contract("connector_b")
        with self.assertRaises(ValueError) as ctx:
            ActionConnectorRegistry().register(connector, contract)
        self.assertIn("connector_a", str(ctx.exception))
        self.assertIn("connector_b", str(ctx.exception))

    def test_get_nonexistent_raises_keyerror_with_available_list(self) -> None:
        """KeyError message should contain the list of available connectors."""
        registry = ActionConnectorRegistry()
        connector = self._make_connector("alpha")
        contract = self._make_contract("alpha")
        registry.register(connector, contract)

        with self.assertRaises(KeyError) as ctx:
            registry.get("nonexistent")

        error_msg = str(ctx.exception)
        self.assertIn("alpha", error_msg)
        self.assertIn("nonexistent", error_msg)

    def test_get_contract_nonexistent_raises_keyerror(self) -> None:
        """get_contract for nonexistent name should raise KeyError."""
        registry = ActionConnectorRegistry()
        with self.assertRaises(KeyError):
            registry.get_contract("nothing")

    def test_reregister_overwrites_old_value(self) -> None:
        """Re-registering the same connector_name should overwrite the old entry."""
        registry = ActionConnectorRegistry()

        # First registration
        c1 = self._make_connector("my_connector")
        contract1 = self._make_contract("my_connector")
        contract1 = ActionConnectorContract(
            connector_name="my_connector",
            display_name="Version 1",
            supported_action_types=("propose",),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R3",
            owner="team_a",
        )
        registry.register(c1, contract1)

        # Second registration with different contract
        c2 = self._make_connector("my_connector")
        contract2 = ActionConnectorContract(
            connector_name="my_connector",
            display_name="Version 2",
            supported_action_types=("propose", "execute"),
            supports_snapshot=True,
            supports_rollback=True,
            compensating_action_description="Undo action",
            risk_ceiling="R5",
            owner="team_b",
        )
        registry.register(c2, contract2)

        # Should return the second (overwritten) contract
        result = registry.get_contract("my_connector")
        self.assertEqual(result.display_name, "Version 2")
        self.assertTrue(result.supports_snapshot)
        self.assertTrue(result.supports_rollback)

    def test_list_connectors_empty(self) -> None:
        """Empty registry should return empty tuple."""
        registry = ActionConnectorRegistry()
        self.assertEqual(registry.list_connectors(), ())

    def test_list_connectors_returns_all(self) -> None:
        """list_connectors should return all registered contracts."""
        registry = ActionConnectorRegistry()
        for name in ("a", "b", "c"):
            registry.register(self._make_connector(name), self._make_contract(name))
        self.assertEqual(len(registry.list_connectors()), 3)
        names = {c.connector_name for c in registry.list_connectors()}
        self.assertEqual(names, {"a", "b", "c"})


# ──────────────────────────────────────────────────────────────────────
# 3. ActionGovernance dynamic filling tests
# ──────────────────────────────────────────────────────────────────────


class ActionGovernanceDynamicFillTest(unittest.TestCase):
    """Tests for dynamic contract filling from the connector registry."""

    def _make_proposal(
        self,
        risk_level: RiskLevel = RiskLevel.R2,
        connector_name: str = "manual_review",
        action_type: str = "propose",
        approval_required: bool = False,
    ) -> ActionProposal:
        return ActionProposal(
            proposal_id="prop-001",
            evidence_chain_id="ev-001",
            target_object="gmv",
            recommended_action="Review the result",
            reason="Test reason",
            risk_level=risk_level,
            expected_impact="Test impact",
            approval_required=approval_required,
            approver_role=None,
            connector_name=connector_name,
            action_type=action_type,
            action_parameters={},
        )

    def _make_registry_with_connector(
        self,
        supports_snapshot: bool = True,
        supports_rollback: bool = True,
        compensating_description: str | None = "Undo it",
        risk_ceiling: str = "R5",
        supported_action_types: tuple[str, ...] = ("propose", "execute"),
    ) -> ActionConnectorRegistry:
        """Build a registry with a 'test_conn' connector."""

        class _TestConnector(ActionConnector):
            @property
            def connector_name(self):
                return "test_conn"

            def take_snapshot(self, operation):
                return None

            def execute(self, operation, parameters):
                return {"status": "ok"}

            def rollback(self, snapshot):
                return {"status": "ok"}

            def can_rollback(self):
                return supports_rollback

            def compensating_action(self):
                return compensating_description

        registry = ActionConnectorRegistry()
        connector = _TestConnector()
        contract = ActionConnectorContract(
            connector_name="test_conn",
            display_name="Test Connector",
            supported_action_types=supported_action_types,
            supports_snapshot=supports_snapshot,
            supports_rollback=supports_rollback,
            compensating_action_description=compensating_description,
            risk_ceiling=risk_ceiling,
            owner="test",
        )
        registry.register(connector, contract)
        return registry

    def test_with_registry_snapshot_required_from_connector(self) -> None:
        """When registry has a connector with supports_snapshot=True, contract should reflect that."""
        registry = self._make_registry_with_connector(supports_snapshot=True)
        gov = ActionGovernance(connector_registry=registry)
        proposal = self._make_proposal(connector_name="test_conn")
        contract = gov.build_operation_contract(proposal)
        self.assertTrue(contract.snapshot_required)

    def test_with_registry_rollback_supported_from_connector(self) -> None:
        """When registry has a connector with supports_rollback=True, contract should reflect that."""
        registry = self._make_registry_with_connector(supports_rollback=True)
        gov = ActionGovernance(connector_registry=registry)
        proposal = self._make_proposal(connector_name="test_conn")
        contract = gov.build_operation_contract(proposal)
        self.assertTrue(contract.rollback_supported)

    def test_with_registry_compensating_action_from_connector(self) -> None:
        """When registry connector declares a compensating action, contract should have it."""
        registry = self._make_registry_with_connector(compensating_description="Rollback data")
        gov = ActionGovernance(connector_registry=registry)
        proposal = self._make_proposal(connector_name="test_conn")
        contract = gov.build_operation_contract(proposal)
        self.assertEqual(contract.compensating_action, "Rollback data")

    def test_with_registry_risk_above_connector_ceiling_raises(self) -> None:
        registry = self._make_registry_with_connector(risk_ceiling="R3")
        gov = ActionGovernance(connector_registry=registry)
        proposal = self._make_proposal(
            connector_name="test_conn",
            risk_level=RiskLevel.R4,
            action_type="execute",
            approval_required=True,
        )

        with self.assertRaises(RiskCeilingExceeded):
            gov.build_operation_contract(proposal)

    def test_with_registry_unsupported_action_type_raises(self) -> None:
        registry = self._make_registry_with_connector(supported_action_types=("propose",))
        gov = ActionGovernance(connector_registry=registry)
        proposal = self._make_proposal(connector_name="test_conn", action_type="execute")

        with self.assertRaises(UnsupportedActionType):
            gov.build_operation_contract(proposal)

    def test_without_registry_uses_defaults(self) -> None:
        """Without a registry, snapshot_required and rollback_supported should default to False."""
        gov = ActionGovernance(connector_registry=None)
        proposal = self._make_proposal()
        contract = gov.build_operation_contract(proposal)
        self.assertFalse(contract.snapshot_required)
        self.assertFalse(contract.rollback_supported)
        self.assertIsNone(contract.compensating_action)

    def test_with_registry_unregistered_connector_uses_defaults(self) -> None:
        """When registry exists but connector_name not in it, should use defaults."""
        registry = self._make_registry_with_connector()  # has "test_conn"
        gov = ActionGovernance(connector_registry=registry)
        proposal = self._make_proposal(connector_name="not_registered")  # different name
        contract = gov.build_operation_contract(proposal)
        self.assertFalse(contract.snapshot_required)
        self.assertFalse(contract.rollback_supported)

    # --- should_snapshot tests ---
    def test_should_snapshot_r0_returns_false(self) -> None:
        """R0 + snapshot_required=True should still return False (no snapshot for lowest risk)."""
        gov = ActionGovernance()
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R0",
            approval_required=False,
            snapshot_required=True,
        )
        self.assertFalse(gov.should_snapshot(op))

    def test_should_snapshot_r1_returns_false(self) -> None:
        """R1 + snapshot_required=True should return False."""
        gov = ActionGovernance()
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R1",
            approval_required=False,
            snapshot_required=True,
        )
        self.assertFalse(gov.should_snapshot(op))

    def test_should_snapshot_r3_returns_true(self) -> None:
        """R3 + snapshot_required=True should return True."""
        gov = ActionGovernance()
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R3",
            approval_required=False,
            snapshot_required=True,
        )
        self.assertTrue(gov.should_snapshot(op))

    def test_should_snapshot_r5_returns_true(self) -> None:
        """R5 + snapshot_required=True should return True."""
        gov = ActionGovernance()
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R5",
            approval_required=True,
            snapshot_required=True,
        )
        self.assertTrue(gov.should_snapshot(op))

    def test_should_snapshot_not_required_returns_false(self) -> None:
        """Even R5 with snapshot_required=False should return False."""
        gov = ActionGovernance()
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R5",
            approval_required=True,
            snapshot_required=False,
        )
        self.assertFalse(gov.should_snapshot(op))


# ──────────────────────────────────────────────────────────────────────
# 4. ApprovalLiteRuntime lifecycle tests
# ──────────────────────────────────────────────────────────────────────


class ApprovalLiteRuntimeLifecycleTest(unittest.TestCase):
    """Tests for approval record lifecycle management."""

    def setUp(self) -> None:
        self.runtime = ApprovalLiteRuntime()

    def test_approve_non_pending_raises_valueerror(self) -> None:
        """Approving an already-approved record should raise ValueError."""
        self.runtime.create_pending(
            approval_id="apr-1",
            proposal_id="prop-1",
            approver_role="owner",
        )
        self.runtime.approve("apr-1")
        with self.assertRaises(ValueError) as ctx:
            self.runtime.approve("apr-1")
        self.assertIn("approved", str(ctx.exception))

    def test_reject_non_pending_raises_valueerror(self) -> None:
        """Rejecting an already-rejected record should raise ValueError."""
        self.runtime.create_pending(
            approval_id="apr-2",
            proposal_id="prop-2",
            approver_role="owner",
        )
        self.runtime.reject("apr-2")
        with self.assertRaises(ValueError) as ctx:
            self.runtime.reject("apr-2")
        self.assertIn("rejected", str(ctx.exception))

    def test_approve_rejected_raises_valueerror(self) -> None:
        """Approving a rejected record should raise ValueError."""
        self.runtime.create_pending(
            approval_id="apr-3",
            proposal_id="prop-3",
            approver_role="owner",
        )
        self.runtime.reject("apr-3")
        with self.assertRaises(ValueError):
            self.runtime.approve("apr-3")

    def test_reject_approved_raises_valueerror(self) -> None:
        """Rejecting an approved record should raise ValueError."""
        self.runtime.create_pending(
            approval_id="apr-4",
            proposal_id="prop-4",
            approver_role="owner",
        )
        self.runtime.approve("apr-4")
        with self.assertRaises(ValueError):
            self.runtime.reject("apr-4")

    def test_get_nonexistent_raises_keyerror(self) -> None:
        """Getting a non-existent approval record should raise KeyError."""
        with self.assertRaises(KeyError) as ctx:
            self.runtime.get("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_approve_nonexistent_raises_keyerror(self) -> None:
        """Approving a non-existent record should raise KeyError."""
        with self.assertRaises(KeyError):
            self.runtime.approve("ghost")

    def test_reject_nonexistent_raises_keyerror(self) -> None:
        """Rejecting a non-existent record should raise KeyError."""
        with self.assertRaises(KeyError):
            self.runtime.reject("ghost")

    def test_approve_sets_status_to_approved(self) -> None:
        """After approve(), the record status should be 'approved'."""
        self.runtime.create_pending(
            approval_id="apr-5",
            proposal_id="prop-5",
            approver_role="admin",
        )
        updated = self.runtime.approve("apr-5")
        self.assertEqual(updated.status, "approved")
        self.assertEqual(updated.approval_id, "apr-5")

    def test_reject_sets_status_to_rejected(self) -> None:
        """After reject(), the record status should be 'rejected'."""
        self.runtime.create_pending(
            approval_id="apr-6",
            proposal_id="prop-6",
            approver_role="admin",
        )
        updated = self.runtime.reject("apr-6", reason="Not justified")
        self.assertEqual(updated.status, "rejected")
        self.assertEqual(updated.reason, "Not justified")

    def test_create_pending_initial_status(self) -> None:
        """Newly created record should have status 'pending'."""
        record = self.runtime.create_pending(
            approval_id="apr-7",
            proposal_id="prop-7",
            approver_role="mgr",
        )
        self.assertEqual(record.status, "pending")
        self.assertEqual(record.approver_role, "mgr")

    def test_get_returns_created_record(self) -> None:
        """get() should return the same record that was created."""
        record = self.runtime.create_pending(
            approval_id="apr-8",
            proposal_id="prop-8",
            approver_role="owner",
        )
        fetched = self.runtime.get("apr-8")
        self.assertEqual(fetched.approval_id, record.approval_id)
        self.assertEqual(fetched.status, "pending")


# ──────────────────────────────────────────────────────────────────────
# 5. ManualReviewConnector complete tests
# ──────────────────────────────────────────────────────────────────────


class ManualReviewConnectorCompleteTest(unittest.TestCase):
    """Complete interface tests for ManualReviewConnector."""

    def setUp(self) -> None:
        self.connector = ManualReviewConnector()

    def test_take_snapshot_returns_none(self) -> None:
        """Manual review never needs a snapshot."""
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R4",
            approval_required=True,
        )
        self.assertIsNone(self.connector.take_snapshot(op))

    def test_execute_returns_status_assigned_to_operation_id(self) -> None:
        """execute() must return dict with status, assigned_to, and operation_id."""
        op = OperationContract(
            operation_id="op-123",
            name="test_op",
            target_connector="manual_review",
            risk_level="R5",
            approval_required=True,
        )
        result = self.connector.execute(op, {})
        self.assertIn("status", result)
        self.assertIn("assigned_to", result)
        self.assertIn("operation_id", result)
        self.assertEqual(result["status"], "pending_approval")
        self.assertEqual(result["operation_id"], "op-123")

    def test_execute_with_approval_required_assigns_approver(self) -> None:
        """When approval is required, assigned_to should be 'approver'."""
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R5",
            approval_required=True,
        )
        result = self.connector.execute(op, {})
        self.assertEqual(result["assigned_to"], "approver")

    def test_execute_without_approval_required_assigned_to_is_none(self) -> None:
        """When approval is not required, assigned_to should be None."""
        op = OperationContract(
            operation_id="op-1",
            name="test",
            target_connector="manual_review",
            risk_level="R1",
            approval_required=False,
        )
        result = self.connector.execute(op, {})
        self.assertIsNone(result["assigned_to"])

    def test_rollback_returns_not_applicable(self) -> None:
        """rollback() should return status='not_applicable' with reason."""
        from agent_os_contracts import StateSnapshot

        snapshot = StateSnapshot(
            snapshot_id="snap-1",
            operation_id="op-1",
            connector_name="manual_review",
            snapshot_type="full",
            state_payload={},
            created_at="2026-01-01T00:00:00Z",
        )
        result = self.connector.rollback(snapshot)
        self.assertEqual(result["status"], "not_applicable")
        self.assertIn("reason", result)

    def test_can_rollback_returns_false(self) -> None:
        """Manual review does not support rollback."""
        self.assertFalse(self.connector.can_rollback())

    def test_compensating_action_returns_none(self) -> None:
        """Manual review has no compensating action."""
        self.assertIsNone(self.connector.compensating_action())

    def test_connector_name_returns_manual_review(self) -> None:
        """connector_name property must return 'manual_review'."""
        self.assertEqual(self.connector.connector_name, "manual_review")


# ──────────────────────────────────────────────────────────────────────
# 6. TrustedLoopRuntime end-to-end integration tests
# ──────────────────────────────────────────────────────────────────────


def _build_runtime(
    rows: list[dict] | None = None,
    connector_registry: ActionConnectorRegistry | None = None,
) -> TrustedLoopRuntime:
    """Helper to build a TrustedLoopRuntime with sensible defaults."""
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value over paid orders.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql=(
            "select order_date, sum(paid_amount) as gmv "
            "from sales.orders "
            "where order_date >= :start_date and order_date < :end_date "
            "group by order_date "
            "limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    kwargs: dict = {
        "metric_contract": metric,
        "sql_template": template,
        "query_executor": StaticQueryExecutor(
            rows if rows is not None else [{"order_date": "2026-05-31", "gmv": 128800.0}]
        ),
        "semantic_registry": SemanticRegistry(metric_contracts=(metric,)),
        "provider_registry": ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales warehouse",
                    owner="revenue_ops",
                    allowed_schemas=("sales",),
                ),
            )
        ),
    }
    if connector_registry is not None:
        kwargs["connector_registry"] = connector_registry
    else:
        kwargs["connector_registry"] = _build_default_connector_registry()
    return TrustedLoopRuntime(**kwargs)


class TrustedLoopIntegrationTest(unittest.TestCase):
    """End-to-end integration tests for the Trusted Loop pipeline."""

    def test_normal_path_result_contains_operation_contract_and_action_result(self) -> None:
        """Normal execution path: result should contain operation_contract and action_result."""
        runtime = _build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # operation_contract must be populated
        self.assertIsNotNone(result.operation_contract)
        self.assertIsInstance(result.operation_contract, OperationContract)
        self.assertEqual(result.operation_contract.connector_name, "manual_review")

        # action_result must be populated and contain status
        self.assertIsNotNone(result.action_result)
        self.assertIsInstance(result.action_result, dict)
        self.assertIn("status", result.action_result)
        self.assertEqual(result.action_result["status"], "pending_approval")

    def test_high_risk_path_approval_pending(self) -> None:
        """High-risk (row_count=0) should create a pending approval record."""
        runtime = _build_runtime(rows=[])
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        self.assertTrue(result.action_proposal.approval_required)
        self.assertIsNotNone(result.approval_record)
        self.assertEqual(result.approval_record.status, "pending")

    def test_no_snapshot_path_for_manual_review(self) -> None:
        """Manual review connector does not support snapshots, so state_snapshot should be None."""
        runtime = _build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        # Manual review has supports_snapshot=False, so should_snapshot should be False
        # and state_snapshot should be None
        self.assertIsNone(result.state_snapshot)

    def test_trace_events_contain_governance_steps(self) -> None:
        """Trace events should include operation_contract and connector_execute steps."""
        runtime = _build_runtime()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )

        steps = [event.step for event in result.trace_events]
        self.assertIn("operation_contract", steps)
        self.assertIn("connector_execute", steps)

    def test_connector_registry_required_enforces_boundary(self) -> None:
        """TrustedLoopRuntime must reject None connector_registry to enforce boundary rule.

        OS Core must never import action connectors — the caller is responsible
        for constructing and injecting the registry.
        """
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )
        template = SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql=(
                "select order_date, sum(paid_amount) as gmv "
                "from sales.orders "
                "where order_date >= :start_date and order_date < :end_date "
                "group by order_date "
                "limit :limit"
            ),
            required_parameters=("start_date", "end_date", "limit"),
        )
        with self.assertRaises(ValueError) as ctx:
            TrustedLoopRuntime(
                metric_contract=metric,
                sql_template=template,
                query_executor=StaticQueryExecutor([{"gmv": 100}]),
            )
        self.assertIn("connector_registry is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
