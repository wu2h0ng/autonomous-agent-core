from __future__ import annotations

from ..domain_contracts import ActionConnectorContract, ConnectorExecutionSemantics

from .base import ActionConnector


class ActionConnectorRegistry:
    """Registry that maps connector names to ActionConnector instances and their contracts.

    Connectors are registered via ``register()`` and looked up by name via ``get()``.
    The registry does not import concrete connector implementations — they are
    injected at runtime, keeping os_core decoupled from external connector packages.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, ActionConnector] = {}
        self._contracts: dict[str, ActionConnectorContract] = {}

    def register(
        self,
        connector: ActionConnector,
        contract: ActionConnectorContract,
    ) -> None:
        """Register a connector together with its contract.

        Validates that ``connector.connector_name`` matches ``contract.connector_name``.
        Re-registering the same name overwrites the previous entry.

        Args:
            connector: The connector instance to register.
            contract: The contract describing the connector's capabilities.

        Raises:
            ValueError: If the connector name and contract name do not match.
        """
        if connector.connector_name != contract.connector_name:
            raise ValueError(
                f"Connector name '{connector.connector_name}' does not match "
                f"contract name '{contract.connector_name}'"
            )
        self._connectors[connector.connector_name] = connector
        self._contracts[contract.connector_name] = contract

    def get(self, connector_name: str) -> ActionConnector:
        """Retrieve a connector by name.

        Args:
            connector_name: The unique name of the connector.

        Returns:
            The registered ActionConnector instance.

        Raises:
            KeyError: If no connector with the given name is registered.
        """
        if connector_name not in self._connectors:
            raise KeyError(
                f"No connector registered with name '{connector_name}'. "
                f"Available: {list(self._connectors.keys())}"
            )
        return self._connectors[connector_name]

    def get_contract(self, connector_name: str) -> ActionConnectorContract:
        """Retrieve a connector's contract by name.

        Args:
            connector_name: The unique name of the connector.

        Returns:
            The registered ActionConnectorContract.

        Raises:
            KeyError: If no contract with the given name is registered.
        """
        if connector_name not in self._contracts:
            raise KeyError(
                f"No contract registered with name '{connector_name}'. "
                f"Available: {list(self._contracts.keys())}"
            )
        return self._contracts[connector_name]

    def get_execution_semantics(self, connector_name: str) -> ConnectorExecutionSemantics:
        """Retrieve a connector's declared execution-audit semantics."""
        return self.get_contract(connector_name).execution_semantics

    def list_connectors(self) -> tuple[ActionConnectorContract, ...]:
        """List all registered connector contracts.

        Returns:
            A tuple of all registered ActionConnectorContract instances.
        """
        return tuple(self._contracts.values())
