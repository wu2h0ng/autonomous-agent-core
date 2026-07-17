"""Pinned, admission-gated execution bridge for R-STATE-CREDIT-1.

This module has no import-time provider effect and no route adjudication.  It
connects the existing provider actor, interactive environment, representation
arms, sealed checkpoint loss and raw scorer behind a closed authority envelope.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping, Protocol, cast

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS
from experiments.r_state_credit_1.arm_blinding import ArmBlinding
from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily
from experiments.r_state_credit_1.episode_generator import EpisodeGenerator
from experiments.r_state_credit_1.interactive_env import EpisodeStatus
from experiments.r_state_credit_1.recast_arms import ArmRoster
from experiments.r_state_credit_1.recast_freeze_contracts import ReceiptKind
from experiments.r_state_credit_1.recast_provider_actor import ProviderActor
from experiments.r_state_credit_1.recast_scorer import RawRecastScorer
from experiments.r_state_credit_1.run_contracts import CheckpointId, HELD_OUT_SEEDS


SCHEMA_VERSION = "r-state-credit-1-execution-admission-v1"
ROUTE_ID = "R-STATE-CREDIT-1"
TARGET_HEAD = "96eb79e1292d6b8f36ad990d3f97c554a9c33f3b"
EXPECTED_PROVIDER_CALLS = 2240
ARK_BASE_URL_PROFILE = "https://ark.cn-beijing.volces.com/api/plan/v3"
ARK_MODEL_SNAPSHOT = "glm-5-2-260617"
ARK_CREDENTIAL_ENV_REF = "ARK_API_KEY"
ACTIVE_MANIFEST_FILENAME = "R-STATE-CREDIT-1.ACTIVE-MANIFEST.json"

_HEX = frozenset("0123456789abcdef")
_RECEIPT_ROLES = {
    ReceiptKind.PROVIDER_CANARY: (
        "provider-canary-attestor",
        "PROVIDER_CANARY_ACCEPTANCE",
    ),
    ReceiptKind.C7: ("c7-owner", "C7_BINDING_ACCEPTANCE"),
    ReceiptKind.EXECUTOR: ("executor-reviewer", "EXECUTOR_ACCEPTANCE"),
    ReceiptKind.INTEGRITY: ("integrity-reviewer", "INTEGRITY_ACCEPTANCE"),
    ReceiptKind.FREEZE: ("freezer", "FREEZE_ACCEPTANCE"),
    ReceiptKind.RUN_AUTHORIZATION: ("run-authorizer", "RUN_AUTHORIZATION"),
}


class ExecutionBridgeViolation(RuntimeError):
    """An admission or execution invariant failed closed."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in _HEX for c in value):
        raise ExecutionBridgeViolation(f"{label} must be a lowercase SHA-256")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionBridgeViolation(f"{label} must be non-empty text")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ExecutionBridgeViolation(f"{label} must be a positive integer")
    return value


