from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from agent_os_contracts import OperationContract, StateSnapshot

from agent_os_core.action_connectors.base import ActionConnector


class ActionRecordStoreLike(Protocol):
    """Store interface required by the action_record connector."""

    def add(
        self,
        *,
        operation_id: str,
        action_type: str,
        parameters: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    def records(self) -> tuple[dict[str, Any], ...]: ...

    def snapshot_state(self) -> dict[str, Any]: ...

    def restore(self, state_payload: dict[str, Any]) -> None: ...


class ActionRecordStore:
    """Connector-side mutable state for the ActionRecord connector.

    Holds an ordered list of action records. This is the real side-effect
    target: ``execute`` appends to it, ``snapshot_state`` captures a deep copy,
    and ``restore`` replaces the live state with a captured copy. It lives in
    the connector package (NOT os_core) because it is connector-specific state.
    """

    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._idempotency: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    def add(
        self,
        *,
        operation_id: str,
        action_type: str,
        parameters: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Append a new record and return it (including its generated id)."""
        payload = {
            "operation_id": operation_id,
            "action_type": action_type,
            "parameters": copy.deepcopy(parameters),
        }
        if idempotency_key is not None and idempotency_key in self._idempotency:
            original_payload, original_record = self._idempotency[idempotency_key]
            if original_payload != payload:
                raise ValueError(
                    "idempotency_key was reused with a different operation/action payload"
                )
            replay = copy.deepcopy(original_record)
            replay["status"] = "idempotent_replay"
            return replay

        record = {
            "record_id": f"record-{uuid4().hex[:12]}",
            "operation_id": operation_id,
            "action_type": action_type,
            "parameters": copy.deepcopy(parameters),
        }
        if idempotency_key is not None:
            record["idempotency_key"] = idempotency_key
        self._records.append(record)
        if idempotency_key is not None:
            self._idempotency[idempotency_key] = (payload, copy.deepcopy(record))
        return copy.deepcopy(record)

    def records(self) -> tuple[dict[str, Any], ...]:
        """Return the live records as a tuple (the dicts themselves are live)."""
        return tuple(self._records)

    def snapshot_state(self) -> dict[str, Any]:
        """Capture a deep copy of the current state, restorable via ``restore``."""
        return {
            "records": copy.deepcopy(self._records),
            "idempotency": copy.deepcopy(self._idempotency),
        }

    def restore(self, state_payload: dict[str, Any]) -> None:
        """Replace the live state with a deep copy of ``state_payload``."""
        self._records = copy.deepcopy(list(state_payload.get("records", [])))
        self._idempotency = copy.deepcopy(dict(state_payload.get("idempotency", {})))


class ActionRecordConnector(ActionConnector):
    """First real WRITE connector: persists action records with reversible state.

    Backed by an injected :class:`ActionRecordStore`. ``execute`` performs a
    genuine mutation (appends a record); ``take_snapshot`` captures the store's
    state before execution; ``rollback`` restores that captured state. This is
    the connector that finally exercises the governance snapshot-before-execute
    and rollback machinery for real.
    """

    def __init__(self, *, store: ActionRecordStoreLike) -> None:
        self._store = store

    @property
    def store(self) -> ActionRecordStoreLike:
        """Return the backing store (exposed for inspection/testing)."""
        return self._store

    @property
    def connector_name(self) -> str:
        return "action_record"

    def take_snapshot(self, operation: OperationContract) -> StateSnapshot | None:
        """Capture the store's current state into a restorable StateSnapshot."""
        state_payload = self._store.snapshot_state()
        state_payload["rollback_operation_id"] = operation.operation_id
        return StateSnapshot(
            snapshot_id=f"snapshot-{uuid4().hex[:12]}",
            operation_id=operation.operation_id,
            connector_name=self.connector_name,
            snapshot_type="full",
            state_payload=state_payload,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def dry_run(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Preview the record that execute would append without mutating state."""
        return {
            "status": "dry_run",
            "connector_name": self.connector_name,
            "operation_id": operation.operation_id,
            "action_type": operation.action_type,
            "parameters": copy.deepcopy(parameters),
            "idempotency_key": operation.idempotency_key,
            "would_append": True,
        }

    def execute(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """Perform a REAL write: append a record to the store."""
        record = self._store.add(
            operation_id=operation.operation_id,
            action_type=operation.action_type,
            parameters=parameters,
            idempotency_key=operation.idempotency_key,
        )
        if record.get("status") == "idempotent_replay":
            return {
                "status": "idempotent_replay",
                "record_id": record["record_id"],
                "idempotency_key": operation.idempotency_key,
            }
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
