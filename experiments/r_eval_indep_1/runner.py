"""Append-only, one-shot collection runner for R-EVAL-INDEP-1 successor V1.

This module deliberately cannot join hidden truth or issue a scientific verdict.
It collects public-cell responses, seals complete or partial raw archives, and
permanently consumes a run id before the first provider call.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

from .native_arm_plan import NativeArmPlan
from .provider_adapter import (
    AmbiguousEffectError,
    ArmProviderBinding,
    ProviderAdapter,
    ProviderResponse,
    validate_provider_bank,
)
from .run_budget import RunBudget
from .result_contracts import SuccessorRawResult


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_TOKEN = re.compile(
    r"oracle|referee|truth|expected[_ -]?verdict", re.IGNORECASE
)


class EvaluationDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class RunInvalidIncomplete(RuntimeError):
    pass


class C7Halt(RunInvalidIncomplete):
    pass


@dataclass(frozen=True)
class PublicEvaluationCase:
    case_id: str
    public_manifest_sha256: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"case-[0-9a-f]{16}", self.case_id):
            raise ValueError("case_id must be opaque")
        if not _SHA256.fullmatch(self.public_manifest_sha256):
            raise ValueError("public manifest digest required")
        encoded = json.dumps(self.payload, sort_keys=True, separators=(",", ":"))
        if _PRIVATE_TOKEN.search(encoded):
            raise ValueError("hidden oracle/truth material cannot enter public case")


RawRunResult = SuccessorRawResult


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


class _Archive:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.previous = "0" * 64
        self.counts = {
            "EVALUATION": 0,
            "PROVIDER_ATTEMPT": 0,
            "PROVIDER_SUCCESS": 0,
            "MECHANICAL": 0,
            "AGGREGATE": 0,
        }

    def append(self, row: Mapping[str, object]) -> None:
        row_type = str(row.get("row_type", ""))
        if row_type not in self.counts:
            raise ValueError("unknown archive row type")
        body = dict(row)
        body["sequence"] = sum(self.counts.values()) + 1
        body["previous_sha256"] = self.previous
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        record = dict(body)
        record["row_sha256"] = digest
        with self.path.open("ab") as handle:
            handle.write(_canonical(record) + b"\n")
            handle.flush()
        self.previous = digest
        self.counts[row_type] += 1

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class NativeSuccessorRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def run_once(
        self,
        *,
        run_id: str,
        cases: tuple[PublicEvaluationCase, ...],
        plan: NativeArmPlan,
        provider_bank: tuple[ArmProviderBinding, ...],
        provider: ProviderAdapter,
        mechanical_rule: Callable[[PublicEvaluationCase], EvaluationDisposition],
        c7_check: Callable[[], str],
        budget: RunBudget,
    ) -> SuccessorRawResult:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", run_id):
            raise ValueError("invalid run_id")
        run_dir = self.root / run_id
        try:
            run_dir.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise RunInvalidIncomplete("run id already consumed") from exc
        (run_dir / "consumed.json").write_bytes(
            _canonical({"run_id": run_id, "single_run_sequence": 1, "consumed": True})
        )
        archive = _Archive(run_dir / "rows.jsonl")
        archive.path.touch(mode=0o600)
        started_ns = time.monotonic_ns()
        try:
            if len(cases) != plan.case_count or len(
                {case.case_id for case in cases}
            ) != len(cases):
                raise RunInvalidIncomplete("case count/set drift")
            bank = validate_provider_bank(plan, provider_bank)
            self._require_c7(c7_check)
            for case in cases:
                for arm in plan.arms:
                    self._require_wallclock(started_ns, budget)
                    self._require_c7(c7_check)
                    if arm.arm_id == "A0":
                        disposition = mechanical_rule(case)
                        if not isinstance(disposition, EvaluationDisposition):
                            raise RunInvalidIncomplete(
                                "mechanical rule returned an invalid disposition"
                            )
                        archive.append(
                            {
                                "row_type": "MECHANICAL",
                                "case_id": case.case_id,
                                "arm_id": arm.arm_id,
                                "disposition": disposition.value,
                            }
                        )
                        archive.append(
                            {
                                "row_type": "EVALUATION",
                                "case_id": case.case_id,
                                "arm_id": arm.arm_id,
                                "disposition": disposition.value,
                                "cost_microusd": 0,
                                "latency_ms": 0,
                            }
                        )
                        continue
                    responses: list[ProviderResponse] = []
                    for sample_index in range(1, arm.sample_count + 1):
                        binding = bank[arm.arm_id]
                        archive.append(
                            {
                                "row_type": "PROVIDER_ATTEMPT",
                                "case_id": case.case_id,
                                "arm_id": arm.arm_id,
                                "sample_index": sample_index,
                                "model_immutable_revision": binding.model_immutable_revision,
                            }
                        )
                        response = provider.review(
                            binding=binding, case=case, sample_index=sample_index
                        )
                        self._require_wallclock(started_ns, budget)
                        self._validate_response(response, budget)
                        responses.append(response)
                        archive.append(
                            {
                                "row_type": "PROVIDER_SUCCESS",
                                "case_id": case.case_id,
                                "arm_id": arm.arm_id,
                                "sample_index": sample_index,
                                "disposition": response.disposition,
                                "input_tokens": response.input_tokens,
                                "output_tokens": response.output_tokens,
                                "cost_microusd": response.cost_microusd,
                                "latency_ms": response.latency_ms,
                                "provider_response_id_sha256": response.provider_response_id_sha256,
                                "raw_response_sha256": response.raw_response_sha256,
                            }
                        )
                    disposition = self._aggregate(responses)
                    if arm.sample_count == 3:
                        archive.append(
                            {
                                "row_type": "AGGREGATE",
                                "case_id": case.case_id,
                                "arm_id": arm.arm_id,
                                "attempt_count": 3,
                                "rule": "MAJORITY",
                                "disposition": disposition,
                            }
                        )
                    archive.append(
                        {
                            "row_type": "EVALUATION",
                            "case_id": case.case_id,
                            "arm_id": arm.arm_id,
                            "disposition": disposition,
                            "cost_microusd": sum(r.cost_microusd for r in responses),
                            "latency_ms": sum(r.latency_ms for r in responses),
                        }
                    )
                    self._enforce_totals(archive, budget)
            return self._seal(
                run_dir, archive, plan.case_count, "RAW_NOT_ADJUDICATED", "COMPLETE"
            )
        except AmbiguousEffectError:
            self._seal(
                run_dir,
                archive,
                plan.case_count,
                "INVALID_INCOMPLETE",
                "AMBIGUOUS_EFFECT",
            )
            raise
        except C7Halt:
            self._seal(
                run_dir, archive, plan.case_count, "INVALID_INCOMPLETE", "C7_HALT"
            )
            raise
        except Exception:
            self._seal(
                run_dir,
                archive,
                plan.case_count,
                "INVALID_INCOMPLETE",
                "COLLECTION_FAILURE",
            )
            raise

    @staticmethod
    def _require_c7(c7_check: Callable[[], str]) -> None:
        decision = c7_check()
        if decision != "ALLOW":
            raise C7Halt(
                "C7 halted collection; partial archive sealed; refill forbidden"
            )

    @staticmethod
    def _validate_response(response: ProviderResponse, budget: RunBudget) -> None:
        if response.disposition not in {item.value for item in EvaluationDisposition}:
            raise RunInvalidIncomplete("invalid provider disposition")
        values = (
            response.input_tokens,
            response.output_tokens,
            response.cost_microusd,
            response.latency_ms,
        )
        if any(value < 0 for value in values):
            raise RunInvalidIncomplete("negative provider accounting")
        if response.input_tokens > budget.per_call_input_tokens:
            raise RunInvalidIncomplete("per-call input budget exceeded")
        if response.output_tokens > budget.per_call_output_tokens:
            raise RunInvalidIncomplete("per-call output budget exceeded")
        if response.cost_microusd > budget.per_call_cost_microusd:
            raise RunInvalidIncomplete("per-call cost budget exceeded")
        if response.latency_ms > budget.per_call_latency_ms:
            raise RunInvalidIncomplete("per-call latency budget exceeded")
        if not _SHA256.fullmatch(response.provider_response_id_sha256):
            raise RunInvalidIncomplete("provider response id is not bound")
        if not _SHA256.fullmatch(response.raw_response_sha256):
            raise RunInvalidIncomplete("raw response is not bound")

    @staticmethod
    def _require_wallclock(started_ns: int, budget: RunBudget) -> None:
        elapsed_ms = (time.monotonic_ns() - started_ns) // 1_000_000
        if elapsed_ms > budget.wallclock_ms:
            raise RunInvalidIncomplete("run wallclock budget exceeded")

    @staticmethod
    def _aggregate(responses: list[ProviderResponse]) -> str:
        if len(responses) == 1:
            return responses[0].disposition
        if len(responses) != 3:
            raise RunInvalidIncomplete("aggregate requires exactly three responses")
        counts = {disposition.value: 0 for disposition in EvaluationDisposition}
        for response in responses:
            counts[response.disposition] += 1
        return max(counts, key=lambda value: (counts[value], value))

    @staticmethod
    def _enforce_totals(archive: _Archive, budget: RunBudget) -> None:
        # Totals are recomputed from append-only provider-success rows so attempt
        # and evaluation rows can never double-count spend.
        input_tokens = output_tokens = cost = latency = 0
        for line in archive.path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["row_type"] == "PROVIDER_SUCCESS":
                input_tokens += int(row["input_tokens"])
                output_tokens += int(row["output_tokens"])
                cost += int(row["cost_microusd"])
                latency += int(row["latency_ms"])
        if (
            input_tokens > budget.total_input_tokens
            or output_tokens > budget.total_output_tokens
        ):
            raise RunInvalidIncomplete("total token budget exceeded")
        if cost > budget.total_cost_microusd or latency > budget.total_latency_ms:
            raise RunInvalidIncomplete("total cost/latency budget exceeded")

    @staticmethod
    def _seal(
        run_dir: Path,
        archive: _Archive,
        case_count: int,
        status: str,
        effect_status: str,
    ) -> SuccessorRawResult:
        result = SuccessorRawResult(
            schema_version="r-eval-indep-1-successor-raw-result-v1",
            single_run_sequence=1,
            status=status,
            verdict=None,
            effect_status=effect_status,
            run_id=run_dir.name,
            case_count=case_count,
            evaluation_row_count=archive.counts["EVALUATION"],
            provider_attempt_count=archive.counts["PROVIDER_ATTEMPT"],
            provider_success_count=archive.counts["PROVIDER_SUCCESS"],
            mechanical_row_count=archive.counts["MECHANICAL"],
            aggregate_row_count=archive.counts["AGGREGATE"],
            raw_archive_sha256=archive.digest(),
        )
        result_path = run_dir / "result.json"
        result_path.write_bytes(_canonical(result.to_mapping()))
        seal = {
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "raw_archive_sha256": result.raw_archive_sha256,
            "last_row_sha256": archive.previous,
            "refill": "FORBIDDEN",
        }
        (run_dir / "seal.json").write_bytes(_canonical(seal))
        return result


def verify_sealed_run(run_dir: Path) -> SuccessorRawResult:
    """Verify result/archive digests and every append-only hash-chain edge."""
    result_path = run_dir / "result.json"
    archive_path = run_dir / "rows.jsonl"
    seal_path = run_dir / "seal.json"
    try:
        result_bytes = result_path.read_bytes()
        archive_bytes = archive_path.read_bytes()
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        result = SuccessorRawResult.from_mapping(json.loads(result_bytes))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("sealed run contract is invalid") from exc
    if set(seal) != {
        "result_sha256",
        "raw_archive_sha256",
        "last_row_sha256",
        "refill",
    }:
        raise ValueError("seal is not a closed contract")
    if seal["refill"] != "FORBIDDEN":
        raise ValueError("seal permits refill")
    if hashlib.sha256(result_bytes).hexdigest() != seal["result_sha256"]:
        raise ValueError("result seal mismatch")
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    if (
        archive_digest != seal["raw_archive_sha256"]
        or archive_digest != result.raw_archive_sha256
    ):
        raise ValueError("archive seal mismatch")
    previous = "0" * 64
    for sequence, line in enumerate(archive_bytes.splitlines(), start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("archive row is not JSON") from exc
        digest = row.pop("row_sha256", None)
        if row.get("sequence") != sequence or row.get("previous_sha256") != previous:
            raise ValueError("archive chain ordering mismatch")
        expected = hashlib.sha256(_canonical(row)).hexdigest()
        if digest != expected:
            raise ValueError("archive chain digest mismatch")
        previous = expected
    if previous != seal["last_row_sha256"]:
        raise ValueError("archive chain tail mismatch")
    return result
