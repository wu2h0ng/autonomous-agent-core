"""Closed complete/partial raw-result contract for successor V1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
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
    execution_permit_sha256: str
    corpus_manifest_sha256: str
    provider_bank_sha256: str
    budget_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != "r-eval-indep-1-successor-raw-result-v2":
            raise ValueError("unsupported successor result schema")
        if self.run_id != "r-eval-indep-1-rfinal-001" or self.single_run_sequence != 1:
            raise ValueError("result is not bound to the frozen one-shot run")
        if self.verdict is not None:
            raise ValueError("raw collector result cannot issue a verdict")
        if self.case_count != 74:
            raise ValueError("result requires the exact 74-case corpus")
        for field in (
            "raw_archive_sha256",
            "execution_permit_sha256",
            "corpus_manifest_sha256",
            "provider_bank_sha256",
            "budget_sha256",
        ):
            if not _SHA256.fullmatch(getattr(self, field)):
                raise ValueError(f"{field} must be sha256")
        counts = (
            self.evaluation_row_count,
            self.provider_attempt_count,
            self.provider_success_count,
            self.mechanical_row_count,
            self.aggregate_row_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("row counts cannot be negative")
        complete = (370, 444, 444, 74, 74)
        if self.status == "RAW_NOT_ADJUDICATED":
            if self.effect_status != "COMPLETE" or counts != complete:
                raise ValueError("COMPLETE requires exact frozen row counts")
        elif self.status == "INVALID_INCOMPLETE":
            if self.effect_status not in {
                "AMBIGUOUS_EFFECT",
                "C7_HALT",
                "COLLECTION_FAILURE",
            }:
                raise ValueError("invalid PARTIAL effect status")
            if any(
                actual > expected
                for actual, expected in zip(counts, complete, strict=True)
            ):
                raise ValueError("PARTIAL exceeds frozen counts")
            if counts == complete:
                raise ValueError("PARTIAL cannot claim complete counts")
        else:
            raise ValueError("unknown raw result status")

    def to_mapping(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SuccessorRawResult:
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected or value.get("verdict") is not None:
            raise ValueError("SuccessorRawResult is closed and verdict-null")
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
            execution_permit_sha256=str(value["execution_permit_sha256"]),
            corpus_manifest_sha256=str(value["corpus_manifest_sha256"]),
            provider_bank_sha256=str(value["provider_bank_sha256"]),
            budget_sha256=str(value["budget_sha256"]),
        )
