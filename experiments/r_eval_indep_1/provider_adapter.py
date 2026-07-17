"""Canary-backed provider bindings for R-EVAL-INDEP-1 successor V1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .contracts import canonical_digest
from .freeze_run_context import (
    ReceiptVerifier,
    SignedReceipt,
    VerifiedReceiptIdentity,
    verify_receipt_identity,
)
from .native_arm_plan import NativeArmPlan


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_ALIASES = {"latest", "stable", "default", "production", "current"}


class AmbiguousEffectError(RuntimeError):
    """Provider accepted a request but the terminal effect is unknown."""


@dataclass(frozen=True, slots=True)
class ArmProviderBinding:
    route_id: str
    arm_id: str
    provider: str
    endpoint_origin_sha256: str
    model_immutable_revision: str
    model_family: str
    model_lineage: str
    system_prompt_sha256: str
    tool_schema_sha256: str
    decoding_config_sha256: str
    credential_ref_sha256: str

    def __post_init__(self) -> None:
        if self.route_id != "R-EVAL-INDEP-1":
            raise ValueError("provider binding route must be R-EVAL-INDEP-1")
        if self.arm_id not in {"A1", "A2", "A3", "A4"}:
            raise ValueError("provider binding cannot target mechanical/unknown arm")
        for field in ("provider", "model_family", "model_lineage"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} is required")
        revision = self.model_immutable_revision.strip()
        if not revision or revision.lower() in _MUTABLE_ALIASES:
            raise ValueError("model_immutable_revision cannot be a mutable alias")
        for field in (
            "endpoint_origin_sha256",
            "system_prompt_sha256",
            "tool_schema_sha256",
            "decoding_config_sha256",
            "credential_ref_sha256",
        ):
            if not _SHA256.fullmatch(getattr(self, field)):
                raise ValueError(f"{field} must be sha256")

    def to_mapping(self) -> dict[str, str]:
        return {field: str(getattr(self, field)) for field in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ArmProviderBinding:
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected or not all(
            isinstance(value[field], str) for field in expected
        ):
            raise ValueError("ArmProviderBinding is a closed string contract")
        return cls(**{field: str(value[field]) for field in expected})

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class ProviderCanaryReceipt:
    arm_id: str
    binding_sha256: str
    served_provider: str
    served_model_immutable_revision: str
    served_model_family: str
    served_model_lineage: str
    canary_request_sha256: str
    canary_response_sha256: str
    signed_receipt: SignedReceipt

    def __post_init__(self) -> None:
        if self.arm_id not in {"A1", "A2", "A3", "A4"}:
            raise ValueError("canary arm is invalid")
        for field in (
            "binding_sha256",
            "canary_request_sha256",
            "canary_response_sha256",
        ):
            if not _SHA256.fullmatch(getattr(self, field)):
                raise ValueError(f"{field} must be sha256")
        for field in (
            "served_provider",
            "served_model_immutable_revision",
            "served_model_family",
            "served_model_lineage",
        ):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} is required")

    def subject_mapping(self) -> dict[str, str]:
        return {
            "arm_id": self.arm_id,
            "binding_sha256": self.binding_sha256,
            "served_provider": self.served_provider,
            "served_model_immutable_revision": self.served_model_immutable_revision,
            "served_model_family": self.served_model_family,
            "served_model_lineage": self.served_model_lineage,
            "canary_request_sha256": self.canary_request_sha256,
            "canary_response_sha256": self.canary_response_sha256,
        }

    def digest(self) -> str:
        return canonical_digest(self.subject_mapping())


_VERIFIED_BANK = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedProviderBank:
    bindings: Mapping[str, ArmProviderBinding]
    canaries: Mapping[str, ProviderCanaryReceipt]
    identities: Mapping[str, VerifiedReceiptIdentity]
    sha256: str
    _token: object

    @classmethod
    def _create(
        cls,
        bindings: Mapping[str, ArmProviderBinding],
        canaries: Mapping[str, ProviderCanaryReceipt],
        identities: Mapping[str, VerifiedReceiptIdentity],
    ) -> VerifiedProviderBank:
        instance = object.__new__(cls)
        frozen_bindings = MappingProxyType(dict(sorted(bindings.items())))
        frozen_canaries = MappingProxyType(dict(sorted(canaries.items())))
        frozen_identities = MappingProxyType(dict(sorted(identities.items())))
        digest = canonical_digest(
            {
                "bindings": {
                    arm: item.to_mapping() for arm, item in frozen_bindings.items()
                },
                "canaries": {
                    arm: {
                        **item.subject_mapping(),
                        "signed_receipt_sha256": item.signed_receipt.digest(),
                        "verified_identity": frozen_identities[arm].to_mapping(),
                    }
                    for arm, item in frozen_canaries.items()
                },
            }
        )
        object.__setattr__(instance, "bindings", frozen_bindings)
        object.__setattr__(instance, "canaries", frozen_canaries)
        object.__setattr__(instance, "identities", frozen_identities)
        object.__setattr__(instance, "sha256", digest)
        object.__setattr__(instance, "_token", _VERIFIED_BANK)
        return instance

    def assert_verified(self) -> None:
        if self._token is not _VERIFIED_BANK:
            raise ValueError("unverified provider bank")


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    run_id: str
    case_id: str
    arm_id: str
    sample_index: int
    public_case_sha256: str
    public_manifest_sha256: str
    execution_permit_sha256: str
    provider_binding_sha256: str
    provider_canary_sha256: str
    provider_canary_receipt_sha256: str
    endpoint_origin_sha256: str
    model_immutable_revision: str
    system_prompt_sha256: str
    tool_schema_sha256: str
    decoding_config_sha256: str
    credential_ref_sha256: str

    def digest(self) -> str:
        return canonical_digest(
            {field: getattr(self, field) for field in self.__dataclass_fields__}
        )


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    request_sha256: str
    provider_binding_sha256: str
    provider_canary_sha256: str
    provider_canary_receipt_sha256: str
    endpoint_origin_sha256: str
    model_immutable_revision: str
    system_prompt_sha256: str
    tool_schema_sha256: str
    decoding_config_sha256: str
    credential_ref_sha256: str
    disposition: str
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    latency_ms: int
    provider_response_id_sha256: str
    raw_response_sha256: str


class ProviderAdapter(Protocol):
    def review(self, *, request: ProviderRequest) -> ProviderResponse: ...


def verify_provider_bank(
    plan: NativeArmPlan,
    bindings: tuple[ArmProviderBinding, ...],
    canaries: tuple[ProviderCanaryReceipt, ...],
    verifier: ReceiptVerifier,
) -> VerifiedProviderBank:
    if plan.route_id != "R-EVAL-INDEP-1" or plan.case_count != 74:
        raise ValueError("provider bank requires the fixed R-EVAL plan")
    bank = {item.arm_id: item for item in bindings}
    canary_bank = {item.arm_id: item for item in canaries}
    expected = {"A1", "A2", "A3", "A4"}
    if len(bank) != len(bindings) or set(bank) != expected:
        raise ValueError("provider bank requires exact A1-A4 coverage")
    if len(canary_bank) != len(canaries) or set(canary_bank) != expected:
        raise ValueError("provider canaries require exact A1-A4 coverage")
    identities: dict[str, VerifiedReceiptIdentity] = {}
    for arm_id, binding in bank.items():
        canary = canary_bank[arm_id]
        if canary.binding_sha256 != binding.digest():
            raise ValueError("provider canary binding drift")
        receipt = canary.signed_receipt
        if (
            receipt.role != "PROVIDER_CANARY_CUSTODIAN"
            or receipt.subject_sha256 != canary.digest()
        ):
            raise ValueError("provider canary receipt subject/role drift")
        identities[arm_id] = verify_receipt_identity(verifier, receipt)
        if (
            canary.served_provider,
            canary.served_model_immutable_revision,
            canary.served_model_family,
            canary.served_model_lineage,
        ) != (
            binding.provider,
            binding.model_immutable_revision,
            binding.model_family,
            binding.model_lineage,
        ):
            raise ValueError("provider canary served identity drift")
    a1, a2, a3, a4 = (canary_bank[f"A{i}"] for i in range(1, 5))
    if (
        a1.served_provider,
        a1.served_model_immutable_revision,
        a1.served_model_family,
        a1.served_model_lineage,
    ) != (
        a2.served_provider,
        a2.served_model_immutable_revision,
        a2.served_model_family,
        a2.served_model_lineage,
    ):
        raise ValueError("A1/A2 canaries must prove the same checkpoint")
    if bank["A1"].system_prompt_sha256 == bank["A2"].system_prompt_sha256:
        raise ValueError("A1/A2 require a prompt variant")
    if (
        a3.served_model_family,
        a3.served_model_lineage,
    ) != (
        a1.served_model_family,
        a1.served_model_lineage,
    ) or a3.served_model_immutable_revision == a1.served_model_immutable_revision:
        raise ValueError("A3 canary must prove same-family different-checkpoint")
    if a4.served_model_lineage == a1.served_model_lineage:
        raise ValueError("A4 canary must prove cross-lineage")
    return VerifiedProviderBank._create(bank, canary_bank, identities)
