"""Freeze-time provider bindings for the R-EVAL-INDEP-1 successor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .native_arm_plan import NativeArmPlan


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MUTABLE_ALIASES = {"latest", "stable", "default", "production", "current"}


class AmbiguousEffectError(RuntimeError):
    """The provider accepted the request but its terminal effect is unknown."""


@dataclass(frozen=True)
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
        if (
            not self.provider.strip()
            or not self.model_family.strip()
            or not self.model_lineage.strip()
        ):
            raise ValueError("provider, family, and lineage are required")
        revision = self.model_immutable_revision.strip()
        if not revision or revision.lower() in _MUTABLE_ALIASES:
            raise ValueError("model_immutable_revision cannot be a mutable alias")
        for name in (
            "endpoint_origin_sha256",
            "system_prompt_sha256",
            "tool_schema_sha256",
            "decoding_config_sha256",
            "credential_ref_sha256",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be sha256")

    def to_mapping(self) -> dict[str, str]:
        return {
            "route_id": self.route_id,
            "arm_id": self.arm_id,
            "provider": self.provider,
            "endpoint_origin_sha256": self.endpoint_origin_sha256,
            "model_immutable_revision": self.model_immutable_revision,
            "model_family": self.model_family,
            "model_lineage": self.model_lineage,
            "system_prompt_sha256": self.system_prompt_sha256,
            "tool_schema_sha256": self.tool_schema_sha256,
            "decoding_config_sha256": self.decoding_config_sha256,
            "credential_ref_sha256": self.credential_ref_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ArmProviderBinding:
        expected = {
            "route_id",
            "arm_id",
            "provider",
            "endpoint_origin_sha256",
            "model_immutable_revision",
            "model_family",
            "model_lineage",
            "system_prompt_sha256",
            "tool_schema_sha256",
            "decoding_config_sha256",
            "credential_ref_sha256",
        }
        if set(value) != expected or not all(
            isinstance(value[field], str) for field in expected
        ):
            raise ValueError("ArmProviderBinding is a closed string contract")
        return cls(**{field: str(value[field]) for field in expected})


@dataclass(frozen=True)
class ProviderResponse:
    disposition: str
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    latency_ms: int
    provider_response_id_sha256: str
    raw_response_sha256: str


class ProviderAdapter(Protocol):
    def review(
        self, *, binding: ArmProviderBinding, case: object, sample_index: int
    ) -> ProviderResponse: ...


def validate_provider_bank(
    plan: NativeArmPlan,
    bindings: tuple[ArmProviderBinding, ...],
) -> dict[str, ArmProviderBinding]:
    if plan.route_id != "R-EVAL-INDEP-1":
        raise ValueError("wrong plan route")
    bank = {binding.arm_id: binding for binding in bindings}
    if len(bank) != len(bindings):
        raise ValueError("duplicate arm provider binding")
    if set(bank) != {"A1", "A2", "A3", "A4"}:
        raise ValueError("provider bank requires exact A1-A4 coverage")
    a1, a2, a3, a4 = (bank[f"A{i}"] for i in range(1, 5))
    if (
        a1.provider,
        a1.endpoint_origin_sha256,
        a1.model_immutable_revision,
        a1.model_family,
        a1.model_lineage,
        a1.tool_schema_sha256,
        a1.decoding_config_sha256,
    ) != (
        a2.provider,
        a2.endpoint_origin_sha256,
        a2.model_immutable_revision,
        a2.model_family,
        a2.model_lineage,
        a2.tool_schema_sha256,
        a2.decoding_config_sha256,
    ):
        raise ValueError("A1/A2 must use the same checkpoint")
    if a1.system_prompt_sha256 == a2.system_prompt_sha256:
        raise ValueError("A1/A2 must use a prompt variant")
    if (a3.model_family, a3.model_lineage) != (
        a1.model_family,
        a1.model_lineage,
    ) or a3.model_immutable_revision == a1.model_immutable_revision:
        raise ValueError("A3 must use the same family and a different checkpoint")
    if a4.model_lineage == a1.model_lineage:
        raise ValueError("A4 must be cross-lineage")
    return bank
