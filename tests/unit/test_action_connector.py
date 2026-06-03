from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import ActionConnectorContract, OperationContract  # noqa: E402

from agent_os_core.action_connectors import (  # noqa: E402
    ActionConnector,
    ActionConnectorRegistry,
)


class _StubConnector(ActionConnector):
    """Minimal concrete connector for testing the ABC and registry."""

    @property
    def connector_name(self) -> str:
        return "stub"

    def take_snapshot(self, operation: OperationContract):
        return None

    def execute(self, operation: OperationContract, parameters: dict) -> dict:
        return {"status": "executed"}

    def rollback(self, snapshot) -> dict:
        return {"status": "rolled_back"}

    def can_rollback(self) -> bool:
        return True

    def compensating_action(self) -> str | None:
        return "undo_stub"


_STUB_CONTRACT = ActionConnectorContract(
    connector_name="stub",
    display_name="Stub Connector",
    supported_action_types=("propose", "execute"),
    supports_snapshot=False,
    supports_rollback=True,
    compensating_action_description="undo_stub",
    risk_ceiling="R3",
    owner="test",
)


class ActionConnectorABCTest(unittest.TestCase):
    def test_cannot_instantiate_abc_directly(self) -> None:
        with self.assertRaises(TypeError):
            ActionConnector()  # type: ignore[abstract]

    def test_stub_connector_implements_all_methods(self) -> None:
        connector = _StubConnector()
        self.assertEqual(connector.connector_name, "stub")
        self.assertIsNone(
            connector.take_snapshot(
                OperationContract(
                    operation_id="op-1",
                    name="test",
                    target_connector="stub",
                    risk_level="R2",
                    approval_required=False,
                )
            )
        )
        result = connector.execute(
            OperationContract(
                operation_id="op-1",
                name="test",
                target_connector="stub",
                risk_level="R2",
                approval_required=False,
            ),
            {},
        )
        self.assertEqual(result["status"], "executed")
        self.assertTrue(connector.can_rollback())
        self.assertEqual(connector.compensating_action(), "undo_stub")


class ActionConnectorRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ActionConnectorRegistry()
        self.connector = _StubConnector()
        self.registry.register(self.connector, _STUB_CONTRACT)

    def test_register_and_get(self) -> None:
        retrieved = self.registry.get("stub")
        self.assertIs(retrieved, self.connector)

    def test_get_contract(self) -> None:
        contract = self.registry.get_contract("stub")
        self.assertEqual(contract.connector_name, "stub")
        self.assertEqual(contract.display_name, "Stub Connector")

    def test_list_connectors(self) -> None:
        contracts = self.registry.list_connectors()
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0].connector_name, "stub")

    def test_get_nonexistent_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            self.registry.get("nonexistent")

    def test_get_contract_nonexistent_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            self.registry.get_contract("nonexistent")

    def test_register_name_mismatch_raises_valueerror(self) -> None:
        mismatched_contract = ActionConnectorContract(
            connector_name="wrong_name",
            display_name="Wrong",
            supported_action_types=("propose",),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R0",
            owner="test",
        )
        with self.assertRaises(ValueError):
            self.registry.register(self.connector, mismatched_contract)

    def test_reregister_overwrites(self) -> None:
        new_contract = ActionConnectorContract(
            connector_name="stub",
            display_name="Updated Stub",
            supported_action_types=("propose",),
            supports_snapshot=True,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R1",
            owner="test_updated",
        )
        self.registry.register(self.connector, new_contract)
        contract = self.registry.get_contract("stub")
        self.assertEqual(contract.display_name, "Updated Stub")
        self.assertTrue(contract.supports_snapshot)

    def test_multiple_connectors(self) -> None:
        class _OtherConnector(ActionConnector):
            @property
            def connector_name(self) -> str:
                return "other"

            def take_snapshot(self, operation):
                return None

            def execute(self, operation, parameters):
                return {"status": "ok"}

            def rollback(self, snapshot):
                return {"status": "ok"}

            def can_rollback(self) -> bool:
                return False

            def compensating_action(self) -> str | None:
                return None

        other = _OtherConnector()
        other_contract = ActionConnectorContract(
            connector_name="other",
            display_name="Other Connector",
            supported_action_types=("propose",),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R5",
            owner="test",
        )
        self.registry.register(other, other_contract)
        self.assertEqual(len(self.registry.list_connectors()), 2)
        self.assertIs(self.registry.get("other"), other)


if __name__ == "__main__":
    unittest.main()