def _closed(value: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ExecutionBridgeViolation(f"{label} must use the closed field set")
    return cast(dict[str, object], value)


def component_digests(root: Path) -> dict[str, str]:
    paths = {
        "executor_sha256": "experiments/r_state_credit_1/execution_bridge.py",
        "scorer_sha256": "experiments/r_state_credit_1/recast_scorer.py",
        "integrity_sha256": "experiments/r_state_credit_1/statistical_integrity.py",
    }
    return {name: _sha256((root / relative).read_bytes()) for name, relative in paths.items()}


@dataclass(frozen=True, slots=True)
class ProviderAdmissionBinding:
    provider_id: str
    base_url_profile: str
    model_id: str
    model_revision: str
    credential_env_ref: str
    canary_receipt_sha256: str

    @classmethod
    def from_mapping(cls, value: object) -> ProviderAdmissionBinding:
        raw = _closed(value, {field.name for field in fields(cls)}, "provider_binding")
        result = cls(**raw)  # type: ignore[arg-type]
        if (
            result.base_url_profile != ARK_BASE_URL_PROFILE
            or result.model_id != ARK_MODEL_SNAPSHOT
            or result.model_revision != ARK_MODEL_SNAPSHOT
            or result.credential_env_ref != ARK_CREDENTIAL_ENV_REF
        ):
            raise ExecutionBridgeViolation("provider must use the pinned immutable snapshot")
        _require_text(result.provider_id, "provider_id")
        _require_sha256(result.canary_receipt_sha256, "canary_receipt_sha256")
        return result

    def subject_sha256(self) -> str:
        return _sha256(
            canonical_json(
                {
                    "base_url_profile": self.base_url_profile,
                    "credential_env_ref": self.credential_env_ref,
                    "model_id": self.model_id,
                    "model_revision": self.model_revision,
                    "provider_id": self.provider_id,
                }
            ).encode()
        )


@dataclass(frozen=True, slots=True)
class C7Binding:
    owner_id: str
    policy_sha256: str
    correction_epoch: str

    @classmethod
    def from_mapping(cls, value: object) -> C7Binding:
        raw = _closed(value, {field.name for field in fields(cls)}, "c7_binding")
        result = cls(**raw)  # type: ignore[arg-type]
        _require_text(result.owner_id, "c7 owner_id")
        _require_sha256(result.policy_sha256, "c7 policy_sha256")
        _require_text(result.correction_epoch, "c7 correction_epoch")
        return result

    def subject_sha256(self) -> str:
        return _sha256(canonical_json(self.to_mapping()).encode())

    def to_mapping(self) -> dict[str, object]:
        return {
            "owner_id": self.owner_id,
            "policy_sha256": self.policy_sha256,
            "correction_epoch": self.correction_epoch,
        }


@dataclass(frozen=True, slots=True)
class WorkflowReservation:
    reservation_id: str
    reservation_token_sha256: str
    attempt_epoch: int
    cas_epoch: int

    @classmethod
    def from_mapping(cls, value: object) -> WorkflowReservation:
        raw = _closed(value, {field.name for field in fields(cls)}, "workflow_reservation")
        result = cls(**raw)  # type: ignore[arg-type]
        _require_text(result.reservation_id, "reservation_id")
        _require_sha256(result.reservation_token_sha256, "reservation_token_sha256")
        _require_positive_int(result.attempt_epoch, "attempt_epoch")
        _require_positive_int(result.cas_epoch, "cas_epoch")
        return result

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    max_provider_calls: int
    max_total_input_tokens: int
    max_total_output_tokens: int
    max_total_cost_microusd: int
    max_input_tokens_per_call: int
    max_output_tokens_per_call: int
    max_cost_microusd_per_call: int

    @classmethod
    def from_mapping(cls, value: object) -> ExecutionBudget:
        raw = _closed(value, {field.name for field in fields(cls)}, "budget")
        result = cls(**raw)  # type: ignore[arg-type]
        for field in fields(result):
            _require_positive_int(getattr(result, field.name), f"budget.{field.name}")
        if result.max_provider_calls != EXPECTED_PROVIDER_CALLS:
            raise ExecutionBridgeViolation("provider call budget must equal exact 2240 coverage")
        return result

    def to_mapping(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class ExecutionAdmission:
    schema_version: str
    route_id: str
    run_id: str
    freeze_subject_digest: str
    freeze_receipt_id: str
    run_authorization_receipt_id: str
    target_head: str
    active_manifest_sha256: str
    provider_binding: ProviderAdmissionBinding
    c7_binding: C7Binding
    workflow_reservation: WorkflowReservation
    components: dict[str, str]
    budget: ExecutionBudget
    six_receipt_digests: dict[ReceiptKind, str]
    envelope_core_sha256: str
    envelope_sha256: str

    @classmethod
    def from_mapping(cls, value: object) -> ExecutionAdmission:
        raw = _closed(value, {field.name for field in fields(cls)}, "execution admission envelope")
        if raw["schema_version"] != SCHEMA_VERSION or raw["route_id"] != ROUTE_ID:
            raise ExecutionBridgeViolation("execution admission route/schema drift")
        if raw["target_head"] != TARGET_HEAD:
            raise ExecutionBridgeViolation("target HEAD drift")
        components = _closed(
            raw["components"],
            {"executor_sha256", "scorer_sha256", "integrity_sha256"},
            "components",
        )
        parsed_components = {
            name: _require_sha256(digest, f"components.{name}")
            for name, digest in components.items()
        }
        receipt_raw = _closed(
            raw["six_receipt_digests"],
            {kind.value for kind in ReceiptKind},
            "six_receipt_digests",
        )
        receipt_digests = {
            kind: _require_sha256(receipt_raw[kind.value], f"receipt {kind.value}")
            for kind in ReceiptKind
        }
        result = cls(
            schema_version=cast(str, raw["schema_version"]),
            route_id=cast(str, raw["route_id"]),
            run_id=_require_text(raw["run_id"], "run_id"),
            freeze_subject_digest=_require_sha256(raw["freeze_subject_digest"], "freeze_subject_digest"),
            freeze_receipt_id=_require_text(raw["freeze_receipt_id"], "freeze_receipt_id"),
            run_authorization_receipt_id=_require_text(
                raw["run_authorization_receipt_id"], "run_authorization_receipt_id"
            ),
            target_head=cast(str, raw["target_head"]),
            active_manifest_sha256=_require_sha256(
                raw["active_manifest_sha256"], "active_manifest_sha256"
            ),
            provider_binding=ProviderAdmissionBinding.from_mapping(raw["provider_binding"]),
            c7_binding=C7Binding.from_mapping(raw["c7_binding"]),
            workflow_reservation=WorkflowReservation.from_mapping(raw["workflow_reservation"]),
            components=parsed_components,
            budget=ExecutionBudget.from_mapping(raw["budget"]),
            six_receipt_digests=receipt_digests,
            envelope_core_sha256=_require_sha256(raw["envelope_core_sha256"], "envelope_core_sha256"),
            envelope_sha256=_require_sha256(raw["envelope_sha256"], "envelope_sha256"),
        )
        if result.recompute_core_sha256() != result.envelope_core_sha256:
            raise ExecutionBridgeViolation("envelope core digest drift")
        if result.recompute_envelope_sha256() != result.envelope_sha256:
            raise ExecutionBridgeViolation("envelope digest drift")
        return result

    @classmethod
    def from_canonical_json(cls, encoded: bytes) -> ExecutionAdmission:
        try:
            raw = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionBridgeViolation("execution admission must be JSON") from exc
        if canonical_json(raw).encode() != encoded:
            raise ExecutionBridgeViolation("execution admission must be strict canonical JSON")
        return cls.from_mapping(raw)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "route_id": self.route_id,
            "run_id": self.run_id,
            "freeze_subject_digest": self.freeze_subject_digest,
            "freeze_receipt_id": self.freeze_receipt_id,
            "run_authorization_receipt_id": self.run_authorization_receipt_id,
            "target_head": self.target_head,
            "active_manifest_sha256": self.active_manifest_sha256,
            "provider_binding": {
                field.name: getattr(self.provider_binding, field.name)
                for field in fields(self.provider_binding)
            },
            "c7_binding": self.c7_binding.to_mapping(),
            "workflow_reservation": self.workflow_reservation.to_mapping(),
            "components": dict(self.components),
            "budget": self.budget.to_mapping(),
            "six_receipt_digests": {
                kind.value: self.six_receipt_digests[kind] for kind in ReceiptKind
            },
            "envelope_core_sha256": self.envelope_core_sha256,
            "envelope_sha256": self.envelope_sha256,
        }

    def recompute_core_sha256(self) -> str:
        payload = self.to_mapping()
        payload.pop("envelope_core_sha256")
        payload.pop("envelope_sha256")
        receipts = cast(dict[str, str], payload["six_receipt_digests"])
        receipts.pop(ReceiptKind.RUN_AUTHORIZATION.value)
        return _sha256(canonical_json(payload).encode())

    def recompute_envelope_sha256(self) -> str:
        payload = self.to_mapping()
        payload.pop("envelope_sha256")
        return _sha256(canonical_json(payload).encode())


@dataclass(frozen=True, slots=True)
class ReceiptVerification:
    registry_verified: bool
    principal_id: str
    role: str
    purpose: str
    subject_sha256: str
    artifact_sha256: str


@dataclass(frozen=True, slots=True)
class ReservationVerification:
    registry_verified: bool
    reservation_id: str
    reservation_token_sha256: str
    attempt_epoch: int
    cas_epoch: int
    run_id: str
    active: bool


class AuthorityVerifier(Protocol):
    def verify(self, kind: ReceiptKind, receipt_bytes: bytes) -> ReceiptVerification: ...

    def verify_reservation(
        self, reservation: dict[str, object], run_id: str
    ) -> ReservationVerification: ...


class C7Probe(Protocol):
    owner_id: str
    policy_sha256: str
    correction_epoch: str

    def abort_requested(self) -> bool: ...


class WorkspaceProbe(Protocol):
    def admit(self, target_head: str, expected_components: dict[str, str]) -> str: ...

    def revalidate(self, anchor_head: str, expected_components: dict[str, str]) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    raw_path: Path
    raw_sha256: str
    row_count: int


@dataclass(slots=True)
class _BudgetLedger:
    budget: ExecutionBudget
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_microusd: int = 0

    def reserve(self) -> None:
        if self.calls + 1 > self.budget.max_provider_calls:
            raise ExecutionBridgeViolation("remaining provider call budget is exhausted")
        checks = (
            (self.input_tokens, self.budget.max_input_tokens_per_call, self.budget.max_total_input_tokens, "input token"),
            (self.output_tokens, self.budget.max_output_tokens_per_call, self.budget.max_total_output_tokens, "output token"),
            (self.cost_microusd, self.budget.max_cost_microusd_per_call, self.budget.max_total_cost_microusd, "cost"),
        )
        for used, reservation, total, label in checks:
            if used + reservation > total:
                raise ExecutionBridgeViolation(f"remaining {label} budget cannot cover per-call reserve")

    def settle(self, *, input_tokens: int, output_tokens: int, cost_microusd: int) -> None:
        actual = (input_tokens, output_tokens, cost_microusd)
        caps = (
            self.budget.max_input_tokens_per_call,
            self.budget.max_output_tokens_per_call,
            self.budget.max_cost_microusd_per_call,
        )
        if any(value > cap for value, cap in zip(actual, caps, strict=True)):
            raise ExecutionBridgeViolation("provider usage exceeded the reserved per-call cap")
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_microusd += cost_microusd

    def to_mapping(self) -> dict[str, int]:
        return {
            "provider_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_microusd": self.cost_microusd,
        }


class ExecutionBridge:
    """One-shot 2,240-effect executor with durable terminal sealing."""

    def __init__(
        self,
        *,
        root: Path,
        active_manifest: Path,
        run_dir: Path,
        receipt_documents: Mapping[ReceiptKind, bytes],
        receipt_verifier: AuthorityVerifier,
        workspace_probe: WorkspaceProbe,
        c7: C7Probe,
        actor: ProviderActor,
    ) -> None:
        self.root = root
        self.active_manifest = active_manifest
        self.run_dir = run_dir
        self.receipt_documents = dict(receipt_documents)
        self.receipt_verifier = receipt_verifier
        self.workspace_probe = workspace_probe
        self.c7 = c7
        self.actor = actor
        self.lock_path = run_dir / "execution.lock.json"
        self.journal_path = run_dir / "execution.journal.jsonl"
        self.raw_path = run_dir / "rfinal.raw.json"
        self.partial_path = run_dir / "rfinal.partial.json"
        self._anchor_head: str | None = None

    def _receipt_payload(self, kind: ReceiptKind) -> dict[str, object]:
        encoded = self.receipt_documents[kind]
        try:
            raw = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionBridgeViolation("receipt must be canonical JSON") from exc
        if canonical_json(raw).encode() != encoded:
            raise ExecutionBridgeViolation("receipt must be canonical JSON")
        return _closed(raw, {"kind", "receipt_id", "subject_sha256"}, f"{kind.value} receipt")

    def admit(self, envelope: ExecutionAdmission) -> None:
        if set(self.receipt_documents) != set(ReceiptKind):
            raise ExecutionBridgeViolation("exact six receipt documents are required")
        if _sha256(self.active_manifest.read_bytes()) != envelope.active_manifest_sha256:
            raise ExecutionBridgeViolation("active manifest digest drift")
        actual_components = component_digests(self.root)
        if actual_components != envelope.components:
            raise ExecutionBridgeViolation("component digest drift")
        actor_binding = self.actor.binding
        expected_actor = envelope.provider_binding
        if (
            actor_binding.provider_id != expected_actor.provider_id
            or actor_binding.model_id != expected_actor.model_id
            or actor_binding.model_revision != expected_actor.model_revision
        ):
            raise ExecutionBridgeViolation("provider actor binding drift")
        if (
            self.c7.owner_id != envelope.c7_binding.owner_id
            or self.c7.policy_sha256 != envelope.c7_binding.policy_sha256
            or self.c7.correction_epoch != envelope.c7_binding.correction_epoch
        ):
            raise ExecutionBridgeViolation("C7 binding drift")
        for kind in ReceiptKind:
            if _sha256(self.receipt_documents[kind]) != envelope.six_receipt_digests[kind]:
                raise ExecutionBridgeViolation(f"{kind.value} receipt digest drift")
        payloads = {kind: self._receipt_payload(kind) for kind in ReceiptKind}
        expected_subjects = {
            ReceiptKind.PROVIDER_CANARY: envelope.provider_binding.subject_sha256(),
            ReceiptKind.C7: envelope.c7_binding.subject_sha256(),
            ReceiptKind.EXECUTOR: envelope.components["executor_sha256"],
            ReceiptKind.INTEGRITY: envelope.components["integrity_sha256"],
            ReceiptKind.FREEZE: envelope.freeze_subject_digest,
            ReceiptKind.RUN_AUTHORIZATION: envelope.envelope_core_sha256,
        }
        principals: set[str] = set()
        for kind in ReceiptKind:
            encoded = self.receipt_documents[kind]
            digest = _sha256(encoded)
            payload = payloads[kind]
            if payload["kind"] != kind.value or payload["subject_sha256"] != expected_subjects[kind]:
                raise ExecutionBridgeViolation(f"{kind.value} receipt subject drift")
            verification = self.receipt_verifier.verify(kind, encoded)
            role, purpose = _RECEIPT_ROLES[kind]
            if not isinstance(verification, ReceiptVerification) or (
                not verification.registry_verified
                or verification.role != role
                or verification.purpose != purpose
            ):
                raise ExecutionBridgeViolation("external receipt signature role/purpose verification failed")
            if (
                verification.subject_sha256 != expected_subjects[kind]
                or verification.artifact_sha256 != digest
            ):
                raise ExecutionBridgeViolation("external receipt signature binding drift")
            if verification.principal_id in principals:
                raise ExecutionBridgeViolation("receipt principals must be role-distinct")
            principals.add(verification.principal_id)
        if payloads[ReceiptKind.FREEZE]["receipt_id"] != envelope.freeze_receipt_id:
            raise ExecutionBridgeViolation("freeze receipt id drift")
        if (
            payloads[ReceiptKind.RUN_AUTHORIZATION]["receipt_id"]
            != envelope.run_authorization_receipt_id
        ):
            raise ExecutionBridgeViolation("run authorization receipt id drift")
        if (
            envelope.provider_binding.canary_receipt_sha256
            != envelope.six_receipt_digests[ReceiptKind.PROVIDER_CANARY]
        ):
            raise ExecutionBridgeViolation("provider canary receipt binding drift")
        reservation = self.receipt_verifier.verify_reservation(
            envelope.workflow_reservation.to_mapping(), envelope.run_id
        )
        expected_reservation = envelope.workflow_reservation
        if (
            not reservation.registry_verified
            or not reservation.active
            or reservation.reservation_id != expected_reservation.reservation_id
            or reservation.reservation_token_sha256 != expected_reservation.reservation_token_sha256
            or reservation.attempt_epoch != expected_reservation.attempt_epoch
            or reservation.cas_epoch != expected_reservation.cas_epoch
            or reservation.run_id != envelope.run_id
        ):
            raise ExecutionBridgeViolation("workflow reservation registry/CAS verification failed")
        self._anchor_head = self.workspace_probe.admit(TARGET_HEAD, envelope.components)

    def _write_exclusive(self, path: Path, payload: object) -> None:
        encoded = (canonical_json(payload) + "\n").encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ExecutionBridgeViolation("execution attempt is permanently consumed") from exc
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _journal(self, payload: object) -> None:
        encoded = (canonical_json(payload) + "\n").encode()
        descriptor = os.open(
            self.journal_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        with os.fdopen(descriptor, "ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    def _terminal_payload(
        self,
        *,
        envelope: ExecutionAdmission,
        state: str,
        rows: list[dict[str, object]],
        ledger: _BudgetLedger,
        last_call_index: int,
        provider_receipt_digests: list[str],
        error: BaseException,
    ) -> dict[str, object]:
        return {
            "schema_version": "r-state-credit-1-execution-terminal-v1",
            "state": state,
            "run_id": envelope.run_id,
            "envelope_sha256": envelope.envelope_sha256,
            "envelope_core_sha256": envelope.envelope_core_sha256,
            "run_authorization_receipt_sha256": envelope.six_receipt_digests[
                ReceiptKind.RUN_AUTHORIZATION
            ],
            "reservation_id": envelope.workflow_reservation.reservation_id,
            "attempt_epoch": envelope.workflow_reservation.attempt_epoch,
            "cas_epoch": envelope.workflow_reservation.cas_epoch,
            "last_call_index": last_call_index,
            "row_count": len(rows),
            "usage": ledger.to_mapping(),
            "ordered_provider_receipt_sha256": provider_receipt_digests,
            "failure_type": type(error).__name__,
            "rows": rows,
        }

    def _check_c7(self) -> None:
        aborted = self.c7.abort_requested()
        if not isinstance(aborted, bool):
            raise ExecutionBridgeViolation("C7 probe must return bool")
        if aborted:
            raise ExecutionBridgeViolation("C7 interrupted execution")

    def execute(self, envelope: ExecutionAdmission) -> ExecutionReceipt:
        self.admit(envelope)
        self._write_exclusive(
            self.lock_path,
            {
                "schema_version": "r-state-credit-1-execution-lock-v1",
                "state": "AUTHORIZED",
                "run_id": envelope.run_id,
                "envelope_sha256": envelope.envelope_sha256,
                "reservation_id": envelope.workflow_reservation.reservation_id,
                "attempt_epoch": envelope.workflow_reservation.attempt_epoch,
                "cas_epoch": envelope.workflow_reservation.cas_epoch,
            },
        )
        self._journal({"state": "AUTHORIZED", "run_id": envelope.run_id})
        rows: list[dict[str, object]] = []
        ledger = _BudgetLedger(envelope.budget)
        provider_receipt_ids: set[str] = set()
        request_digests: set[str] = set()
        provider_receipt_digests: list[str] = []
        last_call_index = 0
        provider_started = False
        provider_settled = False
        try:
            for family in ScenarioFamily:
                for seed in HELD_OUT_SEEDS:
                    episode_root = self.run_dir / "episodes" / family.value / str(seed)
                    episode = EpisodeGenerator(family.value, seed).generate(
                        temp_root=episode_root
                    )
                    roster = ArmRoster()
                    blinding = ArmBlinding(episode._episode_seed)
                    try:
                        while episode.status is EpisodeStatus.RUNNING:
                            observation = episode.observe()
                            if episode._turn_index in episode.checkpoints:
                                ordinal = episode.checkpoints.index(episode._turn_index)
                                checkpoint = tuple(CheckpointId)[ordinal]
                                calls = blinding.blinded_calls(
                                    ordinal,
                                    episode.observations[: episode._turn_index],
                                    roster,
                                    ALL_ACTIONS,
                                )
                                for call in calls:
                                    last_call_index += 1
                                    if call.request is None:
                                        raise ExecutionBridgeViolation(
                                            "arm budget forced a non-provider row; exact 2240-call route is invalid"
                                        )
                                    self._check_c7()
                                    ledger.reserve()
                                    if self._anchor_head is None:
                                        raise ExecutionBridgeViolation("workspace anchor is absent")
                                    self.workspace_probe.revalidate(
                                        self._anchor_head, envelope.components
                                    )
                                    request_digest = _sha256(
                                        call.request.to_canonical_json().encode()
                                    )
                                    if request_digest in request_digests:
                                        raise ExecutionBridgeViolation(
                                            "provider request digest must be globally unique"
                                        )
                                    request_digests.add(request_digest)
                                    identity = {
                                        "family": family.value,
                                        "seed": seed,
                                        "checkpoint_id": checkpoint.value,
                                        "arm_id": blinding.arm_for_label(
                                            ordinal, call.session_label
                                        ).value,
                                    }
                                    self._journal(
                                        {
                                            "state": "RESERVED",
                                            "call_index": last_call_index,
                                            "identity": identity,
                                            "request_sha256": request_digest,
                                            "reserve": {
                                                "input_tokens": envelope.budget.max_input_tokens_per_call,
                                                "output_tokens": envelope.budget.max_output_tokens_per_call,
                                                "cost_microusd": envelope.budget.max_cost_microusd_per_call,
                                            },
                                        }
                                    )
                                    self._journal(
                                        {
                                            "state": "STARTED",
                                            "call_index": last_call_index,
                                            "request_sha256": request_digest,
                                        }
                                    )
                                    provider_started = True
                                    provider_settled = False
                                    actor_response = self.actor.act(call.request)
                                    receipt = actor_response.receipt
                                    if receipt.provider_receipt_id in provider_receipt_ids:
                                        raise ExecutionBridgeViolation(
                                            "provider receipt id must be globally unique"
                                        )
                                    provider_receipt_ids.add(receipt.provider_receipt_id)
                                    ledger.settle(
                                        input_tokens=receipt.input_tokens,
                                        output_tokens=receipt.output_tokens,
                                        cost_microusd=envelope.budget.max_cost_microusd_per_call,
                                    )
                                    receipt_mapping = {
                                        "provider_receipt_id": receipt.provider_receipt_id,
                                        "provider_id": receipt.provider_id,
                                        "model_id": receipt.model_id,
                                        "model_revision": receipt.model_revision,
                                        "request_sha256": receipt.request_sha256,
                                        "response_sha256": receipt.response_sha256,
                                        "input_tokens": receipt.input_tokens,
                                        "output_tokens": receipt.output_tokens,
                                        "cost_microusd": envelope.budget.max_cost_microusd_per_call,
                                        "run_id": envelope.run_id,
                                        "call_index": last_call_index,
                                    }
                                    receipt_digest = _sha256(
                                        canonical_json(receipt_mapping).encode()
                                    )
                                    provider_receipt_digests.append(receipt_digest)
                                    self._journal(
                                        {
                                            "state": "STARTED",
                                            "event": "RECEIPT_SETTLED",
                                            "call_index": last_call_index,
                                            "provider_receipt_sha256": receipt_digest,
                                            "usage": ledger.to_mapping(),
                                        }
                                    )
                                    provider_settled = True
                                    self._check_c7()
                                    arm_id, resolved = blinding.resolve_response(
                                        ordinal,
                                        actor_response.response,
                                        call.session_label,
                                    )
                                    loss, weight = episode.score_action(resolved.action)
                                    rows.append(
                                        {
                                            "run_id": envelope.run_id,
                                            "call_index": last_call_index,
                                            "episode_id": f"rsc1:{family.value.lower()}:{seed}",
                                            "family": family.value,
                                            "seed": seed,
                                            "checkpoint_id": checkpoint.value,
                                            "arm_id": arm_id.value,
                                            "request_sha256": request_digest,
                                            "provider_receipt_id": receipt.provider_receipt_id,
                                            "provider_receipt_sha256": receipt_digest,
                                            "response_sha256": receipt.response_sha256,
                                            "model_revision": receipt.model_revision,
                                            "input_tokens": receipt.input_tokens,
                                            "output_tokens": receipt.output_tokens,
                                            "cost_microusd": envelope.budget.max_cost_microusd_per_call,
                                            "action": resolved.action.value,
                                            "loss_code": loss.value,
                                            "loss_weight": weight,
                                        }
                                    )
                                    provider_started = False
                            episode.step(episode._default_policy(observation, episode))
                    finally:
                        episode.cleanup()
            if ledger.calls != EXPECTED_PROVIDER_CALLS or len(rows) != EXPECTED_PROVIDER_CALLS:
                raise ExecutionBridgeViolation("exact 2240-call/row coverage drift")
            expected: set[tuple[object, object, object, object]] = {
                (family.value, seed, checkpoint.value, arm.value)
                for family in ScenarioFamily
                for seed in HELD_OUT_SEEDS
                for checkpoint in CheckpointId
                for arm in ArmId
            }
            scorer = RawRecastScorer()
            scorer.validate_identity_rows(rows, expected=expected)
            raw_metrics = scorer.score_raw(rows)
            payload: dict[str, object] = {
                "schema_version": "r-state-credit-1-execution-raw-v1",
                "artifact_class": "RAW_EXECUTION",
                "state": "SEALED_RAW",
                "run_id": envelope.run_id,
                "envelope_sha256": envelope.envelope_sha256,
                "run_authorization_receipt_sha256": envelope.six_receipt_digests[
                    ReceiptKind.RUN_AUTHORIZATION
                ],
                "usage": ledger.to_mapping(),
                "ordered_provider_receipt_sha256": provider_receipt_digests,
                "raw_metrics": raw_metrics,
                "rows": rows,
            }
            self._write_exclusive(self.raw_path, payload)
            self._journal(
                {
                    "state": "SEALED_RAW",
                    "row_count": len(rows),
                    "raw_sha256": _sha256(self.raw_path.read_bytes()),
                }
            )
            return ExecutionReceipt(
                raw_path=self.raw_path,
                raw_sha256=_sha256(self.raw_path.read_bytes()),
                row_count=len(rows),
            )
        except BaseException as exc:
            state = (
                "AMBIGUOUS_EFFECT_TERMINAL"
                if provider_started and not provider_settled
                else "PARTIAL_TERMINAL"
            )
            terminal = self._terminal_payload(
                envelope=envelope,
                state=state,
                rows=rows,
                ledger=ledger,
                last_call_index=last_call_index,
                provider_receipt_digests=provider_receipt_digests,
                error=exc,
            )
            self._write_exclusive(self.partial_path, terminal)
            self._journal(
                {
                    "state": state,
                    "last_call_index": last_call_index,
                    "row_count": len(rows),
                    "partial_sha256": _sha256(self.partial_path.read_bytes()),
                }
            )
            raise
