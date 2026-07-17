"""Verified hand-off seam from the shared Freeze/Run service.

This module does not sign, freeze, or authorize a run.  It accepts only exact
signed receipts verified by an external custody implementation and produces a
non-serializable verified context for the local collector.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .contracts import canonical_digest
from .native_protocol import CollectionPermit


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: str, field: str) -> str:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be sha256")
    return value


@dataclass(frozen=True, slots=True)
class SignedReceipt:
    role: str
    subject_sha256: str
    signer_id: str
    public_key_sha256: str
    signature_sha256: str

    def __post_init__(self) -> None:
        if self.role not in {
            "COLLECTION_AUTHORITY",
            "RUN_AUTHORITY",
            "PROVIDER_CANARY_CUSTODIAN",
            "C7_AUTHORITY",
            "ORACLE_CUSTODIAN",
        }:
            raise ValueError("unsupported receipt role")
        if not self.signer_id.strip():
            raise ValueError("receipt signer is required")
        for field in ("subject_sha256", "public_key_sha256", "signature_sha256"):
            _sha(getattr(self, field), field)

    def digest(self) -> str:
        return canonical_digest(
            {field: getattr(self, field) for field in self.__dataclass_fields__}
        )


class ReceiptVerifier(Protocol):
    def verify(self, receipt: SignedReceipt) -> bool: ...


@dataclass(frozen=True, slots=True)
class RunExecutionPermit:
    route_id: str
    run_id: str
    global_run_sequence: int
    collection_permit_sha256: str
    prereg_spec_sha256: str
    exact_manifest_sha256: str
    freeze_subject_sha256: str
    correction_epoch: int
    corpus_manifest_sha256: str
    public_cases_sha256: str
    provider_bank_sha256: str
    budget_sha256: str
    freeze_receipt_sha256: str
    run_authority_receipt_sha256: str

    def __post_init__(self) -> None:
        if self.route_id != "R-EVAL-INDEP-1":
            raise ValueError("wrong execution route")
        if self.run_id != "r-eval-indep-1-rfinal-001":
            raise ValueError("run id is frozen")
        if self.global_run_sequence != 1:
            raise ValueError("only global sequence 1 is permitted")
        if self.correction_epoch < 0:
            raise ValueError("correction epoch cannot be negative")
        for field in (
            "collection_permit_sha256",
            "prereg_spec_sha256",
            "exact_manifest_sha256",
            "freeze_subject_sha256",
            "corpus_manifest_sha256",
            "public_cases_sha256",
            "provider_bank_sha256",
            "budget_sha256",
            "freeze_receipt_sha256",
            "run_authority_receipt_sha256",
        ):
            _sha(getattr(self, field), field)

    def to_mapping(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    def digest(self) -> str:
        return canonical_digest(self.to_mapping())


_VERIFIED = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedFreezeRunContext:
    collection_permit: CollectionPermit
    execution_permit: RunExecutionPermit
    verifier: ReceiptVerifier
    collection_receipt: SignedReceipt
    execution_receipt: SignedReceipt
    _token: object

    @classmethod
    def _create(
        cls,
        *,
        collection_permit: CollectionPermit,
        execution_permit: RunExecutionPermit,
        verifier: ReceiptVerifier,
        collection_receipt: SignedReceipt,
        execution_receipt: SignedReceipt,
    ) -> VerifiedFreezeRunContext:
        instance = object.__new__(cls)
        object.__setattr__(instance, "collection_permit", collection_permit)
        object.__setattr__(instance, "execution_permit", execution_permit)
        object.__setattr__(instance, "verifier", verifier)
        object.__setattr__(instance, "collection_receipt", collection_receipt)
        object.__setattr__(instance, "execution_receipt", execution_receipt)
        object.__setattr__(instance, "_token", _VERIFIED)
        return instance

    def assert_verified(self) -> None:
        if self._token is not _VERIFIED:
            raise ValueError("unverified FreezeRun context")


def verify_freeze_run_context(
    *,
    collection_permit: CollectionPermit,
    collection_receipt: SignedReceipt,
    execution_permit: RunExecutionPermit,
    execution_receipt: SignedReceipt,
    verifier: ReceiptVerifier,
) -> VerifiedFreezeRunContext:
    if not verifier.verify(collection_receipt) or not verifier.verify(
        execution_receipt
    ):
        raise ValueError("permit signature verification failed")
    if collection_receipt.role != "COLLECTION_AUTHORITY":
        raise ValueError("collection permit receipt has wrong role")
    if execution_receipt.role != "RUN_AUTHORITY":
        raise ValueError("execution permit receipt has wrong role")
    if collection_receipt.signer_id == execution_receipt.signer_id:
        raise ValueError("collection and run authority must be distinct")
    if execution_receipt.signer_id != collection_permit.run_authority_id:
        raise ValueError("execution receipt signer is not the bound run authority")
    if collection_receipt.subject_sha256 != collection_permit.digest():
        raise ValueError("collection permit receipt subject drift")
    if execution_receipt.subject_sha256 != execution_permit.digest():
        raise ValueError("execution permit receipt subject drift")
    if execution_permit.collection_permit_sha256 != collection_permit.digest():
        raise ValueError("execution permit does not bind collection permit")
    if execution_permit.prereg_spec_sha256 != collection_permit.prereg_lock_sha256:
        raise ValueError("collection/execution prereg binding drift")
    expected = (
        execution_permit.run_id,
        execution_permit.global_run_sequence,
        execution_permit.exact_manifest_sha256,
        execution_permit.correction_epoch,
    )
    actual = (
        collection_permit.run_id,
        collection_permit.single_run_sequence,
        collection_permit.exact_manifest_sha256,
        collection_permit.correction_epoch,
    )
    if actual != expected:
        raise ValueError("collection/execution permit binding drift")
    return VerifiedFreezeRunContext._create(
        collection_permit=collection_permit,
        execution_permit=execution_permit,
        verifier=verifier,
        collection_receipt=collection_receipt,
        execution_receipt=execution_receipt,
    )
