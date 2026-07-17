"""Closed raw-result contract for the successor collection runner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SuccessorRawResult:
    schema_version: str
    run_id: str
    single_run_sequence: int
    status: str
    verdict: None
    effect_status: str
    case_count: int
    evaluation_row_count: int
    provider_attempt_count: int
    provider_success_count: int
    mechanical_row_count: int
    aggregate_row_count: int
    raw_archive_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "r-eval-indep-1-successor-raw-result-v1":
            raise ValueError("unsupported successor result schema")
        if self.single_run_sequence != 1:
            raise ValueError("only the one-shot sequence is valid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", self.run_id):
            raise ValueError("invalid run id")
        if self.verdict is not None:
            raise ValueError("raw collector result cannot issue a verdict")
        if self.case_count <= 0 or not _SHA256.fullmatch(self.raw_archive_sha256):
            raise ValueError("case count and archive digest are required")
        counts = (
            self.evaluation_row_count,
            self.provider_attempt_count,
            self.provider_success_count,
            self.mechanical_row_count,
            self.aggregate_row_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("row counts cannot be negative")
        complete = (
            self.case_count * 5,
            self.case_count * 6,
            self.case_count * 6,
            self.case_count,
            self.case_count,
        )
        if self.status == "RAW_NOT_ADJUDICATED":
            if self.effect_status != "COMPLETE" or counts != complete:
                raise ValueError("complete result requires exact row counts")
        elif self.status == "INVALID_INCOMPLETE":
            if self.effect_status not in {
                "AMBIGUOUS_EFFECT",
                "C7_HALT",
                "COLLECTION_FAILURE",
            }:
                raise ValueError("invalid incomplete effect status")
            if any(
                actual > expected
                for actual, expected in zip(counts, complete, strict=True)
            ):
                raise ValueError("partial result exceeds frozen counts")
            if counts == complete:
                raise ValueError("an incomplete result cannot claim complete counts")
        else:
            raise ValueError("unknown raw result status")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "single_run_sequence": self.single_run_sequence,
            "status": self.status,
            "verdict": None,
            "effect_status": self.effect_status,
            "case_count": self.case_count,
            "evaluation_row_count": self.evaluation_row_count,
            "provider_attempt_count": self.provider_attempt_count,
            "provider_success_count": self.provider_success_count,
            "mechanical_row_count": self.mechanical_row_count,
            "aggregate_row_count": self.aggregate_row_count,
            "raw_archive_sha256": self.raw_archive_sha256,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SuccessorRawResult:
        expected = {
            "schema_version",
            "run_id",
            "single_run_sequence",
            "status",
            "verdict",
            "effect_status",
            "case_count",
            "evaluation_row_count",
            "provider_attempt_count",
            "provider_success_count",
            "mechanical_row_count",
            "aggregate_row_count",
            "raw_archive_sha256",
        }
        if set(value) != expected:
            raise ValueError("SuccessorRawResult is a closed contract")
        if value["verdict"] is not None:
            raise ValueError("raw verdict must be null")
        return cls(
            schema_version=str(value["schema_version"]),
            run_id=str(value["run_id"]),
            single_run_sequence=int(value["single_run_sequence"]),
            status=str(value["status"]),
            verdict=None,
            effect_status=str(value["effect_status"]),
            case_count=int(value["case_count"]),
            evaluation_row_count=int(value["evaluation_row_count"]),
            provider_attempt_count=int(value["provider_attempt_count"]),
            provider_success_count=int(value["provider_success_count"]),
            mechanical_row_count=int(value["mechanical_row_count"]),
            aggregate_row_count=int(value["aggregate_row_count"]),
            raw_archive_sha256=str(value["raw_archive_sha256"]),
        )
