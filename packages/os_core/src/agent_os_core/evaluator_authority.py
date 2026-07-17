from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from agent_os_contracts import (
    EvaluationArtifactRole,
    EvaluationConsumptionEntry,
    EvaluationFailureCode,
    EvaluationReceipt,
    EvaluationScore,
    EvaluatorInput,
    EvaluatorMeasurementCandidate,
    EvaluatorRegistration,
    FailureReason,
    Uncertainty,
    canonical_json,
    content_digest,
)


class EvaluatorAuthorityError(RuntimeError):
    pass


class EvaluationAuthorityDenied(EvaluatorAuthorityError):
    pass


class EvaluationBindingDrift(EvaluatorAuthorityError):
    pass


class EvaluationInProgress(EvaluatorAuthorityError):
    pass


class EvaluatorBackendUnavailable(EvaluatorAuthorityError):
    pass


class EvaluatorBackendTimeout(EvaluatorBackendUnavailable):
    pass


class EvaluatorBackendMalformed(EvaluatorAuthorityError):
    pass


@dataclass(frozen=True)
class VerifiedEvaluatorInputs:
    config_bytes: bytes
    rubric_bytes: bytes
    prompt_bytes: bytes
    checkpoint_bytes: bytes
    hidden_set_bytes: bytes
    evidence_payloads: tuple[bytes, ...]
    consumption_manifest: tuple[EvaluationConsumptionEntry, ...]


class EvaluatorAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    adapter_binding_digest: str

    def evaluate_candidate(
        self,
        request: EvaluatorInput,
        registration: EvaluatorRegistration,
        inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate: ...


ExternalEvaluatorCall = Callable[
    [EvaluatorInput, EvaluatorRegistration, VerifiedEvaluatorInputs],
    EvaluatorMeasurementCandidate,
]
ArtifactReader = Callable[[str], bytes | None]


class TrustedEvaluatorRegistrationRegistry:
    """Canonical startup custody for evaluator authority registrations."""

    def __init__(self, registrations: Mapping[str, EvaluatorRegistration]) -> None:
        self._snapshots: dict[str, bytes] = {}
        for supplied_id, registration in registrations.items():
            if supplied_id != registration.registration_id:
                raise ValueError(
                    "registration mapping key does not match registration_id"
                )
            snapshot = canonical_json(registration).encode("utf-8")
            canonical = EvaluatorRegistration.model_validate_json(snapshot, strict=True)
            if canonical_json(canonical).encode("utf-8") != snapshot:
                raise ValueError("registration is not canonical")
            if supplied_id in self._snapshots:
                raise ValueError("duplicate evaluator registration")
            self._snapshots[supplied_id] = snapshot

    def resolve(self, registration_id: str, version: str) -> EvaluatorRegistration:
        snapshot = self._snapshots.get(registration_id)
        if snapshot is None:
            raise EvaluationAuthorityDenied("trusted evaluator registration is missing")
        registration = EvaluatorRegistration.model_validate_json(snapshot, strict=True)
        if canonical_json(registration).encode("utf-8") != snapshot:
            raise EvaluationAuthorityDenied("trusted evaluator registration is corrupt")
        if registration.registration_version != version:
            raise EvaluationAuthorityDenied(
                "requested evaluator registration version is not trusted"
            )
        return registration


class ExternalEvaluatorAdapter:
    """External backend receives verified role-separated inputs, never authority."""

    def __init__(
        self,
        backend: ExternalEvaluatorCall,
        *,
        adapter_id: str,
        adapter_version: str,
        adapter_binding_digest: str,
    ) -> None:
        self._backend = backend
        self.adapter_id = adapter_id
        self.adapter_version = adapter_version
        self.adapter_binding_digest = adapter_binding_digest

    def evaluate_candidate(
        self,
        request: EvaluatorInput,
        registration: EvaluatorRegistration,
        inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        try:
            candidate = self._backend(request, registration, inputs)
        except TimeoutError as exc:
            raise EvaluatorBackendTimeout("evaluator backend timed out") from exc
        if not isinstance(candidate, EvaluatorMeasurementCandidate):
            raise EvaluatorBackendMalformed(
                "external evaluator must return an unsealed measurement candidate"
            )
        return candidate


class DeterministicEvaluatorAdapter:
    """Local reference that consumes frozen rubric, hidden set, and evidence."""

    adapter_id = "deterministic-json"
    adapter_version = "2"
    adapter_binding_digest = hashlib.sha256(b"deterministic-json:2").hexdigest()

    @staticmethod
    def _object(raw: bytes, label: str) -> dict[str, object]:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvaluatorBackendMalformed(f"{label} is malformed") from exc
        if not isinstance(value, dict):
            raise EvaluatorBackendMalformed(f"{label} must be an object")
        return value

    def evaluate_candidate(
        self,
        request: EvaluatorInput,
        registration: EvaluatorRegistration,
        inputs: VerifiedEvaluatorInputs,
    ) -> EvaluatorMeasurementCandidate:
        config = self._object(inputs.config_bytes, "evaluator config")
        rubric = self._object(inputs.rubric_bytes, "rubric")
        hidden = self._object(inputs.hidden_set_bytes, "hidden set")
        if config.get("score") != "pass_rate":
            raise EvaluatorBackendMalformed("unsupported deterministic config")
        if rubric.get("metric") != "passed_over_total":
            raise EvaluatorBackendMalformed("unsupported deterministic rubric")
        minimum_passed = hidden.get("minimum_passed")
        if isinstance(minimum_passed, bool) or not isinstance(minimum_passed, int):
            raise EvaluatorBackendMalformed("hidden set minimum_passed is invalid")
        if minimum_passed <= 0 or len(inputs.evidence_payloads) != 1:
            raise EvaluatorBackendMalformed("deterministic inputs are unsupported")
        report = self._object(inputs.evidence_payloads[0], "evidence report")
        passed = report.get("passed")
        failed = report.get("failed")
        if (
            isinstance(passed, bool)
            or isinstance(failed, bool)
            or not isinstance(passed, int)
            or not isinstance(failed, int)
            or passed < 0
            or failed < 0
            or passed + failed <= 0
        ):
            raise EvaluatorBackendMalformed(
                "evidence report requires non-negative passed/failed counts"
            )
        score_value = min(passed / (passed + failed), passed / minimum_passed)
        failures: tuple[FailureReason, ...] = ()
        if failed or passed < minimum_passed:
            failures = (
                FailureReason(
                    code=EvaluationFailureCode.CRITERIA_NOT_MET,
                    message="one or more deterministic criteria were not met",
                    retriable=False,
                ),
            )
        trace_digest = content_digest(
            {
                "input_digest": request.canonical_digest(),
                "registration_digest": registration.canonical_digest(),
                "minimum_passed": minimum_passed,
                "passed": passed,
                "failed": failed,
                "score": score_value,
                "consumption_manifest": inputs.consumption_manifest,
            }
        )
        return EvaluatorMeasurementCandidate(
            input_digest=request.canonical_digest(),
            registration_digest=registration.canonical_digest(),
            score=EvaluationScore(
                value=score_value,
                scale_min=0.0,
                scale_max=1.0,
            ),
            uncertainty=Uncertainty(confidence=1.0, reasons=()),
            failure_reasons=failures,
            consumption_manifest=inputs.consumption_manifest,
            trace_digest=trace_digest,
        )


@dataclass(frozen=True)
class _Reservation:
    evaluation_id: str
    sequence: int
    input_digest: str
    registration_digest: str
    token: str | None = None
    existing_receipt: EvaluationReceipt | None = None


class EvaluationReceiptStore:
    """Local process-isolated SQLite custody with a sealed-writer HMAC namespace."""

    def __init__(
        self,
        path: str | Path,
        *,
        writer_namespace: str,
        seal_key: bytes,
        clock: Callable[[], datetime] | None = None,
        reservation_timeout_seconds: int = 300,
    ) -> None:
        if not writer_namespace.strip():
            raise ValueError("writer_namespace is required")
        if len(seal_key) < 16:
            raise ValueError("seal_key must contain at least 16 bytes")
        if reservation_timeout_seconds < 1:
            raise ValueError("reservation timeout must be positive")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._writer_namespace = writer_namespace
        self._seal_key = bytes(seal_key)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._reservation_timeout = timedelta(seconds=reservation_timeout_seconds)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        key_digest = hashlib.sha256(self._seal_key).hexdigest()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluator_store_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    writer_namespace TEXT NOT NULL,
                    seal_key_digest TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_receipts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    evaluation_id TEXT NOT NULL UNIQUE,
                    input_digest TEXT NOT NULL,
                    registration_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reservation_token TEXT,
                    reservation_expires_at TEXT,
                    receipt_bytes BLOB,
                    store_seal TEXT
                )
                """
            )
            row = connection.execute(
                "SELECT writer_namespace, seal_key_digest "
                "FROM evaluator_store_meta WHERE singleton = 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO evaluator_store_meta "
                    "(singleton, writer_namespace, seal_key_digest) VALUES (1, ?, ?)",
                    (self._writer_namespace, key_digest),
                )
            elif (
                row["writer_namespace"] != self._writer_namespace
                or row["seal_key_digest"] != key_digest
            ):
                raise EvaluationAuthorityDenied(
                    "receipt store writer namespace or seal key does not match"
                )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("store clock must be timezone aware")
        return value.astimezone(timezone.utc)

    def _seal(self, receipt_digest: str, evaluation_id: str, sequence: int) -> str:
        material = canonical_json(
            {
                "writer_namespace": self._writer_namespace,
                "evaluation_id": evaluation_id,
                "sequence": sequence,
                "receipt_digest": receipt_digest,
            }
        ).encode("utf-8")
        return hmac.new(self._seal_key, material, hashlib.sha256).hexdigest()

    def _decode_receipt(
        self,
        raw: bytes,
        expected_seal: str,
    ) -> EvaluationReceipt:
        try:
            receipt = EvaluationReceipt.model_validate_json(raw, strict=True)
        except (TypeError, ValueError) as exc:
            raise EvaluationAuthorityDenied("stored receipt bytes are invalid") from exc
        if canonical_json(receipt).encode("utf-8") != raw:
            raise EvaluationAuthorityDenied("stored receipt bytes are not canonical")
        if receipt.store_namespace != self._writer_namespace:
            raise EvaluationAuthorityDenied(
                "stored receipt writer namespace mismatches"
            )
        computed_seal = self._seal(
            receipt.receipt_digest,
            receipt.evaluation_id,
            receipt.store_sequence,
        )
        if not hmac.compare_digest(expected_seal, computed_seal):
            raise EvaluationAuthorityDenied("stored receipt seal is invalid")
        if not hmac.compare_digest(receipt.store_seal, computed_seal):
            raise EvaluationAuthorityDenied("receipt seal does not match trusted store")
        return receipt

    def reserve(
        self,
        evaluation_id: str,
        input_digest: str,
        registration_digest: str,
    ) -> _Reservation:
        now = self._as_utc(self._clock())
        token = str(uuid4())
        expires = now + self._reservation_timeout
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM evaluation_receipts WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO evaluation_receipts (
                        evaluation_id, input_digest, registration_digest, status,
                        reservation_token, reservation_expires_at
                    ) VALUES (?, ?, ?, 'PENDING', ?, ?)
                    """,
                    (
                        evaluation_id,
                        input_digest,
                        registration_digest,
                        token,
                        expires.isoformat(),
                    ),
                )
                if cursor.lastrowid is None:
                    raise EvaluationAuthorityDenied(
                        "receipt store did not assign a durable sequence"
                    )
                sequence = int(cursor.lastrowid)
                connection.commit()
                return _Reservation(
                    evaluation_id,
                    sequence,
                    input_digest,
                    registration_digest,
                    token=token,
                )
            if (
                row["input_digest"] != input_digest
                or row["registration_digest"] != registration_digest
            ):
                raise EvaluationBindingDrift(
                    "evaluation_id is durably bound to different input or registration"
                )
            if row["status"] == "SEALED":
                raw = row["receipt_bytes"]
                seal = row["store_seal"]
                if not isinstance(raw, bytes) or not isinstance(seal, str):
                    raise EvaluationAuthorityDenied("sealed receipt row is incomplete")
                receipt = self._decode_receipt(raw, seal)
                connection.commit()
                return _Reservation(
                    evaluation_id,
                    int(row["sequence"]),
                    input_digest,
                    registration_digest,
                    existing_receipt=receipt,
                )
            if row["status"] == "PENDING":
                expires_at = datetime.fromisoformat(str(row["reservation_expires_at"]))
                if self._as_utc(expires_at) > now:
                    raise EvaluationInProgress(
                        "evaluation already has an active reservation"
                    )
            connection.execute(
                """
                UPDATE evaluation_receipts
                SET status = 'PENDING', reservation_token = ?,
                    reservation_expires_at = ?, receipt_bytes = NULL, store_seal = NULL
                WHERE evaluation_id = ?
                """,
                (token, expires.isoformat(), evaluation_id),
            )
            connection.commit()
            return _Reservation(
                evaluation_id,
                int(row["sequence"]),
                input_digest,
                registration_digest,
                token=token,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail(self, reservation: _Reservation) -> None:
        if reservation.token is None:
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE evaluation_receipts
                SET status = 'FAILED', reservation_token = NULL,
                    reservation_expires_at = NULL
                WHERE evaluation_id = ? AND status = 'PENDING'
                    AND reservation_token = ?
                """,
                (reservation.evaluation_id, reservation.token),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise EvaluationBindingDrift("evaluation reservation was replaced")
            connection.commit()

    def finalize(
        self,
        reservation: _Reservation,
        unsigned_payload: Mapping[str, object],
    ) -> EvaluationReceipt:
        if reservation.token is None:
            raise EvaluationBindingDrift("cannot finalize without reservation custody")
        payload = dict(unsigned_payload)
        payload.update(
            {
                "schema_version": "1.0",
                "receipt_id": (
                    f"receipt:{self._writer_namespace}:{reservation.sequence}"
                ),
                "store_namespace": self._writer_namespace,
                "store_sequence": reservation.sequence,
            }
        )
        receipt_digest = content_digest(payload)
        store_seal = self._seal(
            receipt_digest,
            reservation.evaluation_id,
            reservation.sequence,
        )
        receipt = EvaluationReceipt.model_validate(
            {
                **payload,
                "receipt_digest": receipt_digest,
                "store_seal": store_seal,
            }
        )
        raw = canonical_json(receipt).encode("utf-8")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM evaluation_receipts WHERE evaluation_id = ?",
                (reservation.evaluation_id,),
            ).fetchone()
            if row is None:
                raise EvaluationBindingDrift("evaluation reservation is missing")
            if (
                row["status"] != "PENDING"
                or row["reservation_token"] != reservation.token
                or row["input_digest"] != reservation.input_digest
                or row["registration_digest"] != reservation.registration_digest
            ):
                raise EvaluationBindingDrift("evaluation reservation binding changed")
            cursor = connection.execute(
                """
                UPDATE evaluation_receipts
                SET status = 'SEALED', receipt_bytes = ?, store_seal = ?,
                    reservation_token = NULL, reservation_expires_at = NULL
                WHERE evaluation_id = ? AND status = 'PENDING'
                    AND reservation_token = ?
                """,
                (raw, store_seal, reservation.evaluation_id, reservation.token),
            )
            if cursor.rowcount != 1:
                raise EvaluationBindingDrift(
                    "evaluation finalize compare-and-set failed"
                )
            connection.commit()
            return self._decode_receipt(raw, store_seal)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, evaluation_id: str) -> EvaluationReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT receipt_bytes, store_seal, status "
                "FROM evaluation_receipts WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
        if row is None or row["status"] != "SEALED":
            return None
        raw = row["receipt_bytes"]
        seal = row["store_seal"]
        if not isinstance(raw, bytes) or not isinstance(seal, str):
            raise EvaluationAuthorityDenied("sealed receipt row is incomplete")
        return self._decode_receipt(raw, seal)

    def receipt_bytes(self, evaluation_id: str) -> bytes:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT receipt_bytes, status FROM evaluation_receipts "
                "WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
        if row is None or row["status"] != "SEALED":
            raise EvaluationAuthorityDenied("sealed receipt is unavailable")
        raw = row["receipt_bytes"]
        if not isinstance(raw, bytes):
            raise EvaluationAuthorityDenied("sealed receipt bytes are missing")
        return bytes(raw)

    def verify(self, receipt: EvaluationReceipt) -> bool:
        try:
            canonical = self.get(receipt.evaluation_id)
        except EvaluationAuthorityDenied:
            return False
        return canonical is not None and hmac.compare_digest(
            canonical_json(canonical).encode("utf-8"),
            canonical_json(receipt).encode("utf-8"),
        )


class EvaluatorRegistry:
    """Seals evaluator measurements without acquiring Outcome authority."""

    def __init__(
        self,
        *,
        registrations: TrustedEvaluatorRegistrationRegistry,
        adapters: Mapping[str, EvaluatorAdapter],
        artifact_reader: ArtifactReader,
        receipt_store: EvaluationReceiptStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registrations = registrations
        self._adapters = dict(adapters)
        self._artifact_reader = artifact_reader
        self._receipt_store = receipt_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _sha256(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def _read_bound_artifact(self, ref: str, expected_digest: str, label: str) -> bytes:
        raw = self._artifact_reader(ref)
        if raw is None:
            raise EvaluationAuthorityDenied(f"{label} artifact is unavailable")
        if self._sha256(raw) != expected_digest:
            raise EvaluationAuthorityDenied(f"{label} bytes do not match registration")
        return raw

    def _verified_inputs(
        self,
        registration: EvaluatorRegistration,
    ) -> VerifiedEvaluatorInputs:
        identity = registration.identity
        bindings = (
            (
                EvaluationArtifactRole.CONFIG,
                identity.config_artifact_ref,
                identity.config_digest,
                "config",
            ),
            (
                EvaluationArtifactRole.RUBRIC,
                registration.rubric.artifact_ref,
                registration.rubric.rubric_digest,
                "rubric",
            ),
            (
                EvaluationArtifactRole.PROMPT,
                identity.prompt_artifact_ref,
                identity.prompt_digest,
                "prompt",
            ),
            (
                EvaluationArtifactRole.CHECKPOINT,
                identity.checkpoint_artifact_ref,
                identity.checkpoint_digest,
                "checkpoint",
            ),
            (
                EvaluationArtifactRole.HIDDEN_SET,
                registration.hidden_set.artifact_ref,
                registration.hidden_set.content_digest,
                "hidden set",
            ),
        )
        resolved = {
            role: self._read_bound_artifact(ref, digest, label)
            for role, ref, digest, label in bindings
        }
        consumption = [
            EvaluationConsumptionEntry(
                role=role,
                artifact_ref=ref,
                content_digest=digest,
            )
            for role, ref, digest, _label in bindings
        ]
        evidence_payloads: list[bytes] = []
        for entry in registration.evidence.entries:
            evidence_payloads.append(
                self._read_bound_artifact(
                    entry.evidence_ref,
                    entry.content_digest,
                    "evidence",
                )
            )
            consumption.append(
                EvaluationConsumptionEntry(
                    role=EvaluationArtifactRole.EVIDENCE,
                    artifact_ref=entry.evidence_ref,
                    content_digest=entry.content_digest,
                )
            )
        manifest = tuple(
            sorted(
                consumption,
                key=lambda item: (item.role.value, item.artifact_ref),
            )
        )
        return VerifiedEvaluatorInputs(
            config_bytes=resolved[EvaluationArtifactRole.CONFIG],
            rubric_bytes=resolved[EvaluationArtifactRole.RUBRIC],
            prompt_bytes=resolved[EvaluationArtifactRole.PROMPT],
            checkpoint_bytes=resolved[EvaluationArtifactRole.CHECKPOINT],
            hidden_set_bytes=resolved[EvaluationArtifactRole.HIDDEN_SET],
            evidence_payloads=tuple(evidence_payloads),
            consumption_manifest=manifest,
        )

    @staticmethod
    def _validate_adapter_binding(
        adapter: EvaluatorAdapter,
        registration: EvaluatorRegistration,
    ) -> None:
        if (
            adapter.adapter_id != registration.adapter_id
            or adapter.adapter_version != registration.adapter_version
            or adapter.adapter_binding_digest != registration.adapter_binding_digest
        ):
            raise EvaluationAuthorityDenied(
                "adapter binding does not match trusted registration"
            )

    def evaluate(self, request: EvaluatorInput) -> EvaluationReceipt:
        registration = self._registrations.resolve(
            request.registration_id,
            request.registration_version,
        )
        if request.proposer_principal_id in {
            registration.registry_writer_principal_id,
            registration.identity.principal_id,
        }:
            raise EvaluationAuthorityDenied(
                "proposer, registry writer, and evaluator must be separate"
            )
        adapter = self._adapters.get(registration.adapter_id)
        if adapter is None:
            raise EvaluatorBackendUnavailable("exact registered adapter is unavailable")
        self._validate_adapter_binding(adapter, registration)
        verified_inputs = self._verified_inputs(registration)
        input_digest = request.canonical_digest()
        registration_digest = registration.canonical_digest()
        reservation = self._receipt_store.reserve(
            request.evaluation_id,
            input_digest,
            registration_digest,
        )
        if reservation.existing_receipt is not None:
            return reservation.existing_receipt
        try:
            candidate = adapter.evaluate_candidate(
                request,
                registration,
                verified_inputs,
            )
            try:
                current_registration = self._registrations.resolve(
                    request.registration_id,
                    request.registration_version,
                )
                current_inputs = self._verified_inputs(current_registration)
            except EvaluationAuthorityDenied as exc:
                raise EvaluationBindingDrift(
                    "trusted registration or artifacts changed during evaluation"
                ) from exc
            if (
                current_registration.canonical_digest() != registration_digest
                or current_inputs != verified_inputs
            ):
                raise EvaluationBindingDrift(
                    "trusted registration or artifacts changed during evaluation"
                )
            if candidate.input_digest != input_digest:
                raise EvaluatorBackendMalformed(
                    "measurement candidate does not bind exact evaluator input"
                )
            if candidate.registration_digest != registration_digest:
                raise EvaluatorBackendMalformed(
                    "measurement candidate does not bind trusted registration"
                )
            if candidate.consumption_manifest != verified_inputs.consumption_manifest:
                raise EvaluationAuthorityDenied(
                    "backend consumption manifest does not cover verified inputs"
                )
            payload: dict[str, object] = {
                "evaluation_id": request.evaluation_id,
                "proposal_id": request.proposal_id,
                "tenant_id": request.tenant_id,
                "workspace_id": request.workspace_id,
                "task_id": request.task_id,
                "run_id": request.run_id,
                "input_digest": input_digest,
                "registration_id": registration.registration_id,
                "registration_version": registration.registration_version,
                "registration_digest": registration_digest,
                "evaluator_identity_digest": registration.identity.canonical_digest(),
                "rubric_digest": registration.rubric.canonical_digest(),
                "hidden_set_manifest_digest": (
                    registration.hidden_set.canonical_digest()
                ),
                "evidence_manifest_digest": registration.evidence.canonical_digest(),
                "score": candidate.score,
                "uncertainty": candidate.uncertainty,
                "failure_reasons": candidate.failure_reasons,
                "consumption_manifest": candidate.consumption_manifest,
                "trace_digest": candidate.trace_digest,
                "sealed_at": self._clock(),
            }
            return self._receipt_store.finalize(reservation, payload)
        except Exception:
            self._receipt_store.fail(reservation)
            raise

    def get_receipt(self, evaluation_id: str) -> EvaluationReceipt | None:
        return self._receipt_store.get(evaluation_id)

    def receipt_bytes(self, evaluation_id: str) -> bytes:
        return self._receipt_store.receipt_bytes(evaluation_id)

    def verify_receipt(self, receipt: EvaluationReceipt) -> bool:
        return self._receipt_store.verify(receipt)
