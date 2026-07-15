from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Protocol

from agent_os_contracts import (
    CandidateEvaluationDisposition,
    CandidateEvaluationReceipt,
    CandidatePromotionDisposition,
    DomainCandidate,
    content_digest,
)


@dataclass(frozen=True, slots=True)
class PromotionReduction:
    disposition: CandidatePromotionDisposition
    reason_codes: tuple[str, ...]


class ProductPromotionPolicy(Protocol):
    @property
    def version(self) -> str: ...

    @property
    def digest(self) -> str: ...

    def reduce(
        self,
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
    ) -> PromotionReduction: ...


PROMOTION_POLICY_V1_SPEC = {
    "schema": "ADM-P3-PROMOTION-POLICY-SPEC-V1",
    "version": "ADM-P3-POLICY-V1",
    "input": "FULL_ADM_P2_RECEIPT_CHAIN",
    "reject_if": "UNREACHABLE_WITH_ADM_P2_V1",
    "promote_if": "UNREACHABLE_WITH_ADM_P2_V1",
    "default_disposition": "DEFER",
    "required_missing_proofs": (
        "EVIDENCE_BYTES_CUSTODY",
        "EVALUATOR_INDEPENDENCE",
    ),
}
PROMOTION_POLICY_V1_DIGEST = content_digest(PROMOTION_POLICY_V1_SPEC)


@dataclass(frozen=True, slots=True)
class PromotionPolicyV1:
    version: str = "ADM-P3-POLICY-V1"
    digest: str = PROMOTION_POLICY_V1_DIGEST

    def reduce(
        self,
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
    ) -> PromotionReduction:
        del candidate
        dispositions = {receipt.draft.disposition for receipt in receipts}
        reasons: list[str] = []
        if not receipts:
            reasons.append("NO_EVALUATION_RECEIPTS")
        if CandidateEvaluationDisposition.EVALUATOR_FAIL in dispositions:
            reasons.append("RECORDED_EVALUATOR_FAIL_UNADJUDICATED")
        if CandidateEvaluationDisposition.INVALID in dispositions:
            reasons.append("EVALUATION_INVALID")
        if CandidateEvaluationDisposition.UNRESOLVED in dispositions:
            reasons.append("EVALUATION_UNRESOLVED")
        reasons.extend(
            (
                "EVIDENCE_BYTES_CUSTODY_UNPROVEN",
                "EVALUATOR_INDEPENDENCE_UNPROVEN",
                "PROMOTION_PROOFS_UNAVAILABLE_IN_ADM_P2",
            )
        )
        return PromotionReduction(
            disposition=CandidatePromotionDisposition.DEFER,
            reason_codes=tuple(reasons),
        )


class PromotionPolicyRegistry:
    def __init__(self, policies: Iterable[ProductPromotionPolicy]) -> None:
        registered: dict[str, tuple[str, ProductPromotionPolicy]] = {}
        for policy in policies:
            if policy.version in registered:
                raise ValueError(
                    f"duplicate promotion policy version: {policy.version}"
                )
            registered[policy.version] = (policy.digest, policy)
        if not registered:
            raise ValueError("at least one promotion policy must be registered")
        self._policies: Mapping[str, tuple[str, ProductPromotionPolicy]] = (
            MappingProxyType(registered)
        )

    def resolve(self, version: str, digest: str) -> ProductPromotionPolicy:
        registered = self._policies.get(version)
        if registered is None:
            raise KeyError(f"promotion policy version is not registered: {version}")
        registered_digest, policy = registered
        if digest != registered_digest or policy.digest != registered_digest:
            raise KeyError(f"promotion policy digest mismatch for version: {version}")
        return policy

    def only(self) -> ProductPromotionPolicy:
        if len(self._policies) != 1:
            raise RuntimeError(
                "promotion policy registry does not contain exactly one policy"
            )
        _, policy = next(iter(self._policies.values()))
        return policy
