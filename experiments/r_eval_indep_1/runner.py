"""Freeze-bound, append-only collection executor for R-EVAL successor V1."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Protocol

from .contracts import canonical_digest, canonical_json_bytes
from .corpus_contracts import PublicCaseManifest
from .freeze_run_context import (
    SignedReceipt,
    VerifiedFreezeRunContext,
    verify_receipt_identity,
)
from .native_arm_plan import NativeArmPlan
from .provider_adapter import (
    AmbiguousEffectError,
    ProviderAdapter,
    ProviderRequest,
    ProviderResponse,
    VerifiedProviderBank,
)
from .result_contracts import SuccessorRawResult
from .run_budget import RunBudget


FROZEN_CORPUS_MANIFEST_SHA256 = (
    "a261aeccfea46b1fd4b28525ba7d20acf32c76b36fd2c587f6ebf8a82ec81bc0"
)
FROZEN_PUBLIC_CASES_SHA256 = (
    "c758e4f59b61e63c647960076da64fc9a0459350d9a56504289c0cbac25d1f7f"
)


class EvaluationDisposition(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class RunInvalidIncomplete(RuntimeError):
    pass


class C7Halt(RunInvalidIncomplete):
    pass


@dataclass(frozen=True, slots=True)
class FrozenPublicCorpus:
    corpus_manifest_sha256: str
    public_cases_sha256: str
    cases: tuple[PublicCaseManifest, ...]

    @classmethod
    def build(
        cls,
        *,
        corpus_manifest_sha256: str,
        cases: tuple[PublicCaseManifest, ...],
    ) -> FrozenPublicCorpus:
        validated = tuple(
            sorted(
                (PublicCaseManifest.from_mapping(case.to_mapping()) for case in cases),
                key=lambda item: item.case_id,
            )
        )
        if len(validated) != 74 or len({case.case_id for case in validated}) != 74:
            raise ValueError(
                "R-EVAL successor requires the exact 74-case public corpus"
            )
        built = cls(
            corpus_manifest_sha256=corpus_manifest_sha256,
            public_cases_sha256=canonical_digest(
                [case.to_mapping() for case in validated]
            ),
            cases=validated,
        )
        if (
            built.corpus_manifest_sha256 != FROZEN_CORPUS_MANIFEST_SHA256
            or built.public_cases_sha256 != FROZEN_PUBLIC_CASES_SHA256
        ):
            raise ValueError("public corpus does not match frozen Batch-2B digests")
        return built


@dataclass(frozen=True, slots=True)
class SignedC7Decision:
    decision: str
    phase: str
    request_sha256: str
    execution_permit_sha256: str
    correction_epoch: int
    signed_receipt: SignedReceipt

    def subject_digest(self) -> str:
        return canonical_digest(
            {
                "decision": self.decision,
                "phase": self.phase,
                "request_sha256": self.request_sha256,
                "execution_permit_sha256": self.execution_permit_sha256,
                "correction_epoch": self.correction_epoch,
            }
        )


class C7Authority(Protocol):
    def check(
        self,
        *,
        freeze_run: VerifiedFreezeRunContext,
        phase: str,
        request_sha256: str,
    ) -> SignedC7Decision: ...


RawRunResult = SuccessorRawResult


def _canonical(value: object) -> bytes:
    return canonical_json_bytes(value)


class _Archive:
    ROW_TYPES = {
        "EVALUATION",
        "PROVIDER_ATTEMPT",
        "PROVIDER_SUCCESS",
        "MECHANICAL",
        "AGGREGATE",
        "C7_CHECK",
    }

    def __init__(self, path: Path, common: Mapping[str, object]) -> None:
        self.path = path
        self.common = dict(common)
        self.previous = "0" * 64
        self.counts = {row_type: 0 for row_type in self.ROW_TYPES}

    def append(self, row: Mapping[str, object]) -> None:
        row_type = str(row.get("row_type", ""))
        if row_type not in self.counts:
            raise ValueError("unknown archive row type")
        body = {**self.common, **dict(row)}
        body["sequence"] = sum(self.counts.values()) + 1
        body["previous_sha256"] = self.previous
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        record = {**body, "row_sha256": digest}
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
        freeze_run: VerifiedFreezeRunContext,
        public_corpus: FrozenPublicCorpus,
        plan: NativeArmPlan,
        provider_bank: VerifiedProviderBank,
        provider: ProviderAdapter,
        mechanical_rule: Callable[[PublicCaseManifest], EvaluationDisposition],
        c7_authority: C7Authority,
        budget: RunBudget,
    ) -> SuccessorRawResult:
        freeze_run.assert_verified()
        provider_bank.assert_verified()
        permit = freeze_run.execution_permit
        if plan.case_count != 74 or plan.evaluation_row_count != 370:
            raise ValueError("only the fixed 74-case five-arm plan is executable")
        if public_corpus.corpus_manifest_sha256 != permit.corpus_manifest_sha256:
            raise ValueError("corpus manifest is not freeze-bound")
        if public_corpus.public_cases_sha256 != permit.public_cases_sha256:
            raise ValueError("public corpus is not freeze-bound")
        if provider_bank.sha256 != permit.provider_bank_sha256:
            raise ValueError("provider bank is not freeze-bound")
        if any(
            identity.trust_registry_sha256 != permit.trust_registry_sha256
            for identity in provider_bank.identities.values()
        ):
            raise ValueError("provider bank trusted registry is not freeze-bound")
        if budget.digest() != permit.budget_sha256:
            raise ValueError("run budget is not freeze-bound")

        run_dir = self.root / permit.freeze_subject_sha256 / "global-sequence-1"
        try:
            run_dir.mkdir(mode=0o700, parents=True)
        except FileExistsError as exc:
            raise RunInvalidIncomplete(
                "freeze subject global sequence already consumed"
            ) from exc
        (run_dir / "consumed.json").write_bytes(
            _canonical(
                {
                    "freeze_subject_sha256": permit.freeze_subject_sha256,
                    "run_id": permit.run_id,
                    "global_run_sequence": 1,
                    "execution_permit_sha256": permit.digest(),
                    "consumed": True,
                }
            )
        )
        common = {
            "run_id": permit.run_id,
            "global_run_sequence": 1,
            "freeze_subject_sha256": permit.freeze_subject_sha256,
            "execution_permit_sha256": permit.digest(),
            "correction_epoch": permit.correction_epoch,
            "corpus_manifest_sha256": permit.corpus_manifest_sha256,
            "public_cases_sha256": permit.public_cases_sha256,
            "provider_bank_sha256": permit.provider_bank_sha256,
            "budget_sha256": permit.budget_sha256,
        }
        archive = _Archive(run_dir / "rows.jsonl", common)
        archive.path.touch(mode=0o600)
        started_ns = time.monotonic_ns()
        status = "INVALID_INCOMPLETE"
        effect_status = "COLLECTION_FAILURE"
        result: SuccessorRawResult | None = None
        try:
            for case in public_corpus.cases:
                case_digest = canonical_digest(case.to_mapping())
                for arm in plan.arms:
                    self._require_wallclock(started_ns, budget)
                    if arm.arm_id == "A0":
                        disposition = mechanical_rule(case)
                        if not isinstance(disposition, EvaluationDisposition):
                            raise RunInvalidIncomplete(
                                "mechanical rule returned invalid disposition"
                            )
                        bound = {
                            "case_id": case.case_id,
                            "public_case_sha256": case_digest,
                            "public_manifest_sha256": case.public_manifest_sha256,
                            "arm_id": "A0",
                            "disposition": disposition.value,
                        }
                        archive.append({"row_type": "MECHANICAL", **bound})
                        archive.append(
                            {
                                "row_type": "EVALUATION",
                                **bound,
                                "request_sha256": None,
                                "response_sha256": None,
                                "cost_microusd": 0,
                                "latency_ms": 0,
                            }
                        )
                        continue
                    responses: list[ProviderResponse] = []
                    binding = provider_bank.bindings[arm.arm_id]
                    canary = provider_bank.canaries[arm.arm_id]
                    for sample_index in range(1, arm.sample_count + 1):
                        self._precheck_budget(archive, budget)
                        request = ProviderRequest(
                            run_id=permit.run_id,
                            case_id=case.case_id,
                            arm_id=arm.arm_id,
                            sample_index=sample_index,
                            public_case_sha256=case_digest,
                            public_manifest_sha256=case.public_manifest_sha256,
                            execution_permit_sha256=permit.digest(),
                            provider_binding_sha256=binding.digest(),
                            provider_canary_sha256=canary.digest(),
                            provider_canary_receipt_sha256=canary.signed_receipt.digest(),
                            endpoint_origin_sha256=binding.endpoint_origin_sha256,
                            model_immutable_revision=canary.served_model_immutable_revision,
                            system_prompt_sha256=binding.system_prompt_sha256,
                            tool_schema_sha256=binding.tool_schema_sha256,
                            decoding_config_sha256=binding.decoding_config_sha256,
                            credential_ref_sha256=binding.credential_ref_sha256,
                        )
                        request_digest = request.digest()
                        self._check_c7(
                            freeze_run,
                            c7_authority,
                            archive,
                            "BEFORE_PROVIDER_CALL",
                            request_digest,
                        )
                        archive.append(
                            {
                                "row_type": "PROVIDER_ATTEMPT",
                                **asdict(request),
                                "request_sha256": request_digest,
                            }
                        )
                        try:
                            response = provider.review(request=request)
                        finally:
                            self._check_c7(
                                freeze_run,
                                c7_authority,
                                archive,
                                "AFTER_PROVIDER_CALL",
                                request_digest,
                            )
                        self._validate_response(request, response, budget)
                        responses.append(response)
                        archive.append(
                            {
                                "row_type": "PROVIDER_SUCCESS",
                                **asdict(request),
                                "request_sha256": request_digest,
                                "response_sha256": canonical_digest(asdict(response)),
                                **asdict(response),
                            }
                        )
                    disposition = self._aggregate(responses)
                    response_digest = canonical_digest(
                        [asdict(response) for response in responses]
                    )
                    if arm.sample_count == 3:
                        archive.append(
                            {
                                "row_type": "AGGREGATE",
                                "case_id": case.case_id,
                                "public_case_sha256": case_digest,
                                "public_manifest_sha256": case.public_manifest_sha256,
                                "arm_id": arm.arm_id,
                                "attempt_count": 3,
                                "rule": "MAJORITY_TIE_ABSTAINS",
                                "request_sha256": canonical_digest(
                                    [response.request_sha256 for response in responses]
                                ),
                                "response_sha256": response_digest,
                                "disposition": disposition,
                            }
                        )
                    archive.append(
                        {
                            "row_type": "EVALUATION",
                            "case_id": case.case_id,
                            "public_case_sha256": case_digest,
                            "public_manifest_sha256": case.public_manifest_sha256,
                            "arm_id": arm.arm_id,
                            "provider_binding_sha256": binding.digest(),
                            "provider_canary_sha256": canary.digest(),
                            "provider_canary_receipt_sha256": canary.signed_receipt.digest(),
                            "endpoint_origin_sha256": binding.endpoint_origin_sha256,
                            "model_immutable_revision": canary.served_model_immutable_revision,
                            "system_prompt_sha256": binding.system_prompt_sha256,
                            "tool_schema_sha256": binding.tool_schema_sha256,
                            "decoding_config_sha256": binding.decoding_config_sha256,
                            "credential_ref_sha256": binding.credential_ref_sha256,
                            "request_sha256": canonical_digest(
                                [response.request_sha256 for response in responses]
                            ),
                            "response_sha256": response_digest,
                            "disposition": disposition,
                            "cost_microusd": sum(
                                item.cost_microusd for item in responses
                            ),
                            "latency_ms": sum(item.latency_ms for item in responses),
                        }
                    )
            status = "RAW_NOT_ADJUDICATED"
            effect_status = "COMPLETE"
        except AmbiguousEffectError:
            effect_status = "AMBIGUOUS_EFFECT"
            raise
        except C7Halt:
            effect_status = "C7_HALT"
            raise
        finally:
            result = self._seal(
                run_dir,
                archive,
                status,
                effect_status,
                permit.digest(),
                public_corpus.corpus_manifest_sha256,
                provider_bank.sha256,
                budget.digest(),
            )
        assert result is not None
        return result

    @staticmethod
    def _check_c7(
        freeze_run: VerifiedFreezeRunContext,
        authority: C7Authority,
        archive: _Archive,
        phase: str,
        request_sha256: str,
    ) -> None:
        decision = authority.check(
            freeze_run=freeze_run, phase=phase, request_sha256=request_sha256
        )
        permit = freeze_run.execution_permit
        try:
            verified_identity = verify_receipt_identity(
                freeze_run.verifier, decision.signed_receipt
            )
        except ValueError as error:
            raise C7Halt("invalid C7 custody receipt") from error
        if (
            decision.phase != phase
            or decision.request_sha256 != request_sha256
            or decision.execution_permit_sha256 != permit.digest()
            or decision.correction_epoch != permit.correction_epoch
            or decision.signed_receipt.role != "C7_AUTHORITY"
            or decision.signed_receipt.signer_id
            != freeze_run.collection_permit.c7_authority_id
            or verified_identity.public_key_sha256
            != permit.c7_authority_public_key_sha256
            or verified_identity.trust_registry_sha256 != permit.trust_registry_sha256
            or decision.signed_receipt.subject_sha256 != decision.subject_digest()
        ):
            raise C7Halt("invalid C7 custody receipt")
        archive.append(
            {
                "row_type": "C7_CHECK",
                "phase": phase,
                "request_sha256": request_sha256,
                "c7_decision_sha256": decision.subject_digest(),
                "c7_signature_sha256": decision.signed_receipt.signature_sha256,
                "decision": decision.decision,
            }
        )
        if decision.decision != "ALLOW":
            raise C7Halt("C7 halted collection; partial archive sealed")

    @staticmethod
    def _precheck_budget(archive: _Archive, budget: RunBudget) -> None:
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_microusd": 0,
            "latency_ms": 0,
        }
        for line in archive.path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["row_type"] == "PROVIDER_SUCCESS":
                for field in totals:
                    totals[field] += int(row[field])
        limits = {
            "input_tokens": (budget.per_call_input_tokens, budget.total_input_tokens),
            "output_tokens": (
                budget.per_call_output_tokens,
                budget.total_output_tokens,
            ),
            "cost_microusd": (
                budget.per_call_cost_microusd,
                budget.total_cost_microusd,
            ),
            "latency_ms": (budget.per_call_latency_ms, budget.total_latency_ms),
        }
        if any(
            totals[field] + per_call > total
            for field, (per_call, total) in limits.items()
        ):
            raise RunInvalidIncomplete(
                "remaining total budget cannot admit another effect"
            )

    @staticmethod
    def _validate_response(
        request: ProviderRequest, response: ProviderResponse, budget: RunBudget
    ) -> None:
        echoes = (
            response.request_sha256,
            response.provider_binding_sha256,
            response.provider_canary_sha256,
            response.provider_canary_receipt_sha256,
            response.endpoint_origin_sha256,
            response.model_immutable_revision,
            response.system_prompt_sha256,
            response.tool_schema_sha256,
            response.decoding_config_sha256,
            response.credential_ref_sha256,
        )
        expected = (
            request.digest(),
            request.provider_binding_sha256,
            request.provider_canary_sha256,
            request.provider_canary_receipt_sha256,
            request.endpoint_origin_sha256,
            request.model_immutable_revision,
            request.system_prompt_sha256,
            request.tool_schema_sha256,
            request.decoding_config_sha256,
            request.credential_ref_sha256,
        )
        if echoes != expected:
            raise RunInvalidIncomplete("provider response binding drift")
        if response.disposition not in {item.value for item in EvaluationDisposition}:
            raise RunInvalidIncomplete("invalid provider disposition")
        for field in ("provider_response_id_sha256", "raw_response_sha256"):
            value = getattr(response, field)
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise RunInvalidIncomplete(f"{field} is not sha256")
        values = (
            response.input_tokens,
            response.output_tokens,
            response.cost_microusd,
            response.latency_ms,
        )
        if any(value < 0 for value in values):
            raise RunInvalidIncomplete("negative provider accounting")
        if (
            response.input_tokens > budget.per_call_input_tokens
            or response.output_tokens > budget.per_call_output_tokens
            or response.cost_microusd > budget.per_call_cost_microusd
            or response.latency_ms > budget.per_call_latency_ms
        ):
            raise RunInvalidIncomplete("per-call budget exceeded")

    @staticmethod
    def _aggregate(responses: list[ProviderResponse]) -> str:
        if len(responses) == 1:
            return responses[0].disposition
        if len(responses) != 3:
            raise RunInvalidIncomplete("aggregate requires exactly three responses")
        counts = {item.value: 0 for item in EvaluationDisposition}
        for response in responses:
            counts[response.disposition] += 1
        winners = [
            key for key, value in counts.items() if value == max(counts.values())
        ]
        return winners[0] if len(winners) == 1 else EvaluationDisposition.ABSTAIN.value

    @staticmethod
    def _require_wallclock(started_ns: int, budget: RunBudget) -> None:
        if (time.monotonic_ns() - started_ns) // 1_000_000 > budget.wallclock_ms:
            raise RunInvalidIncomplete("run wallclock budget exceeded")

    @staticmethod
    def _seal(
        run_dir: Path,
        archive: _Archive,
        status: str,
        effect_status: str,
        permit_sha256: str,
        corpus_sha256: str,
        provider_bank_sha256: str,
        budget_sha256: str,
    ) -> SuccessorRawResult:
        result = SuccessorRawResult(
            schema_version="r-eval-indep-1-successor-raw-result-v2",
            run_id="r-eval-indep-1-rfinal-001",
            single_run_sequence=1,
            status=status,
            verdict=None,
            effect_status=effect_status,
            case_count=74,
            evaluation_row_count=archive.counts["EVALUATION"],
            provider_attempt_count=archive.counts["PROVIDER_ATTEMPT"],
            provider_success_count=archive.counts["PROVIDER_SUCCESS"],
            mechanical_row_count=archive.counts["MECHANICAL"],
            aggregate_row_count=archive.counts["AGGREGATE"],
            raw_archive_sha256=archive.digest(),
            execution_permit_sha256=permit_sha256,
            corpus_manifest_sha256=corpus_sha256,
            provider_bank_sha256=provider_bank_sha256,
            budget_sha256=budget_sha256,
        )
        result_path = run_dir / "result.json"
        result_path.write_bytes(_canonical(result.to_mapping()))
        (run_dir / "seal.json").write_bytes(
            _canonical(
                {
                    "result_sha256": hashlib.sha256(
                        result_path.read_bytes()
                    ).hexdigest(),
                    "raw_archive_sha256": result.raw_archive_sha256,
                    "last_row_sha256": archive.previous,
                    "refill": "FORBIDDEN",
                }
            )
        )
        return result


def verify_sealed_run(run_dir: Path) -> SuccessorRawResult:
    result_bytes = (run_dir / "result.json").read_bytes()
    archive_bytes = (run_dir / "rows.jsonl").read_bytes()
    seal = json.loads((run_dir / "seal.json").read_text(encoding="utf-8"))
    result = SuccessorRawResult.from_mapping(json.loads(result_bytes))
    if set(seal) != {
        "result_sha256",
        "raw_archive_sha256",
        "last_row_sha256",
        "refill",
    }:
        raise ValueError("seal is not closed")
    if seal["refill"] != "FORBIDDEN":
        raise ValueError("seal permits refill")
    if hashlib.sha256(result_bytes).hexdigest() != seal["result_sha256"]:
        raise ValueError("result seal mismatch")
    digest = hashlib.sha256(archive_bytes).hexdigest()
    if digest != seal["raw_archive_sha256"] or digest != result.raw_archive_sha256:
        raise ValueError("archive seal mismatch")
    previous = "0" * 64
    for sequence, line in enumerate(archive_bytes.splitlines(), start=1):
        row = json.loads(line)
        row_digest = row.pop("row_sha256", None)
        if row.get("sequence") != sequence or row.get("previous_sha256") != previous:
            raise ValueError("archive chain ordering mismatch")
        previous = hashlib.sha256(_canonical(row)).hexdigest()
        if row_digest != previous:
            raise ValueError("archive chain digest mismatch")
    if previous != seal["last_row_sha256"]:
        raise ValueError("archive chain tail mismatch")
    return result
