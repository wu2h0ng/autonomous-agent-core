"""Pinned, admission-gated execution bridge for R-STATE-CREDIT-1.

This module has no import-time provider effect and no route adjudication.  It
connects the existing provider actor, interactive environment, representation
arms, sealed checkpoint loss and raw scorer behind a closed authority envelope.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Callable, Mapping, Protocol, cast

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS
from experiments.r_state_credit_1.arm_blinding import ArmBlinding
from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily
from experiments.r_state_credit_1.episode_generator import EpisodeGenerator
from experiments.r_state_credit_1.interactive_env import EpisodeStatus
from experiments.r_state_credit_1.recast_arms import ArmRoster
from experiments.r_state_credit_1.recast_freeze_contracts import ReceiptKind
from experiments.r_state_credit_1.recast_provider_actor import (
    ProviderActor,
    ProviderCostStatus,
)
from experiments.r_state_credit_1.recast_scorer import RawRecastScorer
from experiments.r_state_credit_1.run_contracts import CheckpointId, HELD_OUT_SEEDS


SCHEMA_VERSION = "r-state-credit-1-execution-admission-v3"
ROUTE_ID = "R-STATE-CREDIT-1"
# This is the independently reviewed mechanism baseline, not the Git HEAD of
# this execution adapter.  Execution bytes are anchored by the active manifest
# and component digests; requiring this module to contain its own future commit
# hash would create an impossible self-reference.
MECHANISM_BASELINE_HEAD = "96eb79e1292d6b8f36ad990d3f97c554a9c33f3b"
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
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in _HEX for c in value)
    ):
        raise ExecutionBridgeViolation(f"{label} must be a lowercase SHA-256")
    return value


def _require_git_head(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(c not in _HEX for c in value)
    ):
        raise ExecutionBridgeViolation(f"{label} must be a lowercase 40-hex Git HEAD")
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
    return {
        name: _sha256((root / relative).read_bytes())
        for name, relative in paths.items()
    }


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
            raise ExecutionBridgeViolation(
                "provider must use the pinned immutable snapshot"
            )
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
class AuthorityBinding:
    broker_id: str
    protocol_version: str
    response_public_key_sha256: str
    server_nonce_sha256: str
    isolation_binding_sha256: str

    @classmethod
    def from_mapping(cls, value: object) -> AuthorityBinding:
        raw = _closed(value, {field.name for field in fields(cls)}, "authority_binding")
        result = cls(**raw)  # type: ignore[arg-type]
        _require_text(result.broker_id, "authority broker_id")
        if result.protocol_version != "r-state-authority-v1":
            raise ExecutionBridgeViolation("authority protocol version drift")
        _require_sha256(
            result.response_public_key_sha256,
            "authority response_public_key_sha256",
        )
        _require_sha256(result.server_nonce_sha256, "authority server_nonce_sha256")
        _require_sha256(
            result.isolation_binding_sha256, "authority isolation_binding_sha256"
        )
        return result

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class IsolationBinding:
    schema_version: str
    interpreter_path: str
    interpreter_sha256: str
    sandbox_profile_sha256: str
    required_deny_set_sha256: str
    authority_public_key_sha256: str
    child_command_sha256: str

    @classmethod
    def from_mapping(cls, value: object) -> IsolationBinding:
        raw = _closed(value, {field.name for field in fields(cls)}, "isolation_binding")
        result = cls(**raw)  # type: ignore[arg-type]
        if result.schema_version != "r-state-credit-1-isolation-binding-v1":
            raise ExecutionBridgeViolation("isolation binding schema drift")
        if not result.interpreter_path.startswith("/"):
            raise ExecutionBridgeViolation(
                "isolation interpreter_path must be absolute"
            )
        for field_name in (
            "interpreter_sha256",
            "sandbox_profile_sha256",
            "required_deny_set_sha256",
            "authority_public_key_sha256",
            "child_command_sha256",
        ):
            _require_sha256(getattr(result, field_name), f"isolation {field_name}")
        return result

    def to_mapping(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def subject_sha256(self) -> str:
        return _sha256(canonical_json(self.to_mapping()).encode())


@dataclass(frozen=True, slots=True)
class WorkflowReservation:
    reservation_id: str
    reservation_token_sha256: str
    attempt_epoch: int
    cas_epoch: int

    @classmethod
    def from_mapping(cls, value: object) -> WorkflowReservation:
        raw = _closed(
            value, {field.name for field in fields(cls)}, "workflow_reservation"
        )
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
    max_total_tokens: int
    max_input_tokens_per_call: int
    max_output_tokens_per_call: int
    max_total_tokens_per_call: int

    @classmethod
    def from_mapping(cls, value: object) -> ExecutionBudget:
        raw = _closed(value, {field.name for field in fields(cls)}, "budget")
        result = cls(**raw)  # type: ignore[arg-type]
        for field in fields(result):
            _require_positive_int(getattr(result, field.name), f"budget.{field.name}")
        if result.max_provider_calls != EXPECTED_PROVIDER_CALLS:
            raise ExecutionBridgeViolation(
                "provider call budget must equal exact 2240 coverage"
            )
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
    mechanism_head: str
    execution_code_head: str
    active_manifest_sha256: str
    provider_binding: ProviderAdmissionBinding
    c7_binding: C7Binding
    authority_binding: AuthorityBinding
    isolation_binding: IsolationBinding
    workflow_reservation: WorkflowReservation
    components: dict[str, str]
    budget: ExecutionBudget
    six_receipt_digests: dict[ReceiptKind, str]
    envelope_core_sha256: str
    envelope_sha256: str

    @classmethod
    def from_mapping(cls, value: object) -> ExecutionAdmission:
        raw = _closed(
            value, {field.name for field in fields(cls)}, "execution admission envelope"
        )
        if raw["schema_version"] != SCHEMA_VERSION or raw["route_id"] != ROUTE_ID:
            raise ExecutionBridgeViolation("execution admission route/schema drift")
        if raw["mechanism_head"] != MECHANISM_BASELINE_HEAD:
            raise ExecutionBridgeViolation("mechanism baseline HEAD drift")
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
            freeze_subject_digest=_require_sha256(
                raw["freeze_subject_digest"], "freeze_subject_digest"
            ),
            freeze_receipt_id=_require_text(
                raw["freeze_receipt_id"], "freeze_receipt_id"
            ),
            run_authorization_receipt_id=_require_text(
                raw["run_authorization_receipt_id"], "run_authorization_receipt_id"
            ),
            mechanism_head=cast(str, raw["mechanism_head"]),
            execution_code_head=_require_git_head(
                raw["execution_code_head"], "execution_code_head"
            ),
            active_manifest_sha256=_require_sha256(
                raw["active_manifest_sha256"], "active_manifest_sha256"
            ),
            provider_binding=ProviderAdmissionBinding.from_mapping(
                raw["provider_binding"]
            ),
            c7_binding=C7Binding.from_mapping(raw["c7_binding"]),
            authority_binding=AuthorityBinding.from_mapping(raw["authority_binding"]),
            isolation_binding=IsolationBinding.from_mapping(raw["isolation_binding"]),
            workflow_reservation=WorkflowReservation.from_mapping(
                raw["workflow_reservation"]
            ),
            components=parsed_components,
            budget=ExecutionBudget.from_mapping(raw["budget"]),
            six_receipt_digests=receipt_digests,
            envelope_core_sha256=_require_sha256(
                raw["envelope_core_sha256"], "envelope_core_sha256"
            ),
            envelope_sha256=_require_sha256(raw["envelope_sha256"], "envelope_sha256"),
        )
        if result.recompute_core_sha256() != result.envelope_core_sha256:
            raise ExecutionBridgeViolation("envelope core digest drift")
        if result.recompute_envelope_sha256() != result.envelope_sha256:
            raise ExecutionBridgeViolation("envelope digest drift")
        if (
            result.isolation_binding.authority_public_key_sha256
            != result.authority_binding.response_public_key_sha256
        ):
            raise ExecutionBridgeViolation("isolation authority public key drift")
        if (
            result.isolation_binding.subject_sha256()
            != result.authority_binding.isolation_binding_sha256
        ):
            raise ExecutionBridgeViolation("authority isolation binding digest drift")
        return result

    @classmethod
    def from_canonical_json(cls, encoded: bytes) -> ExecutionAdmission:
        try:
            raw = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionBridgeViolation("execution admission must be JSON") from exc
        if canonical_json(raw).encode() != encoded:
            raise ExecutionBridgeViolation(
                "execution admission must be strict canonical JSON"
            )
        return cls.from_mapping(raw)

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "route_id": self.route_id,
            "run_id": self.run_id,
            "freeze_subject_digest": self.freeze_subject_digest,
            "freeze_receipt_id": self.freeze_receipt_id,
            "run_authorization_receipt_id": self.run_authorization_receipt_id,
            "mechanism_head": self.mechanism_head,
            "execution_code_head": self.execution_code_head,
            "active_manifest_sha256": self.active_manifest_sha256,
            "provider_binding": {
                field.name: getattr(self.provider_binding, field.name)
                for field in fields(self.provider_binding)
            },
            "c7_binding": self.c7_binding.to_mapping(),
            "authority_binding": self.authority_binding.to_mapping(),
            "isolation_binding": self.isolation_binding.to_mapping(),
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
class ReservationClaimReceipt:
    registry_verified: bool
    claimed: bool
    claim_id: str
    reservation_id: str
    reservation_token_sha256: str
    attempt_epoch: int
    cas_epoch: int
    run_id: str
    envelope_sha256: str
    claimant_nonce_sha256: str


@dataclass(frozen=True, slots=True)
class ReservationTerminalReceipt:
    registry_verified: bool
    claim_id: str
    state: str
    terminal_sha256: str
    terminalized: bool


class AuthorityVerifier(Protocol):
    def verify(
        self, kind: ReceiptKind, receipt_bytes: bytes
    ) -> ReceiptVerification: ...

    def claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
        claimant_nonce_sha256: str,
    ) -> ReservationClaimReceipt: ...

    def query_claim(
        self,
        reservation: dict[str, object],
        run_id: str,
        envelope_sha256: str,
        claimant_nonce_sha256: str,
    ) -> ReservationClaimReceipt | None: ...

    def terminalize(
        self,
        claim: ReservationClaimReceipt,
        state: str,
        terminal_sha256: str,
    ) -> ReservationTerminalReceipt: ...

    def query_terminal(self, claim_id: str) -> ReservationTerminalReceipt | None: ...


class C7Probe(Protocol):
    owner_id: str
    policy_sha256: str
    correction_epoch: str

    def abort_requested(self) -> bool: ...


class WorkspaceProbe(Protocol):
    def admit(
        self,
        mechanism_head: str,
        execution_code_head: str,
        expected_components: dict[str, str],
    ) -> str: ...

    def revalidate(
        self, anchor_head: str, expected_components: dict[str, str]
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    raw_path: Path
    raw_sha256: str
    row_count: int


_RAW_ROW_FIELDS = {
    "run_id",
    "call_index",
    "episode_id",
    "family",
    "seed",
    "checkpoint_id",
    "arm_id",
    "actor_request_sha256",
    "provider_request_sha256",
    "provider_receipt_id",
    "provider_receipt_sha256",
    "provider_response_sha256",
    "raw_output_sha256",
    "model_revision",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_status",
    "cost_amount_microunits",
    "cost_currency",
    "latency_ms",
    "timeout_seconds",
    "action",
    "loss_code",
    "loss_weight",
}
_FORBIDDEN_RAW_FIELDS = {"met", "not_met", "verdict", "promotion"}


def assert_raw_only(value: object) -> None:
    """Recursively reject route-adjudication fields or scalar values."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.casefold() in _FORBIDDEN_RAW_FIELDS:
                raise ExecutionBridgeViolation("raw output contains route adjudication")
            assert_raw_only(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_raw_only(item)
    elif isinstance(value, str) and value.casefold() in _FORBIDDEN_RAW_FIELDS:
        raise ExecutionBridgeViolation("raw output contains route adjudication")


@dataclass(frozen=True, slots=True)
class InternalSealedRawRow:
    """Runner-internal closed raw row; never a public actor input."""

    values: dict[str, object]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> InternalSealedRawRow:
        if set(value) != _RAW_ROW_FIELDS:
            raise ExecutionBridgeViolation("internal sealed raw row must be closed")
        assert_raw_only(value)
        return cls(values=dict(value))

    def to_mapping(self) -> dict[str, object]:
        return dict(self.values)


@dataclass(slots=True)
class _BudgetLedger:
    budget: ExecutionBudget
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_status: ProviderCostStatus | None = None
    cost_amount_microunits: int | None = None
    cost_currency: str | None = None

    def reserve(self) -> None:
        if self.calls + 1 > self.budget.max_provider_calls:
            raise ExecutionBridgeViolation(
                "remaining provider call budget is exhausted"
            )
        checks = (
            (
                self.input_tokens,
                self.budget.max_input_tokens_per_call,
                self.budget.max_total_input_tokens,
                "input token",
            ),
            (
                self.output_tokens,
                self.budget.max_output_tokens_per_call,
                self.budget.max_total_output_tokens,
                "output token",
            ),
            (
                self.total_tokens,
                self.budget.max_total_tokens_per_call,
                self.budget.max_total_tokens,
                "total token",
            ),
        )
        for used, reservation, total, label in checks:
            if used + reservation > total:
                raise ExecutionBridgeViolation(
                    f"remaining {label} budget cannot cover per-call reserve"
                )

    def settle(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_status: ProviderCostStatus,
        cost_amount_microunits: int | None,
        cost_currency: str | None,
    ) -> None:
        actual = (input_tokens, output_tokens, total_tokens)
        caps = (
            self.budget.max_input_tokens_per_call,
            self.budget.max_output_tokens_per_call,
            self.budget.max_total_tokens_per_call,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in actual
        ):
            raise ExecutionBridgeViolation("provider token usage is invalid")
        if total_tokens != input_tokens + output_tokens:
            raise ExecutionBridgeViolation("provider total token usage drift")
        if any(value > cap for value, cap in zip(actual, caps, strict=True)):
            raise ExecutionBridgeViolation(
                "provider usage exceeded the reserved per-call cap"
            )
        if self.cost_status is not None and self.cost_status is not cost_status:
            raise ExecutionBridgeViolation("mixed provider cost status is forbidden")
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total_tokens
        self.cost_status = cost_status
        if cost_status is ProviderCostStatus.UNAVAILABLE_NOT_GUESSED:
            if cost_amount_microunits is not None or cost_currency is not None:
                raise ExecutionBridgeViolation("unknown provider cost must remain null")
        else:
            if cost_amount_microunits is None or cost_currency is None:
                raise ExecutionBridgeViolation("reported provider cost is incomplete")
            if (
                not isinstance(cost_amount_microunits, int)
                or isinstance(cost_amount_microunits, bool)
                or cost_amount_microunits < 0
                or not isinstance(cost_currency, str)
                or not cost_currency
            ):
                raise ExecutionBridgeViolation("reported provider cost is invalid")
            if self.cost_currency is not None and self.cost_currency != cost_currency:
                raise ExecutionBridgeViolation(
                    "mixed provider cost currency is forbidden"
                )
            self.cost_currency = cost_currency
            self.cost_amount_microunits = (
                self.cost_amount_microunits or 0
            ) + cost_amount_microunits

    def to_mapping(self) -> dict[str, object]:
        return {
            "provider_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_status": (
                self.cost_status.value if self.cost_status is not None else None
            ),
            "cost_amount_microunits": self.cost_amount_microunits,
            "cost_currency": self.cost_currency,
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
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.root = root
        self.active_manifest = active_manifest
        self.run_dir = run_dir
        self.receipt_documents = dict(receipt_documents)
        self.receipt_verifier = receipt_verifier
        self.workspace_probe = workspace_probe
        self.c7 = c7
        self.actor = actor
        self._fault_hook = fault_hook
        self.lock_path = run_dir / "execution.lock.json"
        self.journal_path = run_dir / "execution.journal.jsonl"
        self.raw_path = run_dir / "rfinal.raw.json"
        self.partial_path = run_dir / "rfinal.partial.json"
        self.claim_intent_path = run_dir / "execution.claim-intent.json"
        self.claim_ack_path = run_dir / "execution.claim-ack.json"
        self.terminal_intent_path = run_dir / "execution.terminal-intent.json"
        self.terminal_ack_path = run_dir / "execution.terminal-ack.json"
        self.terminal_path = self.terminal_ack_path
        self._anchor_head: str | None = None
        self._claim: ReservationClaimReceipt | None = None

    def _receipt_payload(self, kind: ReceiptKind) -> dict[str, object]:
        encoded = self.receipt_documents[kind]
        try:
            raw = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionBridgeViolation("receipt must be canonical JSON") from exc
        if canonical_json(raw).encode() != encoded:
            raise ExecutionBridgeViolation("receipt must be canonical JSON")
        expected = {
            "kind",
            "receipt_id",
            "subject_sha256",
            "signer_id",
            "signature_b64",
        }
        if kind is ReceiptKind.RUN_AUTHORIZATION:
            expected.add("authorization_context_sha256")
        payload = _closed(raw, expected, f"{kind.value} receipt")
        _require_text(payload["receipt_id"], f"{kind.value} receipt_id")
        _require_sha256(payload["subject_sha256"], f"{kind.value} subject_sha256")
        _require_text(payload["signer_id"], f"{kind.value} signer_id")
        signature_b64 = _require_text(
            payload["signature_b64"], f"{kind.value} signature_b64"
        )
        try:
            signature = base64.b64decode(signature_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ExecutionBridgeViolation(
                f"{kind.value} signature_b64 must be strict base64"
            ) from exc
        if not signature or base64.b64encode(signature).decode() != signature_b64:
            raise ExecutionBridgeViolation(
                f"{kind.value} signature_b64 must encode non-empty canonical bytes"
            )
        if kind is ReceiptKind.RUN_AUTHORIZATION:
            _require_sha256(
                payload["authorization_context_sha256"],
                "RUN_AUTHORIZATION authorization_context_sha256",
            )
        return payload

    def admit(self, envelope: ExecutionAdmission) -> None:
        if set(self.receipt_documents) != set(ReceiptKind):
            raise ExecutionBridgeViolation("exact six receipt documents are required")
        if (
            _sha256(self.active_manifest.read_bytes())
            != envelope.active_manifest_sha256
        ):
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
            if (
                _sha256(self.receipt_documents[kind])
                != envelope.six_receipt_digests[kind]
            ):
                raise ExecutionBridgeViolation(f"{kind.value} receipt digest drift")
        payloads = {kind: self._receipt_payload(kind) for kind in ReceiptKind}
        expected_subjects = {
            ReceiptKind.PROVIDER_CANARY: envelope.provider_binding.subject_sha256(),
            ReceiptKind.C7: envelope.c7_binding.subject_sha256(),
            ReceiptKind.EXECUTOR: envelope.components["executor_sha256"],
            ReceiptKind.INTEGRITY: envelope.components["integrity_sha256"],
            ReceiptKind.FREEZE: envelope.freeze_subject_digest,
            ReceiptKind.RUN_AUTHORIZATION: envelope.six_receipt_digests[
                ReceiptKind.FREEZE
            ],
        }
        receipt_ids = [payloads[kind]["receipt_id"] for kind in ReceiptKind]
        receipt_subjects = [payloads[kind]["subject_sha256"] for kind in ReceiptKind]
        receipt_digests = [envelope.six_receipt_digests[kind] for kind in ReceiptKind]
        if len(set(cast(list[str], receipt_ids))) != len(ReceiptKind):
            raise ExecutionBridgeViolation("receipt ids must be globally unique")
        if len(set(cast(list[str], receipt_subjects))) != len(ReceiptKind):
            raise ExecutionBridgeViolation("receipt subjects must be globally unique")
        if len(set(receipt_digests)) != len(ReceiptKind):
            raise ExecutionBridgeViolation("receipt digests must be globally unique")
        if (
            payloads[ReceiptKind.RUN_AUTHORIZATION]["authorization_context_sha256"]
            != envelope.envelope_core_sha256
        ):
            raise ExecutionBridgeViolation(
                "run authorization context does not bind the envelope core"
            )
        principals: set[str] = set()
        for kind in ReceiptKind:
            encoded = self.receipt_documents[kind]
            digest = _sha256(encoded)
            payload = payloads[kind]
            if (
                payload["kind"] != kind.value
                or payload["subject_sha256"] != expected_subjects[kind]
            ):
                raise ExecutionBridgeViolation(f"{kind.value} receipt subject drift")
            verification = self.receipt_verifier.verify(kind, encoded)
            role, purpose = _RECEIPT_ROLES[kind]
            if not isinstance(verification, ReceiptVerification) or (
                not verification.registry_verified
                or verification.role != role
                or verification.purpose != purpose
            ):
                raise ExecutionBridgeViolation(
                    "external receipt signature role/purpose verification failed"
                )
            if (
                verification.subject_sha256 != expected_subjects[kind]
                or verification.artifact_sha256 != digest
                or verification.principal_id != payload["signer_id"]
            ):
                raise ExecutionBridgeViolation(
                    "external receipt signature binding drift"
                )
            if verification.principal_id in principals:
                raise ExecutionBridgeViolation(
                    "receipt principals must be role-distinct"
                )
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
        self._anchor_head = self.workspace_probe.admit(
            envelope.mechanism_head,
            envelope.execution_code_head,
            envelope.components,
        )

    def _write_exclusive(self, path: Path, payload: object) -> None:
        encoded = (canonical_json(payload) + "\n").encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ExecutionBridgeViolation("execution attempt is permanently consumed")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ExecutionBridgeViolation("atomic seal temporary path exists") from exc
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ExecutionBridgeViolation(
                "execution attempt is permanently consumed"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _journal(self, payload: object) -> None:
        prior = self.journal_path.read_bytes() if self.journal_path.exists() else b""
        encoded = prior + (canonical_json(payload) + "\n").encode()
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal_path.with_name(
            f".{self.journal_path.name}.{os.getpid()}.tmp"
        )
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, self.journal_path)
        directory = os.open(
            self.journal_path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

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

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def _validate_claim(
        self,
        claim: ReservationClaimReceipt,
        envelope: ExecutionAdmission,
        claimant_nonce_sha256: str,
    ) -> None:
        expected = envelope.workflow_reservation
        if (
            not isinstance(claim, ReservationClaimReceipt)
            or not claim.registry_verified
            or claim.reservation_id != expected.reservation_id
            or claim.reservation_token_sha256 != expected.reservation_token_sha256
            or claim.attempt_epoch != expected.attempt_epoch
            or claim.cas_epoch != expected.cas_epoch
            or claim.run_id != envelope.run_id
            or claim.envelope_sha256 != envelope.envelope_sha256
            or claim.claimant_nonce_sha256 != claimant_nonce_sha256
        ):
            raise ExecutionBridgeViolation("workflow reservation claim binding failed")
        _require_sha256(claim.claimant_nonce_sha256, "claimant_nonce_sha256")
        if not claim.claimed:
            raise ExecutionBridgeViolation("workflow reservation already claimed")

    def _claim_intent(
        self, envelope: ExecutionAdmission, claimant_nonce_sha256: str
    ) -> dict[str, object]:
        return {
            "schema_version": "r-state-credit-1-claim-intent-v1",
            "run_id": envelope.run_id,
            "envelope_sha256": envelope.envelope_sha256,
            "reservation_id": envelope.workflow_reservation.reservation_id,
            "reservation_token_sha256": (
                envelope.workflow_reservation.reservation_token_sha256
            ),
            "attempt_epoch": envelope.workflow_reservation.attempt_epoch,
            "cas_epoch": envelope.workflow_reservation.cas_epoch,
            "claimant_nonce_sha256": claimant_nonce_sha256,
        }

    def _claimant_nonce_from_intent(self, envelope: ExecutionAdmission) -> str:
        try:
            encoded = self.claim_intent_path.read_bytes()
            raw = json.loads(encoded)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionBridgeViolation("claim intent is absent or invalid") from exc
        if (canonical_json(raw) + "\n").encode() != encoded:
            raise ExecutionBridgeViolation("claim intent must be canonical JSON")
        intent = _closed(
            raw,
            {
                "schema_version",
                "run_id",
                "envelope_sha256",
                "reservation_id",
                "reservation_token_sha256",
                "attempt_epoch",
                "cas_epoch",
                "claimant_nonce_sha256",
            },
            "claim intent",
        )
        expected = envelope.workflow_reservation
        nonce = _require_sha256(
            intent["claimant_nonce_sha256"], "claim intent claimant_nonce_sha256"
        )
        if (
            intent["schema_version"] != "r-state-credit-1-claim-intent-v1"
            or intent["run_id"] != envelope.run_id
            or intent["envelope_sha256"] != envelope.envelope_sha256
            or intent["reservation_id"] != expected.reservation_id
            or intent["reservation_token_sha256"] != expected.reservation_token_sha256
            or intent["attempt_epoch"] != expected.attempt_epoch
            or intent["cas_epoch"] != expected.cas_epoch
        ):
            raise ExecutionBridgeViolation("claim intent binding failed")
        return nonce

    def _reconcile_terminal_intent(self) -> None:
        if self._claim is None:
            raise ExecutionBridgeViolation("claim is absent during terminal reconcile")
        intent = json.loads(self.terminal_intent_path.read_text(encoding="utf-8"))
        state = _require_text(intent.get("state"), "terminal intent state")
        intent_sha256 = _sha256(self.terminal_intent_path.read_bytes())
        receipt = self.receipt_verifier.query_terminal(self._claim.claim_id)
        if receipt is None:
            receipt = self.receipt_verifier.terminalize(
                self._claim, state, intent_sha256
            )
        if not isinstance(receipt, ReservationTerminalReceipt) or (
            not receipt.registry_verified
            or not receipt.terminalized
            or receipt.claim_id != self._claim.claim_id
            or receipt.state != state
            or receipt.terminal_sha256 != intent_sha256
        ):
            raise ExecutionBridgeViolation("reservation terminal reconcile failed")
        self._fault("after_external_terminalize_before_ack")
        if not self.terminal_ack_path.exists():
            self._write_exclusive(
                self.terminal_ack_path,
                {
                    "schema_version": "r-state-credit-1-terminal-ack-v1",
                    "state": state,
                    "claim_id": self._claim.claim_id,
                    "terminal_intent_sha256": intent_sha256,
                    "registry_verified": True,
                },
            )
        self._journal(
            {
                "state": state,
                "event": "RESERVATION_TERMINALIZED",
                "terminal_intent_sha256": intent_sha256,
            }
        )

    def _seal_terminal(self, *, state: str, payload: dict[str, object]) -> None:
        if self._claim is None:
            raise ExecutionBridgeViolation("reservation claim is absent at terminal")
        artifact_sha256 = payload.get(
            "artifact_sha256",
            payload.get("raw_sha256", payload.get("partial_sha256")),
        )
        _require_sha256(artifact_sha256, "terminal artifact_sha256")
        terminal_intent = {
            "schema_version": "r-state-credit-1-terminal-intent-v1",
            "state": state,
            "claim_id": self._claim.claim_id,
            "reservation_token_sha256": self._claim.reservation_token_sha256,
            "attempt_epoch": self._claim.attempt_epoch,
            "cas_epoch": self._claim.cas_epoch,
            "artifact_sha256": artifact_sha256,
            **payload,
        }
        if not self.terminal_intent_path.exists():
            self._write_exclusive(self.terminal_intent_path, terminal_intent)
        self._fault("after_terminal_intent_before_external_terminalize")
        self._reconcile_terminal_intent()

    def _query_claim(
        self, envelope: ExecutionAdmission, claimant_nonce_sha256: str
    ) -> ReservationClaimReceipt | None:
        return self.receipt_verifier.query_claim(
            envelope.workflow_reservation.to_mapping(),
            envelope.run_id,
            envelope.envelope_sha256,
            claimant_nonce_sha256,
        )

    def _reconcile_existing(self, envelope: ExecutionAdmission) -> None:
        if self.terminal_ack_path.exists():
            raise ExecutionBridgeViolation(
                "execution attempt is permanently consumed and already reconciled"
            )
        if not (
            self.claim_intent_path.exists()
            or self.claim_ack_path.exists()
            or self.terminal_intent_path.exists()
            or self.lock_path.exists()
        ):
            return
        if not self.claim_intent_path.exists():
            raise ExecutionBridgeViolation(
                "claim intent is required for custody reconciliation"
            )
        claimant_nonce_sha256 = self._claimant_nonce_from_intent(envelope)
        claim = self._query_claim(envelope, claimant_nonce_sha256)
        if claim is None:
            claim = self.receipt_verifier.claim(
                envelope.workflow_reservation.to_mapping(),
                envelope.run_id,
                envelope.envelope_sha256,
                claimant_nonce_sha256,
            )
        self._validate_claim(claim, envelope, claimant_nonce_sha256)
        self._claim = claim
        if self.terminal_intent_path.exists():
            self._reconcile_terminal_intent()
        else:
            self._seal_terminal(
                state="INVALID_TERMINAL",
                payload={
                    "run_id": envelope.run_id,
                    "envelope_sha256": envelope.envelope_sha256,
                    "artifact_sha256": _sha256(self.claim_intent_path.read_bytes()),
                    "recovery_reason": "INCOMPLETE_CLAIM_OR_EXECUTION_STATE",
                },
            )
        raise ExecutionBridgeViolation(
            "execution custody was reconciled without provider"
        )

    def execute(self, envelope: ExecutionAdmission) -> ExecutionReceipt:
        self.admit(envelope)
        self._reconcile_existing(envelope)
        claimant_nonce_sha256 = _sha256(secrets.token_bytes(32))
        self._write_exclusive(
            self.claim_intent_path,
            self._claim_intent(envelope, claimant_nonce_sha256),
        )
        prior_claim = self._query_claim(envelope, claimant_nonce_sha256)
        if prior_claim is not None:
            self._validate_claim(prior_claim, envelope, claimant_nonce_sha256)
            raise ExecutionBridgeViolation("workflow reservation already claimed")
        claim = self.receipt_verifier.claim(
            envelope.workflow_reservation.to_mapping(),
            envelope.run_id,
            envelope.envelope_sha256,
            claimant_nonce_sha256,
        )
        self._validate_claim(claim, envelope, claimant_nonce_sha256)
        self._claim = claim
        self._fault("after_claim_before_lock")
        self._write_exclusive(
            self.claim_ack_path,
            {
                "schema_version": "r-state-credit-1-claim-ack-v1",
                "claim_id": claim.claim_id,
                "claim_intent_sha256": _sha256(self.claim_intent_path.read_bytes()),
                "registry_verified": True,
            },
        )
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
                                        raise ExecutionBridgeViolation(
                                            "workspace anchor is absent"
                                        )
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
                                            "actor_request_sha256": request_digest,
                                            "reserve": {
                                                "input_tokens": envelope.budget.max_input_tokens_per_call,
                                                "output_tokens": envelope.budget.max_output_tokens_per_call,
                                                "total_tokens": envelope.budget.max_total_tokens_per_call,
                                            },
                                        }
                                    )
                                    self._journal(
                                        {
                                            "state": "STARTED",
                                            "call_index": last_call_index,
                                            "actor_request_sha256": request_digest,
                                        }
                                    )
                                    provider_started = True
                                    provider_settled = False
                                    actor_response = self.actor.act(call.request)
                                    provider_settled = True
                                    receipt = actor_response.receipt
                                    if (
                                        receipt.provider_receipt_id
                                        in provider_receipt_ids
                                    ):
                                        raise ExecutionBridgeViolation(
                                            "provider receipt id must be globally unique"
                                        )
                                    provider_receipt_ids.add(
                                        receipt.provider_receipt_id
                                    )
                                    ledger.settle(
                                        input_tokens=receipt.input_tokens,
                                        output_tokens=receipt.output_tokens,
                                        total_tokens=receipt.total_tokens,
                                        cost_status=receipt.cost_status,
                                        cost_amount_microunits=(
                                            receipt.cost_amount_microunits
                                        ),
                                        cost_currency=receipt.cost_currency,
                                    )
                                    receipt_mapping = {
                                        "provider_receipt_id": receipt.provider_receipt_id,
                                        "provider_id": receipt.provider_id,
                                        "model_id": receipt.model_id,
                                        "model_revision": receipt.model_revision,
                                        "actor_request_sha256": receipt.actor_request_sha256,
                                        "provider_request_sha256": receipt.provider_request_sha256,
                                        "provider_response_sha256": receipt.provider_response_sha256,
                                        "raw_output_sha256": receipt.raw_output_sha256,
                                        "input_tokens": receipt.input_tokens,
                                        "output_tokens": receipt.output_tokens,
                                        "total_tokens": receipt.total_tokens,
                                        "cost_status": receipt.cost_status.value,
                                        "cost_amount_microunits": receipt.cost_amount_microunits,
                                        "cost_currency": receipt.cost_currency,
                                        "latency_ms": receipt.latency_ms,
                                        "timeout_seconds": receipt.timeout_seconds,
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
                                    self._check_c7()
                                    arm_id, resolved = blinding.resolve_response(
                                        ordinal,
                                        actor_response.response,
                                        call.session_label,
                                    )
                                    loss, weight = episode.score_action(resolved.action)
                                    row = InternalSealedRawRow.from_mapping(
                                        {
                                            "run_id": envelope.run_id,
                                            "call_index": last_call_index,
                                            "episode_id": f"rsc1:{family.value.lower()}:{seed}",
                                            "family": family.value,
                                            "seed": seed,
                                            "checkpoint_id": checkpoint.value,
                                            "arm_id": arm_id.value,
                                            "actor_request_sha256": request_digest,
                                            "provider_request_sha256": receipt.provider_request_sha256,
                                            "provider_receipt_id": receipt.provider_receipt_id,
                                            "provider_receipt_sha256": receipt_digest,
                                            "provider_response_sha256": receipt.provider_response_sha256,
                                            "raw_output_sha256": receipt.raw_output_sha256,
                                            "model_revision": receipt.model_revision,
                                            "input_tokens": receipt.input_tokens,
                                            "output_tokens": receipt.output_tokens,
                                            "total_tokens": receipt.total_tokens,
                                            "cost_status": receipt.cost_status.value,
                                            "cost_amount_microunits": receipt.cost_amount_microunits,
                                            "cost_currency": receipt.cost_currency,
                                            "latency_ms": receipt.latency_ms,
                                            "timeout_seconds": receipt.timeout_seconds,
                                            "action": resolved.action.value,
                                            "loss_code": loss.value,
                                            "loss_weight": weight,
                                        }
                                    ).to_mapping()
                                    rows.append(row)
                                    provider_started = False
                            episode.step(episode._default_policy(observation, episode))
                    finally:
                        episode.cleanup()
            if (
                ledger.calls != EXPECTED_PROVIDER_CALLS
                or len(rows) != EXPECTED_PROVIDER_CALLS
            ):
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
            assert_raw_only(payload)
            self._write_exclusive(self.raw_path, payload)
            self._journal(
                {
                    "state": "SEALED_RAW",
                    "row_count": len(rows),
                    "raw_sha256": _sha256(self.raw_path.read_bytes()),
                }
            )
            self._seal_terminal(
                state="SEALED_RAW",
                payload={
                    "run_id": envelope.run_id,
                    "envelope_sha256": envelope.envelope_sha256,
                    "row_count": len(rows),
                    "raw_sha256": _sha256(self.raw_path.read_bytes()),
                },
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
            self._seal_terminal(
                state=state,
                payload={
                    "run_id": envelope.run_id,
                    "envelope_sha256": envelope.envelope_sha256,
                    "row_count": len(rows),
                    "partial_sha256": _sha256(self.partial_path.read_bytes()),
                },
            )
            raise
