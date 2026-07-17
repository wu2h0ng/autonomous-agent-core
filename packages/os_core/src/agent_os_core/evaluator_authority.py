from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from agent_os_contracts import (
    EvaluationFailureCode,
    EvaluationReceipt,
    EvaluationScore,
    EvaluatorInput,
    EvaluatorMeasurementCandidate,
    FailureReason,
    Uncertainty,
    canonical_json,
)


class EvaluatorAuthorityError(RuntimeError):
    pass


class EvaluationAuthorityDenied(EvaluatorAuthorityError):
    pass


class EvaluationBindingDrift(EvaluatorAuthorityError):
    pass


class EvaluatorBackendUnavailable(EvaluatorAuthorityError):
    pass


class EvaluatorBackendTimeout(EvaluatorBackendUnavailable):
    pass


class EvaluatorBackendMalformed(EvaluatorAuthorityError):
    pass


class EvaluatorAdapter(Protocol):
    def evaluate_candidate(
        self,
        request: EvaluatorInput,
        *,
        evidence_payloads: tuple[bytes, ...],
    ) -> EvaluatorMeasurementCandidate: ...


ExternalEvaluatorCall = Callable[[EvaluatorInput], EvaluatorMeasurementCandidate]
ArtifactReader = Callable[[str], bytes | None]


class ExternalEvaluatorAdapter:
    """Converts an external call into an untrusted measurement candidate."""

    def __init__(self, backend: ExternalEvaluatorCall) -> None:
        self._backend = backend

    def evaluate_candidate(
        self,
        request: EvaluatorInput,
        *,
        evidence_payloads: tuple[bytes, ...],
    ) -> EvaluatorMeasurementCandidate:
        del evidence_payloads
        try:
            candidate = self._backend(request)
        except TimeoutError as exc:
            raise EvaluatorBackendTimeout("evaluator backend timed out") from exc
        if not isinstance(candidate, EvaluatorMeasurementCandidate):
            raise EvaluatorBackendMalformed(
                "external evaluator must return an unsealed measurement candidate"
            )
        return candidate


class DeterministicEvaluatorAdapter:
    """Narrow local reference: scores one JSON passed/failed report."""

    def __init__(self, artifact_reader: ArtifactReader | None = None) -> None:
        self._artifact_reader = artifact_reader

    def evaluate_candidate(
        self,
        request: EvaluatorInput,
        *,
        evidence_payloads: tuple[bytes, ...],
    ) -> EvaluatorMeasurementCandidate:
        payloads = evidence_payloads
        if self._artifact_reader is not None:
            resolved: list[bytes] = []
            for entry in request.evidence.entries:
                raw = self._artifact_reader(entry.evidence_ref)
                if raw is None:
                    raise EvaluatorBackendUnavailable(
                        f"evidence unavailable: {entry.evidence_ref}"
                    )
                resolved.append(raw)
            payloads = tuple(resolved)
        if len(payloads) != 1:
            raise EvaluatorBackendMalformed(
                "deterministic reference requires exactly one evidence report"
            )
        try:
            report = json.loads(payloads[0])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EvaluatorBackendMalformed("evidence report is malformed") from exc
        if not isinstance(report, dict):
            raise EvaluatorBackendMalformed("evidence report must be an object")
        passed = report.get("passed")
        failed = report.get("failed")
        if (
            isinstance(passed, bool)
            or isinstance(failed, bool)
            or not isinstance(passed, int)
            or not isinstance(failed, int)
            or passed < 0
            or failed < 0
            or passed + failed <= 0
        ):
            raise EvaluatorBackendMalformed(
                "evidence report requires non-negative passed/failed counts"
            )
        failures: tuple[FailureReason, ...] = ()
        if failed:
            failures = (
                FailureReason(
                    code=EvaluationFailureCode.CRITERIA_NOT_MET,
                    message="one or more deterministic checks failed",
                    retriable=False,
                ),
            )
        return EvaluatorMeasurementCandidate(
            input_digest=request.canonical_digest(),
            score=EvaluationScore(
                value=passed / (passed + failed),
                scale_min=0.0,
                scale_max=1.0,
            ),
            uncertainty=Uncertainty(confidence=1.0, reasons=()),
            failure_reasons=failures,
        )


class EvaluatorRegistry:
    """Owns bindings and seals measurements; it has no Outcome authority."""

    def __init__(
        self,
        *,
        adapters: Mapping[str, EvaluatorAdapter],
        artifact_reader: ArtifactReader,
        clock: Callable[[], datetime] | None = None,
        receipt_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._adapters = dict(adapters)
        self._artifact_reader = artifact_reader
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._receipt_id_factory = receipt_id_factory or (
            lambda: f"evaluation-receipt-{uuid4()}"
        )
        self._sealed: dict[str, tuple[str, EvaluationReceipt]] = {}

    @staticmethod
    def _sha256(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def _read_bound_artifact(self, ref: str, expected_digest: str, label: str) -> bytes:
        raw = self._artifact_reader(ref)
        if raw is None:
            raise EvaluationAuthorityDenied(f"{label} artifact is unavailable")
        if self._sha256(raw) != expected_digest:
            raise EvaluationAuthorityDenied(f"{label} bytes do not match manifest")
        return raw

    def evaluate(self, request: EvaluatorInput) -> EvaluationReceipt:
        if request.proposer_principal_id == request.identity.principal_id:
            raise EvaluationAuthorityDenied(
                "proposer cannot act as evaluator for its own proposal"
            )

        input_digest = request.canonical_digest()
        previous = self._sealed.get(request.evaluation_id)
        if previous is not None:
            previous_digest, previous_receipt = previous
            if previous_digest != input_digest:
                raise EvaluationBindingDrift(
                    "evaluation_id is already bound to different input"
                )
            return previous_receipt

        adapter = self._adapters.get(request.identity.evaluator_id)
        if adapter is None:
            raise EvaluatorBackendUnavailable(
                "no exact evaluator adapter is registered"
            )

        self._read_bound_artifact(
            request.hidden_set.artifact_ref,
            request.hidden_set.content_digest,
            "hidden set",
        )
        evidence_payloads = tuple(
            self._read_bound_artifact(
                entry.evidence_ref,
                entry.content_digest,
                "evidence",
            )
            for entry in request.evidence.entries
        )
        candidate = adapter.evaluate_candidate(
            request,
            evidence_payloads=evidence_payloads,
        )
        if candidate.input_digest != input_digest:
            raise EvaluatorBackendMalformed(
                "measurement candidate does not bind exact evaluator input"
            )

        payload = {
            "schema_version": "1.0",
            "receipt_id": self._receipt_id_factory(),
            "evaluation_id": request.evaluation_id,
            "proposal_id": request.proposal_id,
            "tenant_id": request.tenant_id,
            "workspace_id": request.workspace_id,
            "task_id": request.task_id,
            "run_id": request.run_id,
            "input_digest": input_digest,
            "evaluator_identity_digest": request.identity.canonical_digest(),
            "rubric_digest": request.rubric.canonical_digest(),
            "hidden_set_manifest_digest": request.hidden_set.canonical_digest(),
            "evidence_manifest_digest": request.evidence.canonical_digest(),
            "score": candidate.score,
            "uncertainty": candidate.uncertainty,
            "failure_reasons": candidate.failure_reasons,
            "sealed_at": self._clock(),
        }
        receipt_digest = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        receipt = EvaluationReceipt(**payload, receipt_digest=receipt_digest)
        self._sealed[request.evaluation_id] = (input_digest, receipt)
        return receipt
