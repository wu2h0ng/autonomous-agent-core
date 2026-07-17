"""Typed, non-authorizing custody contracts for R-STATE successor F."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol

from experiments.r_state_credit_1.contracts import ScenarioFamily


def _digest(value: str | None, label: str) -> None:
    if value is None:
        return
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


class ReceiptKind(str, Enum):
    PROVIDER_CANARY = "PROVIDER_CANARY"
    C7 = "C7"
    EXECUTOR = "EXECUTOR"
    INTEGRITY = "INTEGRITY"
    FREEZE = "FREEZE"
    RUN_AUTHORIZATION = "RUN_AUTHORIZATION"


@dataclass(frozen=True, slots=True)
class VerifiedReceipt:
    kind: ReceiptKind
    receipt_sha256: str
    subject_sha256: str
    signer_id: str
    signature_verified: bool

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReceiptKind):
            raise ValueError("receipt kind must be ReceiptKind")
        _digest(self.receipt_sha256, "receipt_sha256")
        _digest(self.subject_sha256, "subject_sha256")
        if not isinstance(self.signer_id, str) or not self.signer_id.strip():
            raise ValueError("signer_id must be non-empty text")
        if not isinstance(self.signature_verified, bool):
            raise ValueError("signature_verified must be bool")


class ReceiptVerifier(Protocol):
    """External custody verifier; receipt fields cannot verify themselves."""

    def verify(self, receipt: VerifiedReceipt) -> bool: ...


@dataclass(frozen=True, slots=True)
class ExactSuccessorArtifacts:
    manifest_sha256: str
    artifact_sha256: Mapping[str, str]
    integrity_subject_sha256: str
    verified: bool

    @classmethod
    def load(cls, root: Path) -> ExactSuccessorArtifacts:
        manifest_path = root / (
            "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-MANIFEST-2026-07-17.json"
        )
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
        if (
            not isinstance(manifest, dict)
            or manifest.get("status") != "CANDIDATE_EXACT_BYTES_NOT_FROZEN"
            or manifest.get("active_freeze_input") is not False
            or not isinstance(manifest.get("artifact_sha256"), dict)
        ):
            raise ValueError("successor manifest schema or status drift")
        hashes: dict[str, str] = {}
        for relative, expected in manifest["artifact_sha256"].items():
            if not isinstance(relative, str) or not isinstance(expected, str):
                raise ValueError("successor manifest artifact schema drift")
            _digest(expected, f"artifact_sha256[{relative}]")
            actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"successor artifact digest drift: {relative}")
            hashes[relative] = expected
        manifest_sha256 = hashlib.sha256(raw).hexdigest()
        integrity_subject = hashlib.sha256(
            json.dumps(
                {"manifest_sha256": manifest_sha256, "artifact_sha256": hashes},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return cls(
            manifest_sha256=manifest_sha256,
            artifact_sha256=hashes,
            integrity_subject_sha256=integrity_subject,
            verified=True,
        )


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
    artifact_manifest_sha256: str
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
            "artifact_manifest_sha256",
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
            self.max_total_input_tokens != 2_240_000
            or self.max_total_output_tokens != 1_120_000
        ):
            raise ValueError(
                "token budgets must equal the exact frozen candidate budgets"
            )


@dataclass(frozen=True, slots=True)
class SuccessorReadiness:
    status: str
    blockers: tuple[str, ...]

    @classmethod
    def evaluate(
        cls,
        bundle: ExecutionBundle,
        *,
        artifacts: ExactSuccessorArtifacts | None = None,
        receipts: tuple[VerifiedReceipt, ...] = (),
        receipt_verifier: ReceiptVerifier | None = None,
    ) -> SuccessorReadiness:
        blockers: list[str] = []
        if artifacts is None:
            blockers.append("exact successor artifact bundle absent")
        else:
            if not artifacts.verified:
                blockers.append("exact successor artifact bundle is unverified")
            if bundle.artifact_manifest_sha256 != artifacts.manifest_sha256:
                blockers.append("successor manifest digest drift")
            expected_local = {
                "runner_sha256": "experiments/r_state_credit_1/recast_result_runner.py",
                "scorer_sha256": "experiments/r_state_credit_1/recast_scorer.py",
                "prereg_sha256": "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-CANDIDATE-2026-07-17.json",
            }
            for field, path in expected_local.items():
                if getattr(bundle, field) != artifacts.artifact_sha256.get(path):
                    blockers.append(
                        f"{field} is not bound to the exact successor manifest"
                    )
        if bundle.future_freeze_receipt_sha256 is None:
            blockers.append("future freeze receipt absent")
        if bundle.run_authorization_freeze_sha256 is None:
            blockers.append("run authorization absent")
        by_kind: dict[ReceiptKind, VerifiedReceipt] = {}
        for receipt in receipts:
            if receipt.kind in by_kind:
                blockers.append(f"duplicate {receipt.kind.value} receipt")
            by_kind[receipt.kind] = receipt
        for kind in ReceiptKind:
            if kind not in by_kind:
                blockers.append(f"verified {kind.value} receipt absent")
        if len({item.receipt_sha256 for item in receipts}) != len(receipts):
            blockers.append("receipt digests must be distinct")
        if len({item.subject_sha256 for item in receipts}) != len(receipts):
            blockers.append("receipt subjects must be globally distinct")
        if len({item.signer_id for item in receipts}) != len(receipts):
            blockers.append("receipt signers must be role-distinct")
        if receipt_verifier is None:
            blockers.append("external receipt verifier absent")
        elif any(
            not item.signature_verified or not receipt_verifier.verify(item)
            for item in receipts
        ):
            blockers.append("external receipt signature verification failed")
        if artifacts is not None:
            expected_subjects = {
                ReceiptKind.PROVIDER_CANARY: bundle.provider_binding_sha256,
                ReceiptKind.C7: bundle.c7_schema_sha256,
                ReceiptKind.EXECUTOR: bundle.runner_sha256,
                ReceiptKind.INTEGRITY: artifacts.integrity_subject_sha256,
                ReceiptKind.FREEZE: artifacts.manifest_sha256,
            }
            for kind, subject in expected_subjects.items():
                receipt = by_kind.get(kind)
                if receipt is not None and receipt.subject_sha256 != subject:
                    blockers.append(f"{kind.value} receipt subject drift")
            freeze = by_kind.get(ReceiptKind.FREEZE)
            authorization = by_kind.get(ReceiptKind.RUN_AUTHORIZATION)
            if freeze is not None:
                if bundle.future_freeze_receipt_sha256 != freeze.receipt_sha256:
                    blockers.append("future freeze receipt binding drift")
                if authorization is not None and (
                    authorization.subject_sha256 != freeze.receipt_sha256
                ):
                    blockers.append(
                        "run authorization does not reference future freeze"
                    )
            if authorization is not None and (
                bundle.run_authorization_freeze_sha256 != authorization.receipt_sha256
            ):
                blockers.append("run authorization receipt binding drift")
        return cls(
            status="READY" if not blockers else "NOT_READY", blockers=tuple(blockers)
        )
