from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import ActionContract, ActionPermit, ActionReceipt


class CapabilityDenied(PermissionError):
    pass


class CapabilityEffectUnknown(CapabilityDenied):
    """A capability may have produced an effect that cannot be proven terminal."""

    def __init__(
        self,
        action: ActionContract,
        *,
        reason_code: str,
        detail: str,
        reservation_id: str | None = None,
    ) -> None:
        self.action = action
        self.action_id = action.action_id
        self.action_digest = action.action_digest()
        self.idempotency_key = action.idempotency_key
        self.reason_code = reason_code
        self.reservation_id = reservation_id
        super().__init__(
            f"UNKNOWN_REQUIRES_REVIEW [{reason_code}]: {detail}"
        )


@dataclass(frozen=True)
class CapabilityResult:
    receipt: ActionReceipt
    output: dict[str, object]
    permit: ActionPermit


class DurableActionOutcomeRepository:
    """Insert-only reservation/outcome codec over the shared durable store."""

    RESERVATION_SCOPE = "capability-reservation.v1"
    OUTCOME_SCOPE = "capability-outcome.v1"
    LEGACY_SCOPE = "capability"

    def __init__(self, store: object) -> None:
        self._store = store

    def replay(self, action: ActionContract) -> CapabilityResult | None:
        try:
            outcome = self._get_record(
                self.OUTCOME_SCOPE,
                action.idempotency_key,
            )
            reservation = self._get_record(
                self.RESERVATION_SCOPE,
                action.idempotency_key,
            )
            if outcome is not None:
                if reservation is None:
                    raise self.unknown(
                        action,
                        reason_code="OUTCOME_WITHOUT_RESERVATION",
                        detail="capability outcome lacks durable reservation",
                    )
                return self._load_outcome(action, reservation, outcome)
            if reservation is not None:
                self._validate_reservation(action, reservation)
                raise self.unknown(
                    action,
                    reason_code="RESERVATION_WITHOUT_OUTCOME",
                    detail=(
                        "capability dispatch was reserved but no terminal outcome "
                        "was sealed; automatic resend is forbidden"
                    ),
                    reservation=reservation,
                )
            legacy = self._get_record(
                self.LEGACY_SCOPE,
                action.idempotency_key,
            )
            if legacy is not None:
                raise self.unknown(
                    action,
                    reason_code="LEGACY_OUTCOME_WITHOUT_RECEIPT",
                    detail=(
                        "legacy capability result lacks an original durable "
                        "receipt; automatic replay is forbidden"
                    ),
                )
            return None
        except CapabilityEffectUnknown:
            raise
        except Exception as exc:
            raise self.unknown(
                action,
                reason_code="DURABLE_OUTCOME_CORRUPT",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc

    def reserve(
        self,
        action: ActionContract,
    ) -> dict[str, object] | CapabilityResult:
        now = datetime.now(timezone.utc)
        reservation = self._with_record_digest(
            {
                "schema_version": self.RESERVATION_SCOPE,
                "state": "RESERVED",
                "reservation_id": f"reservation-{uuid4()}",
                "receipt_id": f"receipt-{uuid4()}",
                "action_id": action.action_id,
                "action_digest": action.action_digest(),
                "idempotency_key": action.idempotency_key,
                "capability_id": action.capability_id,
                "intent_fingerprint": _intent_fingerprint(action),
                "reserved_at": now.isoformat(),
            }
        )
        try:
            inserted = self._put_record(
                self.RESERVATION_SCOPE,
                action.idempotency_key,
                reservation,
                now,
            )
        except Exception as exc:
            raise self.unknown(
                action,
                reason_code="RESERVATION_STORE_FAILED",
                detail=f"{type(exc).__name__}: {exc}",
            ) from exc
        if inserted:
            return reservation
        replayed = self.replay(action)
        if replayed is not None:
            return replayed
        raise self.unknown(
            action,
            reason_code="RESERVATION_CONFLICT",
            detail="capability reservation conflict",
        )

    def seal(
        self,
        action: ActionContract,
        reservation: dict[str, object],
        permit: ActionPermit,
        receipt: ActionReceipt,
        output: dict[str, object],
    ) -> CapabilityResult:
        now = datetime.now(timezone.utc)
        outcome = self._with_record_digest(
            {
                "schema_version": self.OUTCOME_SCOPE,
                "state": receipt.status.value,
                "reservation_id": reservation["reservation_id"],
                "action_id": action.action_id,
                "action_digest": action.action_digest(),
                "idempotency_key": action.idempotency_key,
                "capability_id": action.capability_id,
                "intent_fingerprint": _intent_fingerprint(action),
                "permit": permit.model_dump(mode="json"),
                "receipt": receipt.model_dump(mode="json"),
                "output": output,
                "sealed_at": now.isoformat(),
            }
        )
        try:
            inserted = self._put_record(
                self.OUTCOME_SCOPE,
                action.idempotency_key,
                outcome,
                now,
            )
            if inserted:
                return CapabilityResult(
                    receipt=receipt,
                    output=output,
                    permit=permit,
                )
            stored = self._get_record(
                self.OUTCOME_SCOPE,
                action.idempotency_key,
            )
            if stored is None:
                raise ValueError("capability outcome seal conflict")
            return self._load_outcome(action, reservation, stored)
        except CapabilityEffectUnknown:
            raise
        except Exception as exc:
            raise self.unknown(
                action,
                reason_code="OUTCOME_SEAL_FAILED",
                detail=f"{type(exc).__name__}: {exc}",
                reservation=reservation,
            ) from exc

    def canonical_output(self, output: dict[str, object]) -> dict[str, object]:
        decoded = json.loads(_canonical_json_bytes(output))
        if not isinstance(decoded, dict):
            raise TypeError("capability output must be a JSON object")
        return decoded

    def unknown(
        self,
        action: ActionContract,
        *,
        reason_code: str,
        detail: str,
        reservation: dict[str, object] | None = None,
    ) -> CapabilityEffectUnknown:
        reservation_id = (
            reservation.get("reservation_id")
            if isinstance(reservation, dict)
            else None
        )
        return CapabilityEffectUnknown(
            action,
            reason_code=reason_code,
            detail=detail,
            reservation_id=(
                reservation_id if isinstance(reservation_id, str) else None
            ),
        )

    def _load_outcome(
        self,
        action: ActionContract,
        reservation: dict[str, object],
        outcome: dict[str, object],
    ) -> CapabilityResult:
        self._validate_reservation(action, reservation)
        required = {
            "schema_version",
            "state",
            "reservation_id",
            "action_id",
            "action_digest",
            "idempotency_key",
            "capability_id",
            "intent_fingerprint",
            "permit",
            "receipt",
            "output",
            "sealed_at",
            "record_digest",
        }
        self._validate_record(outcome, required, self.OUTCOME_SCOPE)
        bindings = {
            "reservation_id": reservation["reservation_id"],
            "action_id": action.action_id,
            "action_digest": action.action_digest(),
            "idempotency_key": action.idempotency_key,
            "capability_id": action.capability_id,
            "intent_fingerprint": _intent_fingerprint(action),
        }
        if any(outcome.get(field) != value for field, value in bindings.items()):
            if outcome.get("intent_fingerprint") != bindings["intent_fingerprint"]:
                raise ValueError("idempotency key reused for a different action intent")
            raise ValueError("capability outcome/action binding mismatch")
        permit_value = outcome.get("permit")
        receipt_value = outcome.get("receipt")
        output_value = outcome.get("output")
        if not isinstance(permit_value, dict) or not isinstance(receipt_value, dict):
            raise TypeError("invalid capability outcome contracts")
        if not isinstance(output_value, dict):
            raise TypeError("invalid capability outcome output")
        permit = ActionPermit.model_validate(permit_value)
        receipt = ActionReceipt.model_validate(receipt_value)
        if not permit.matches(action):
            raise ValueError("stored capability permit/action mismatch")
        if (
            receipt.receipt_id != reservation["receipt_id"]
            or receipt.action_id != action.action_id
            or receipt.action_digest != action.action_digest()
            or receipt.permit_id != permit.permit_id
            or receipt.tenant_id != action.tenant_id
            or receipt.workspace_id != action.workspace_id
            or receipt.connector_id != action.capability_id
            or receipt.idempotency_key != action.idempotency_key
            or receipt.status.value != outcome["state"]
        ):
            raise ValueError("stored capability receipt/action mismatch")
        return CapabilityResult(
            receipt=receipt,
            output=self.canonical_output(output_value),
            permit=permit,
        )

    def _validate_reservation(
        self,
        action: ActionContract,
        reservation: dict[str, object],
    ) -> None:
        required = {
            "schema_version",
            "state",
            "reservation_id",
            "receipt_id",
            "action_id",
            "action_digest",
            "idempotency_key",
            "capability_id",
            "intent_fingerprint",
            "reserved_at",
            "record_digest",
        }
        self._validate_record(reservation, required, self.RESERVATION_SCOPE)
        if reservation.get("intent_fingerprint") != _intent_fingerprint(action):
            raise ValueError("idempotency key reused for a different action intent")
        expected = {
            "state": "RESERVED",
            "action_id": action.action_id,
            "action_digest": action.action_digest(),
            "idempotency_key": action.idempotency_key,
            "capability_id": action.capability_id,
        }
        if any(reservation.get(field) != value for field, value in expected.items()):
            raise ValueError("capability reservation/action binding mismatch")
        if not all(
            isinstance(reservation.get(field), str) and reservation[field]
            for field in ("reservation_id", "receipt_id", "reserved_at")
        ):
            raise TypeError("invalid capability reservation identity")

    @staticmethod
    def _with_record_digest(record: dict[str, object]) -> dict[str, object]:
        return {
            **record,
            "record_digest": _sha256(_canonical_json_bytes(record)),
        }

    @staticmethod
    def _validate_record(
        record: dict[str, object],
        required: set[str],
        schema_version: str,
    ) -> None:
        if set(record) != required or record.get("schema_version") != schema_version:
            raise ValueError("invalid durable capability record fields")
        claimed = record.get("record_digest")
        without_digest = {
            key: value for key, value in record.items() if key != "record_digest"
        }
        if not isinstance(claimed, str) or claimed != _sha256(
            _canonical_json_bytes(without_digest)
        ):
            raise ValueError("durable capability record digest mismatch")

    def _get_record(self, scope: str, key: str) -> dict[str, object] | None:
        getter = getattr(self._store, "get_idempotency", None)
        if getter is None:
            raise TypeError("durable idempotency store is not readable")
        stored: Any = getter(scope, key)
        if stored is None:
            return None
        if not isinstance(stored, dict):
            raise TypeError("invalid durable capability record")
        return stored

    def _put_record(
        self,
        scope: str,
        key: str,
        record: dict[str, object],
        created_at: datetime,
    ) -> bool:
        setter = getattr(self._store, "put_idempotency", None)
        if setter is None:
            raise TypeError("durable idempotency store is not writable")
        return bool(setter(scope, key, record, created_at.isoformat()))


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _intent_fingerprint(action: ActionContract) -> str:
    return _sha256(
        _canonical_json_bytes(
            {
                "tenant_id": action.tenant_id,
                "workspace_id": action.workspace_id,
                "principal_id": action.principal_id,
                "run_id": action.run_id,
                "node_id": action.node_id,
                "capability_id": action.capability_id,
                "capability_version": action.capability_version,
                "arguments_json": action.arguments_json,
                "policy_version": action.policy_version,
                "expected_outcome_id": action.expected_outcome_id,
            }
        )
    )
