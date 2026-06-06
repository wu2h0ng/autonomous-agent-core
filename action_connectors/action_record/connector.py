from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import OperationContract, StateSnapshot

from agent_os_core.action_connectors.base import ActionConnector


class ActionRecordStore:
    """Connector-side mutable state for the ActionRecord connector.

    Holds an ordered list of action records. This is the real side-effect
    target: ``execute`` appends to it, ``snapshot_state`` captures a deep copy,
    and ``restore`` replaces the live state with a captured copy. It lives in
    the connector package (NOT os_core) because it is connector-specific state.
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def add(
        self, *, operation_id: str, action_type: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Append a new record and return it (including its generated id)."""
        record = {
            "record_id": f"record-{uuid4().hex[:12]}",
            "operation_id": operation_id,
            "action_type": action_type,
            "parameters": copy.deepcopy(parameters),
        }
        self._records.append(record)
        return copy.deepcopy(record)

    def records(self) -> tuple[dict[str, Any], ...]:
        """Return the live records as a tuple (the dicts themselves are live)."""
        return tuple(self._records)

    def snapshot_state(self) -> dict[str, Any]:
        """Capture a deep copy of the current state, restorable via ``restore``."""
        return {"records": copy.deepcopy(self._records)}

    def restore(self, state_payload: dict[str, Any]) -> None:
        """Replace the live state with a deep copy of ``state_payload``."""
        self._records = copy.deepcopy(list(state_payload.get("records", [])))


class ActionRecordConnector(ActionConnector):
    """First real WRITE connector: persists action records with reversible state.

    Backed by an injected :class:`ActionRecordStore`. ``execute`` performs a
    genuine mutation (appends a record); ``take_snapshot`` captures the store's
    state before execution; ``rollback`` restores that captured state. This is
    the connector that finally exercises the governance snapshot-before-execute
    and rollback machinery for real.
    """

    def __init__(self, *, store: ActionRecordStore) -> None:
        self._store = store

    @property
    def store(self) -> ActionRecordStore:
        """Return the backing store (exposed for inspection/testing)."""
        return self._store

    @property
    def connector_name(self) -> str:
        return "action_record"

    def take_snapshot(self, operation: OperationContract) -> StateSnapshot | None:
        """Capture the store's current state into a restorable StateSnapshot."""
        return StateSnapshot(
            snapshot_id=f"snapshot-{uuid4().hex[:12]}",
            operation_id=operation.operation_id,
            connector_name=self.connector_name,
            snapshot_type="full",
            state_payload=self._store.snapshot_state(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def execute(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Perform a REAL write: append a record to the store."""
        record = self._store.add(
            operation_id=operation.operation_id,
            action_type=operation.action_type,
            parameters=parameters,
        )
        return {"status": "executed", "record_id": record["record_id"]}

    def rollback(self, snapshot: StateSnapshot) -> dict[str, Any]:
        """Restore the store to the state captured in ``snapshot``."""
        self._store.restore(snapshot.state_payload)
        return {
            "status": "rolled_back",
            "snapshot_id": snapshot.snapshot_id,
            "operation_id": snapshot.operation_id,
            "record_count": len(self._store.records()),
        }

    def can_rollback(self) -> bool:
        return True

    def compensating_action(self) -> str | None:
        return "Restore the action record store to the pre-execution snapshot state"
