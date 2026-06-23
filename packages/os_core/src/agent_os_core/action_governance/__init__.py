from __future__ import annotations

from agent_os_contracts import ActionProposal, OperationContract, RiskLevel

from ..action_connectors.registry import ActionConnectorRegistry


_RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4, "R5": 5}


class ActionGovernanceError(ValueError):
    """Base class for action-governance contract violations."""


class RiskCeilingExceeded(ActionGovernanceError):
    """Raised when a proposal exceeds the routed connector's risk ceiling."""


class UnsupportedActionType(ActionGovernanceError):
    """Raised when a proposal requests an action type the connector does not support."""


def _risk_value(risk: RiskLevel | str) -> str:
    return risk.value if isinstance(risk, RiskLevel) else risk


def _risk_order(risk: RiskLevel | str) -> int:
    value = _risk_value(risk)
    try:
        return _RISK_ORDER[value]
    except KeyError as exc:
        raise ActionGovernanceError(f"unknown risk level '{value}'") from exc


class ActionGovernance:
    """Determines governance rules for operation execution.

    Builds operation contracts from proposals, decides whether an operation
    can be auto-executed, and whether a pre-execution snapshot is needed.
    """

    def __init__(self, connector_registry: ActionConnectorRegistry | None = None) -> None:
        self._registry = connector_registry

    def build_operation_contract(self, proposal: ActionProposal) -> OperationContract:
        """Build an OperationContract from an ActionProposal.

        When a connector registry is available, the contract's
        ``snapshot_required``, ``rollback_supported``, and
        ``compensating_action`` fields are dynamically filled from the
        connector's declared contract.  The ``connector_name`` drives routing
        and ``target_connector`` is kept in sync (deprecated but retained for
        backward compatibility).

        Args:
            proposal: The action proposal to convert.

        Returns:
            A fully populated OperationContract.
        """
        high_risk = proposal.risk_level in (RiskLevel.R4, RiskLevel.R5)
        approval_required = proposal.approval_required or high_risk

        # Default values — may be overridden from connector contract
        snapshot_required: bool = False
        rollback_supported: bool = False
        compensating_action: str | None = None

        if self._registry is not None:
            try:
                connector_contract = self._registry.get_contract(proposal.connector_name)
                if proposal.action_type not in connector_contract.supported_action_types:
                    raise UnsupportedActionType(
                        f"unsupported action type '{proposal.action_type}' for connector "
                        f"'{proposal.connector_name}'"
                    )
                if _risk_order(proposal.risk_level) > _risk_order(connector_contract.risk_ceiling):
                    raise RiskCeilingExceeded(
                        "risk ceiling exceeded: "
                        f"proposal risk '{proposal.risk_level.value}' exceeds connector "
                        f"'{proposal.connector_name}' ceiling "
                        f"'{connector_contract.risk_ceiling}'"
                    )
                snapshot_required = connector_contract.supports_snapshot
                rollback_supported = connector_contract.supports_rollback
                compensating_action = connector_contract.compensating_action_description
            except KeyError:
                # Connector not registered — keep defaults
                pass

        return OperationContract(
            operation_id=f"operation-{proposal.proposal_id}",
            name=f"operation_for_{proposal.target_object}",
            target_connector=proposal.connector_name,
            risk_level=proposal.risk_level.value,
            approval_required=approval_required,
            dry_run_required=True,
            rollback_supported=rollback_supported,
            snapshot_required=snapshot_required,
            compensating_action=compensating_action,
            connector_name=proposal.connector_name,
            action_type=proposal.action_type,
            idempotency_key=proposal.idempotency_key,
        )

    def can_auto_execute(self, operation: OperationContract) -> bool:
        """Determine whether an operation can be executed automatically.

        An operation can be auto-executed when:
        - It does not require approval AND is low risk (R0 or R1).
        - Its connector_name exists in the registry.
        - Its action_type is among the connector's supported action types.

        Args:
            operation: The operation contract to evaluate.

        Returns:
            True if the operation can be auto-executed.
        """
        if operation.approval_required or operation.risk_level not in {"R0", "R1"}:
            return False

        if self._registry is not None:
            try:
                connector_contract = self._registry.get_contract(operation.connector_name)
                if operation.action_type not in connector_contract.supported_action_types:
                    return False
            except KeyError:
                return False

        return True

    def should_snapshot(self, operation: OperationContract) -> bool:
        """Determine whether a pre-execution snapshot is needed.

        A snapshot is required when the operation declares ``snapshot_required``
        AND the risk level is R2 or above.

        Args:
            operation: The operation contract to evaluate.

        Returns:
            True if a snapshot should be taken before execution.
        """
        return operation.snapshot_required and operation.risk_level not in {"R0", "R1"}
