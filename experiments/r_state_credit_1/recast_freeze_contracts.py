"""Typed, non-authorizing contracts for R-STATE successor F."""

from __future__ import annotations

from dataclasses import dataclass

from experiments.r_state_credit_1.contracts import ScenarioFamily


def _digest(value: str | None, label: str) -> None:
    if value is None:
        return
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ExecutionBundle:
    schema_version: str
    reviewed_mechanism_head: str
    provider_binding_sha256: str
    runner_sha256: str
    scorer_sha256: str
    c7_schema_sha256: str
    prereg_sha256: str
    future_freeze_receipt_sha256: str | None
    run_authorization_freeze_sha256: str | None
    expected_provider_calls: int
    max_total_input_tokens: int
    max_total_output_tokens: int
    required_family_strata: tuple[str, ...] = tuple(x.value for x in ScenarioFamily)
    required_perturbations: str = "GENERATED_PER_FAMILY_NOT_EVERY_INSTANCE"
    integrity_umbrella: str = "INTEGRITY_VALID"

    def __post_init__(self) -> None:
        if self.schema_version != "r-state-credit-1-successor-f-execution-v1":
            raise ValueError("successor execution schema drift")
        if self.reviewed_mechanism_head != "0ca38aa3491161fa115c0b58685cf408e5be106b":
            raise ValueError("reviewed mechanism base drift")
        for name in (
            "provider_binding_sha256",
            "runner_sha256",
            "scorer_sha256",
            "c7_schema_sha256",
            "prereg_sha256",
            "future_freeze_receipt_sha256",
            "run_authorization_freeze_sha256",
        ):
            _digest(getattr(self, name), name)
        if self.required_family_strata != tuple(x.value for x in ScenarioFamily):
            raise ValueError("family strata drift")
        if self.required_perturbations != "GENERATED_PER_FAMILY_NOT_EVERY_INSTANCE":
            raise ValueError("family perturbation claim overreach")
        if self.integrity_umbrella != "INTEGRITY_VALID":
            raise ValueError("integrity umbrella drift")
        if self.expected_provider_calls != 2240:
            raise ValueError("provider call budget must equal exact 2240-row coverage")
        if (
            not isinstance(self.max_total_input_tokens, int)
            or self.max_total_input_tokens <= 0
            or not isinstance(self.max_total_output_tokens, int)
            or self.max_total_output_tokens <= 0
        ):
            raise ValueError("token budgets must be positive integers")
        if self.run_authorization_freeze_sha256 is not None and (
            self.future_freeze_receipt_sha256 != self.run_authorization_freeze_sha256
        ):
            raise ValueError("run authorization must reference the future freeze")


@dataclass(frozen=True, slots=True)
class SuccessorReadiness:
    status: str
    blockers: tuple[str, ...]

    @classmethod
    def evaluate(cls, bundle: ExecutionBundle) -> SuccessorReadiness:
        blockers: list[str] = []
        if bundle.future_freeze_receipt_sha256 is None:
            blockers.append("future freeze receipt absent")
        if bundle.run_authorization_freeze_sha256 is None:
            blockers.append("run authorization absent")
        return cls(
            status="READY" if not blockers else "NOT_READY", blockers=tuple(blockers)
        )
