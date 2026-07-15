"""API-only typed reviewer protocol for R-EVAL-INDEP-1.

This module defines contracts and collection orchestration only.  It contains no
concrete provider client, credential lookup, CLI transport, freeze operation, or
result-bearing entry point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import (
    ContractValidationError,
    ReviewDisposition,
    ReviewerIdentity,
    ReviewResponse,
    canonical_digest,
    validate_response_matrix,
)
from .corpus_contracts import PublicCaseManifest


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARM_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SCHEMA_VERSION = "r-eval-indep-1-native-review-v1"


class ReviewCollectionError(RuntimeError):
    """Collection was refused before a complete bound matrix existed."""


class APITransport(str, Enum):
    API_ONLY = "API_ONLY"


class APIProtocol(str, Enum):
    RESPONSES_API = "RESPONSES_API"
    CHAT_COMPLETIONS_API = "CHAT_COMPLETIONS_API"
    MESSAGES_API = "MESSAGES_API"
    TYPED_HTTP_API = "TYPED_HTTP_API"


class C7Decision(str, Enum):
    ALLOW = "ALLOW"
    HALT = "HALT"


def _closed(
    value: Mapping[str, Any], expected: set[str], contract_name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{contract_name} requires an object")
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown or missing:
        raise ContractValidationError(
            f"{contract_name} field mismatch: unknown={unknown}, missing={missing}"
        )
    return dict(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} requires a non-empty string")
    return value


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _SHA256.fullmatch(text):
        raise ContractValidationError(f"{field} requires lowercase sha256")
    return text


def _arm(value: Any) -> str:
    text = _text(value, "arm_id")
    if not _ARM_ID.fullmatch(text):
        raise ContractValidationError("arm_id has invalid characters")
    return text


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{field} requires a non-negative integer")
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractValidationError(f"{field} requires an array")
    return tuple(_text(item, field) for item in value)


@dataclass(frozen=True, slots=True)
class ReviewerEndpointBinding:
    arm_id: str
    reviewer_identity: ReviewerIdentity
    transport: APITransport
    api_protocol: APIProtocol
    credential_ref_sha256: str
    endpoint_origin_sha256: str
    public_cases_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReviewerEndpointBinding:
        payload = _closed(
            value,
            {
                "arm_id",
                "reviewer_identity",
                "transport",
                "api_protocol",
                "credential_ref_sha256",
                "endpoint_origin_sha256",
                "public_cases_sha256",
            },
            cls.__name__,
        )
        try:
            transport = APITransport(payload["transport"])
            protocol = APIProtocol(payload["api_protocol"])
        except (TypeError, ValueError) as error:
            raise ContractValidationError("unsupported API transport/protocol") from error
        identity_value = payload["reviewer_identity"]
        if not isinstance(identity_value, Mapping):
            raise ContractValidationError("reviewer_identity requires an object")
        identity = ReviewerIdentity.from_mapping(identity_value)
        endpoint_class = identity.endpoint_class.lower()
        if "api" not in endpoint_class or any(
            token in endpoint_class for token in ("cli", "shell", "subprocess")
        ):
            raise ContractValidationError(
                "reviewer endpoint_class must identify an API surface"
            )
        return cls(
            arm_id=_arm(payload["arm_id"]),
            reviewer_identity=identity,
            transport=transport,
            api_protocol=protocol,
            credential_ref_sha256=_sha(
                payload["credential_ref_sha256"], "credential_ref_sha256"
            ),
            endpoint_origin_sha256=_sha(
                payload["endpoint_origin_sha256"], "endpoint_origin_sha256"
            ),
            public_cases_sha256=_sha(
                payload["public_cases_sha256"], "public_cases_sha256"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "reviewer_identity": self.reviewer_identity.to_mapping(),
            "transport": self.transport.value,
            "api_protocol": self.api_protocol.value,
            "credential_ref_sha256": self.credential_ref_sha256,
            "endpoint_origin_sha256": self.endpoint_origin_sha256,
            "public_cases_sha256": self.public_cases_sha256,
        }

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class CollectionPermit:
    run_id: str
    prereg_lock_sha256: str
    exact_manifest_sha256: str
    independent_review_sha256: str
    run_authority_id: str
    c7_authority_id: str
    correction_epoch: int
    c7_decision: C7Decision
    single_run_sequence: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CollectionPermit:
        payload = _closed(
            value,
            {
                "run_id",
                "prereg_lock_sha256",
                "exact_manifest_sha256",
                "independent_review_sha256",
                "run_authority_id",
                "c7_authority_id",
                "correction_epoch",
                "c7_decision",
                "single_run_sequence",
            },
            cls.__name__,
        )
        try:
            decision = C7Decision(payload["c7_decision"])
        except (TypeError, ValueError) as error:
            raise ContractValidationError("unsupported C7 decision") from error
        run_authority = _text(payload["run_authority_id"], "run_authority_id")
        c7_authority = _text(payload["c7_authority_id"], "c7_authority_id")
        if run_authority == c7_authority:
            raise ContractValidationError("run authority and C7 authority must differ")
        sequence = _nonnegative_int(
            payload["single_run_sequence"], "single_run_sequence"
        )
        if sequence != 1:
            raise ContractValidationError("only the predeclared one-run sequence 1 is valid")
        return cls(
            run_id=_text(payload["run_id"], "run_id"),
            prereg_lock_sha256=_sha(
                payload["prereg_lock_sha256"], "prereg_lock_sha256"
            ),
            exact_manifest_sha256=_sha(
                payload["exact_manifest_sha256"], "exact_manifest_sha256"
            ),
            independent_review_sha256=_sha(
                payload["independent_review_sha256"],
                "independent_review_sha256",
            ),
            run_authority_id=run_authority,
            c7_authority_id=c7_authority,
            correction_epoch=_nonnegative_int(
                payload["correction_epoch"], "correction_epoch"
            ),
            c7_decision=decision,
            single_run_sequence=sequence,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "prereg_lock_sha256": self.prereg_lock_sha256,
            "exact_manifest_sha256": self.exact_manifest_sha256,
            "independent_review_sha256": self.independent_review_sha256,
            "run_authority_id": self.run_authority_id,
            "c7_authority_id": self.c7_authority_id,
            "correction_epoch": self.correction_epoch,
            "c7_decision": self.c7_decision.value,
            "single_run_sequence": self.single_run_sequence,
        }

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    run_id: str
    case_id: str
    arm_id: str
    provider_family: str
    served_model_id: str
    model_version: str
    api_protocol: APIProtocol
    endpoint_binding_sha256: str
    reviewer_identity_digest: str
    public_manifest_sha256: str
    system_prompt_sha256: str
    task_prompt_sha256: str
    tool_profile_sha256: str
    context_manifest_sha256: str
    decoding_config_sha256: str
    collection_permit_sha256: str
    request_sha256: str

    @classmethod
    def build(
        cls,
        *,
        permit: CollectionPermit,
        public_case: PublicCaseManifest,
        endpoint: ReviewerEndpointBinding,
    ) -> ReviewRequest:
        identity = endpoint.reviewer_identity
        unsigned: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": permit.run_id,
            "case_id": public_case.case_id,
            "arm_id": endpoint.arm_id,
            "provider_family": identity.provider_family,
            "served_model_id": identity.served_model_id,
            "model_version": identity.model_version,
            "api_protocol": endpoint.api_protocol.value,
            "endpoint_binding_sha256": endpoint.digest(),
            "reviewer_identity_digest": identity.digest(),
            "public_manifest_sha256": public_case.public_manifest_sha256,
            "system_prompt_sha256": identity.system_prompt_sha256,
            "task_prompt_sha256": identity.task_prompt_sha256,
            "tool_profile_sha256": identity.tool_profile_sha256,
            "context_manifest_sha256": identity.context_manifest_sha256,
            "decoding_config_sha256": identity.decoding_config_sha256,
            "collection_permit_sha256": permit.digest(),
        }
        return cls(
            run_id=permit.run_id,
            case_id=public_case.case_id,
            arm_id=endpoint.arm_id,
            provider_family=identity.provider_family,
            served_model_id=identity.served_model_id,
            model_version=identity.model_version,
            api_protocol=endpoint.api_protocol,
            endpoint_binding_sha256=endpoint.digest(),
            reviewer_identity_digest=identity.digest(),
            public_manifest_sha256=public_case.public_manifest_sha256,
            system_prompt_sha256=identity.system_prompt_sha256,
            task_prompt_sha256=identity.task_prompt_sha256,
            tool_profile_sha256=identity.tool_profile_sha256,
            context_manifest_sha256=identity.context_manifest_sha256,
            decoding_config_sha256=identity.decoding_config_sha256,
            collection_permit_sha256=permit.digest(),
            request_sha256=canonical_digest(unsigned),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "arm_id": self.arm_id,
            "provider_family": self.provider_family,
            "served_model_id": self.served_model_id,
            "model_version": self.model_version,
            "api_protocol": self.api_protocol.value,
            "endpoint_binding_sha256": self.endpoint_binding_sha256,
            "reviewer_identity_digest": self.reviewer_identity_digest,
            "public_manifest_sha256": self.public_manifest_sha256,
            "system_prompt_sha256": self.system_prompt_sha256,
            "task_prompt_sha256": self.task_prompt_sha256,
            "tool_profile_sha256": self.tool_profile_sha256,
            "context_manifest_sha256": self.context_manifest_sha256,
            "decoding_config_sha256": self.decoding_config_sha256,
            "collection_permit_sha256": self.collection_permit_sha256,
            "request_sha256": self.request_sha256,
        }


@dataclass(frozen=True, slots=True)
class NativeReviewResponse:
    case_id: str
    arm_id: str
    request_sha256: str
    endpoint_binding_sha256: str
    reviewer_identity_digest: str
    public_manifest_sha256: str
    disposition: ReviewDisposition
    p_candidate_valid_micros: int
    blocking_findings: tuple[str, ...]
    generated_test_patch: str | None
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    latency_ms: int
    provider_response_id_sha256: str
    raw_response_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> NativeReviewResponse:
        payload = _closed(
            value,
            {
                "case_id",
                "arm_id",
                "request_sha256",
                "endpoint_binding_sha256",
                "reviewer_identity_digest",
                "public_manifest_sha256",
                "disposition",
                "p_candidate_valid_micros",
                "blocking_findings",
                "generated_test_patch",
                "input_tokens",
                "output_tokens",
                "cost_microusd",
                "latency_ms",
                "provider_response_id_sha256",
                "raw_response_sha256",
            },
            cls.__name__,
        )
        try:
            disposition = ReviewDisposition(payload["disposition"])
        except (TypeError, ValueError) as error:
            raise ContractValidationError("unsupported review disposition") from error
        probability = _nonnegative_int(
            payload["p_candidate_valid_micros"], "p_candidate_valid_micros"
        )
        if probability > 1_000_000:
            raise ContractValidationError(
                "p_candidate_valid_micros must be between 0 and 1000000"
            )
        generated = payload["generated_test_patch"]
        if generated is not None and not isinstance(generated, str):
            raise ContractValidationError("generated_test_patch must be string or null")
        return cls(
            case_id=_text(payload["case_id"], "case_id"),
            arm_id=_arm(payload["arm_id"]),
            request_sha256=_sha(payload["request_sha256"], "request_sha256"),
            endpoint_binding_sha256=_sha(
                payload["endpoint_binding_sha256"], "endpoint_binding_sha256"
            ),
            reviewer_identity_digest=_sha(
                payload["reviewer_identity_digest"], "reviewer_identity_digest"
            ),
            public_manifest_sha256=_sha(
                payload["public_manifest_sha256"], "public_manifest_sha256"
            ),
            disposition=disposition,
            p_candidate_valid_micros=probability,
            blocking_findings=_strings(
                payload["blocking_findings"], "blocking_findings"
            ),
            generated_test_patch=generated,
            input_tokens=_nonnegative_int(payload["input_tokens"], "input_tokens"),
            output_tokens=_nonnegative_int(
                payload["output_tokens"], "output_tokens"
            ),
            cost_microusd=_nonnegative_int(
                payload["cost_microusd"], "cost_microusd"
            ),
            latency_ms=_nonnegative_int(payload["latency_ms"], "latency_ms"),
            provider_response_id_sha256=_sha(
                payload["provider_response_id_sha256"],
                "provider_response_id_sha256",
            ),
            raw_response_sha256=_sha(
                payload["raw_response_sha256"], "raw_response_sha256"
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "arm_id": self.arm_id,
            "request_sha256": self.request_sha256,
            "endpoint_binding_sha256": self.endpoint_binding_sha256,
            "reviewer_identity_digest": self.reviewer_identity_digest,
            "public_manifest_sha256": self.public_manifest_sha256,
            "disposition": self.disposition.value,
            "p_candidate_valid_micros": self.p_candidate_valid_micros,
            "blocking_findings": list(self.blocking_findings),
            "generated_test_patch": self.generated_test_patch,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_microusd": self.cost_microusd,
            "latency_ms": self.latency_ms,
            "provider_response_id_sha256": self.provider_response_id_sha256,
            "raw_response_sha256": self.raw_response_sha256,
        }

    def to_review_response(self) -> ReviewResponse:
        return ReviewResponse.from_mapping(
            {
                "case_id": self.case_id,
                "arm_id": self.arm_id,
                "reviewer_identity_digest": self.reviewer_identity_digest,
                "disposition": self.disposition.value,
                "p_candidate_valid_micros": self.p_candidate_valid_micros,
                "blocking_findings": list(self.blocking_findings),
                "generated_test_patch": self.generated_test_patch,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "latency_ms": self.latency_ms,
                "raw_response_sha256": self.raw_response_sha256,
            }
        )


@runtime_checkable
class ReviewerClient(Protocol):
    @property
    def endpoint_binding(self) -> ReviewerEndpointBinding: ...

    def review_api(self, request: ReviewRequest) -> NativeReviewResponse: ...


def collect_complete_response_matrix(
    *,
    permit: CollectionPermit,
    public_cases: Sequence[PublicCaseManifest],
    endpoint_bindings: Sequence[ReviewerEndpointBinding],
    clients: Mapping[str, ReviewerClient],
) -> tuple[NativeReviewResponse, ...]:
    if permit.c7_decision is not C7Decision.ALLOW:
        raise ReviewCollectionError("C7 refused reviewer collection")
    cases = tuple(
        sorted(
            (PublicCaseManifest.from_mapping(case.to_mapping()) for case in public_cases),
            key=lambda item: item.case_id,
        )
    )
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ReviewCollectionError("public case set must be non-empty and unique")
    public_cases_sha256 = canonical_digest([case.to_mapping() for case in cases])
    bindings = tuple(endpoint_bindings)
    arm_ids = tuple(binding.arm_id for binding in bindings)
    if not bindings or len(set(arm_ids)) != len(arm_ids):
        raise ReviewCollectionError("endpoint arm bindings must be non-empty and unique")
    if any(binding.public_cases_sha256 != public_cases_sha256 for binding in bindings):
        raise ReviewCollectionError("endpoint binding public case set digest mismatch")
    if set(clients) != set(arm_ids):
        raise ReviewCollectionError("client map must exactly match endpoint arms")
    for binding in bindings:
        client = clients[binding.arm_id]
        if not isinstance(client, ReviewerClient):
            raise ReviewCollectionError("client does not implement ReviewerClient")
        if client.endpoint_binding.digest() != binding.digest():
            raise ReviewCollectionError(
                f"client binding drift for arm {binding.arm_id}"
            )

    responses: list[NativeReviewResponse] = []
    for public_case in cases:
        for binding in bindings:
            request = ReviewRequest.build(
                permit=permit,
                public_case=public_case,
                endpoint=binding,
            )
            response = clients[binding.arm_id].review_api(request)
            if not isinstance(response, NativeReviewResponse):
                raise ReviewCollectionError("client returned an untyped response")
            expected = (
                request.case_id,
                request.arm_id,
                request.request_sha256,
                request.endpoint_binding_sha256,
                request.reviewer_identity_digest,
                request.public_manifest_sha256,
            )
            actual = (
                response.case_id,
                response.arm_id,
                response.request_sha256,
                response.endpoint_binding_sha256,
                response.reviewer_identity_digest,
                response.public_manifest_sha256,
            )
            if actual != expected:
                raise ReviewCollectionError(
                    f"response binding drift for {(request.case_id, request.arm_id)}"
                )
            responses.append(response)

    validate_response_matrix(
        tuple(case.case_id for case in cases),
        arm_ids,
        tuple(response.to_review_response() for response in responses),
    )
    return tuple(responses)


__all__ = (
    "APIProtocol",
    "APITransport",
    "C7Decision",
    "CollectionPermit",
    "NativeReviewResponse",
    "ReviewCollectionError",
    "ReviewRequest",
    "ReviewerClient",
    "ReviewerEndpointBinding",
    "collect_complete_response_matrix",
)
