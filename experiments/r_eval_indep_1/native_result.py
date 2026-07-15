"""Closed raw r-final result contract for R-EVAL-INDEP-1.

This module validates an already-collected raw record.  It deliberately exposes
no provider collector, runner, filesystem writer, adjudicator, or verdict path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import ContractValidationError, canonical_digest, canonical_json_bytes


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_HEAD = re.compile(r"^[0-9a-f]{40}$")
_FIELDS = {
    "schema_version",
    "prereg_id",
    "run_id",
    "single_run_sequence",
    "status",
    "verdict",
    "target_head",
    "prereg_lock_sha256",
    "prereg_candidate_sha256",
    "exact_manifest_sha256",
    "independent_review_sha256",
    "provider_bindings_sha256",
    "oracle_custody_sha256",
    "public_cases_sha256",
    "referee_cases_sha256",
    "response_matrix_sha256",
    "truth_join_sha256",
    "raw_response_archive_sha256",
    "metrics",
    "metrics_sha256",
    "case_count",
    "arm_count",
    "provider_response_count",
    "provider_call_count",
    "correction_epoch",
    "collection_operator_id",
    "run_authority_id",
    "c7_authority_id",
    "c7_decision",
    "result_adjudicator_id",
}


def _closed(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("RawRFinalResult requires an object")
    actual = set(value)
    unknown = sorted(actual - _FIELDS)
    missing = sorted(_FIELDS - actual)
    if unknown or missing:
        raise ContractValidationError(
            f"RawRFinalResult field mismatch: unknown={unknown}, missing={missing}"
        )
    return dict(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} requires a non-empty string")
    return value


def _literal(value: Any, field: str, expected: str) -> str:
    text = _text(value, field)
    if text != expected:
        raise ContractValidationError(f"{field} must be {expected}")
    return text


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _SHA256.fullmatch(text) or text == "0" * 64:
        raise ContractValidationError(f"{field} requires a non-zero lowercase sha256")
    return text


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractValidationError(f"{field} requires a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{field} requires a non-negative integer")
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class RawRFinalResult:
    schema_version: str
    prereg_id: str
    run_id: str
    single_run_sequence: int
    status: str
    verdict: None
    target_head: str
    prereg_lock_sha256: str
    prereg_candidate_sha256: str
    exact_manifest_sha256: str
    independent_review_sha256: str
    provider_bindings_sha256: str
    oracle_custody_sha256: str
    public_cases_sha256: str
    referee_cases_sha256: str
    response_matrix_sha256: str
    truth_join_sha256: str
    raw_response_archive_sha256: str
    metrics: Mapping[str, Any]
    metrics_sha256: str
    case_count: int
    arm_count: int
    provider_response_count: int
    provider_call_count: int
    correction_epoch: int
    collection_operator_id: str
    run_authority_id: str
    c7_authority_id: str
    c7_decision: str
    result_adjudicator_id: None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RawRFinalResult:
        payload = _closed(value)
        if payload["verdict"] is not None:
            raise ContractValidationError("raw r-final verdict must be null")
        if payload["result_adjudicator_id"] is not None:
            raise ContractValidationError(
                "raw r-final cannot bind an adjudicator before adjudication"
            )
        head = _text(payload["target_head"], "target_head")
        if not _GIT_HEAD.fullmatch(head):
            raise ContractValidationError("target_head requires a 40-character Git hash")
        sequence = _positive_int(payload["single_run_sequence"], "single_run_sequence")
        if sequence != 1:
            raise ContractValidationError("only the predeclared run sequence 1 is valid")
        case_count = _positive_int(payload["case_count"], "case_count")
        arm_count = _positive_int(payload["arm_count"], "arm_count")
        response_count = _positive_int(
            payload["provider_response_count"], "provider_response_count"
        )
        call_count = _positive_int(payload["provider_call_count"], "provider_call_count")
        if response_count != case_count * arm_count or call_count != response_count:
            raise ContractValidationError(
                "raw r-final requires one successful API call for every case x arm cell"
            )
        raw_metrics = payload["metrics"]
        if not isinstance(raw_metrics, Mapping) or not raw_metrics:
            raise ContractValidationError("metrics requires a non-empty object")
        try:
            normalized_metrics = json.loads(canonical_json_bytes(raw_metrics))
        except (ContractValidationError, json.JSONDecodeError) as error:
            raise ContractValidationError("metrics are not canonical JSON") from error
        metrics_sha = _sha(payload["metrics_sha256"], "metrics_sha256")
        if canonical_digest(normalized_metrics) != metrics_sha:
            raise ContractValidationError("metrics_sha256 does not bind metrics")
        collection_operator = _text(
            payload["collection_operator_id"], "collection_operator_id"
        )
        run_authority = _text(payload["run_authority_id"], "run_authority_id")
        c7_authority = _text(payload["c7_authority_id"], "c7_authority_id")
        if len({collection_operator, run_authority, c7_authority}) != 3:
            raise ContractValidationError(
                "collection operator, run authority, and C7 authority must differ"
            )
        return cls(
            schema_version=_literal(
                payload["schema_version"],
                "schema_version",
                "r-eval-indep-1-raw-rfinal-v1",
            ),
            prereg_id=_literal(payload["prereg_id"], "prereg_id", "R-EVAL-INDEP-1"),
            run_id=_text(payload["run_id"], "run_id"),
            single_run_sequence=sequence,
            status=_literal(
                payload["status"], "status", "RAW_NOT_ADJUDICATED"
            ),
            verdict=None,
            target_head=head,
            prereg_lock_sha256=_sha(
                payload["prereg_lock_sha256"], "prereg_lock_sha256"
            ),
            prereg_candidate_sha256=_sha(
                payload["prereg_candidate_sha256"], "prereg_candidate_sha256"
            ),
            exact_manifest_sha256=_sha(
                payload["exact_manifest_sha256"], "exact_manifest_sha256"
            ),
            independent_review_sha256=_sha(
                payload["independent_review_sha256"], "independent_review_sha256"
            ),
            provider_bindings_sha256=_sha(
                payload["provider_bindings_sha256"], "provider_bindings_sha256"
            ),
            oracle_custody_sha256=_sha(
                payload["oracle_custody_sha256"], "oracle_custody_sha256"
            ),
            public_cases_sha256=_sha(
                payload["public_cases_sha256"], "public_cases_sha256"
            ),
            referee_cases_sha256=_sha(
                payload["referee_cases_sha256"], "referee_cases_sha256"
            ),
            response_matrix_sha256=_sha(
                payload["response_matrix_sha256"], "response_matrix_sha256"
            ),
            truth_join_sha256=_sha(
                payload["truth_join_sha256"], "truth_join_sha256"
            ),
            raw_response_archive_sha256=_sha(
                payload["raw_response_archive_sha256"],
                "raw_response_archive_sha256",
            ),
            metrics=_freeze_json(normalized_metrics),
            metrics_sha256=metrics_sha,
            case_count=case_count,
            arm_count=arm_count,
            provider_response_count=response_count,
            provider_call_count=call_count,
            correction_epoch=_nonnegative_int(
                payload["correction_epoch"], "correction_epoch"
            ),
            collection_operator_id=collection_operator,
            run_authority_id=run_authority,
            c7_authority_id=c7_authority,
            c7_decision=_literal(payload["c7_decision"], "c7_decision", "ALLOW"),
            result_adjudicator_id=None,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prereg_id": self.prereg_id,
            "run_id": self.run_id,
            "single_run_sequence": self.single_run_sequence,
            "status": self.status,
            "verdict": self.verdict,
            "target_head": self.target_head,
            "prereg_lock_sha256": self.prereg_lock_sha256,
            "prereg_candidate_sha256": self.prereg_candidate_sha256,
            "exact_manifest_sha256": self.exact_manifest_sha256,
            "independent_review_sha256": self.independent_review_sha256,
            "provider_bindings_sha256": self.provider_bindings_sha256,
            "oracle_custody_sha256": self.oracle_custody_sha256,
            "public_cases_sha256": self.public_cases_sha256,
            "referee_cases_sha256": self.referee_cases_sha256,
            "response_matrix_sha256": self.response_matrix_sha256,
            "truth_join_sha256": self.truth_join_sha256,
            "raw_response_archive_sha256": self.raw_response_archive_sha256,
            "metrics": _thaw_json(self.metrics),
            "metrics_sha256": self.metrics_sha256,
            "case_count": self.case_count,
            "arm_count": self.arm_count,
            "provider_response_count": self.provider_response_count,
            "provider_call_count": self.provider_call_count,
            "correction_epoch": self.correction_epoch,
            "collection_operator_id": self.collection_operator_id,
            "run_authority_id": self.run_authority_id,
            "c7_authority_id": self.c7_authority_id,
            "c7_decision": self.c7_decision,
            "result_adjudicator_id": self.result_adjudicator_id,
        }


def validate_raw_rfinal_result(value: Mapping[str, Any]) -> RawRFinalResult:
    return RawRFinalResult.from_mapping(value)


__all__ = ("RawRFinalResult", "validate_raw_rfinal_result")
