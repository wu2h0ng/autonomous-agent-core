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


@dataclass(frozen=True, slots=True)
class VerifiedReceiptIdentity:
    receipt_sha256: str
    signer_id: str
    public_key_sha256: str
    trust_registry_sha256: str

    def __post_init__(self) -> None:
        if not self.signer_id.strip():
            raise ValueError("verified signer is required")
        for field in (
            "receipt_sha256",
            "public_key_sha256",
            "trust_registry_sha256",
        ):
            _sha(getattr(self, field), field)

    def to_mapping(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


class ReceiptVerifier(Protocol):
    def verify(self, receipt: SignedReceipt) -> VerifiedReceiptIdentity | None: ...


def verify_receipt_identity(
    verifier: ReceiptVerifier, receipt: SignedReceipt
) -> VerifiedReceiptIdentity:
    identity = verifier.verify(receipt)
    if not isinstance(identity, VerifiedReceiptIdentity):
        raise ValueError("receipt signature or trusted signer verification failed")
    if (
        identity.receipt_sha256 != receipt.digest()
        or identity.signer_id != receipt.signer_id
        or identity.public_key_sha256 != receipt.public_key_sha256
    ):
        raise ValueError("receipt trusted identity does not match signed receipt")
    return identity


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
    collection_authority_id: str
    collection_authority_public_key_sha256: str
    run_authority_public_key_sha256: str
    c7_authority_public_key_sha256: str
    oracle_custodian_id: str
    oracle_custodian_public_key_sha256: str
    trust_registry_sha256: str

    def __post_init__(self) -> None:
        if self.route_id != "R-EVAL-INDEP-1":
            raise ValueError("wrong execution route")
        if self.run_id != "r-eval-indep-1-rfinal-001":
            raise ValueError("run id is frozen")
        if self.global_run_sequence != 1:
            raise ValueError("only global sequence 1 is permitted")
        if self.correction_epoch < 0:
            raise ValueError("correction epoch cannot be negative")
        authority_ids = (
            self.collection_authority_id,
            self.oracle_custodian_id,
        )
        if any(not authority_id.strip() for authority_id in authority_ids):
            raise ValueError("permit authority identities are required")
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
            "collection_authority_public_key_sha256",
            "run_authority_public_key_sha256",
            "c7_authority_public_key_sha256",
            "oracle_custodian_public_key_sha256",
            "trust_registry_sha256",
        ):
            _sha(getattr(self, field), field)
        bound_ids = (
            self.collection_authority_id,
            self.oracle_custodian_id,
        )
        if len(set(bound_ids)) != len(bound_ids):
            raise ValueError("permit authority identities must be distinct")
        bound_keys = (
            self.collection_authority_public_key_sha256,
            self.run_authority_public_key_sha256,
            self.c7_authority_public_key_sha256,
            self.oracle_custodian_public_key_sha256,
        )
        if len(set(bound_keys)) != len(bound_keys):
            raise ValueError("permit authority public keys must be distinct")

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
    collection_identity: VerifiedReceiptIdentity
    execution_identity: VerifiedReceiptIdentity
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
        collection_identity: VerifiedReceiptIdentity,
        execution_identity: VerifiedReceiptIdentity,
    ) -> VerifiedFreezeRunContext:
        instance = object.__new__(cls)
        object.__setattr__(instance, "collection_permit", collection_permit)
        object.__setattr__(instance, "execution_permit", execution_permit)
        object.__setattr__(instance, "verifier", verifier)
        object.__setattr__(instance, "collection_receipt", collection_receipt)
        object.__setattr__(instance, "execution_receipt", execution_receipt)
        object.__setattr__(instance, "collection_identity", collection_identity)
        object.__setattr__(instance, "execution_identity", execution_identity)
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
    collection_identity = verify_receipt_identity(verifier, collection_receipt)
    execution_identity = verify_receipt_identity(verifier, execution_receipt)
    if collection_receipt.role != "COLLECTION_AUTHORITY":
        raise ValueError("collection permit receipt has wrong role")
    if execution_receipt.role != "RUN_AUTHORITY":
        raise ValueError("execution permit receipt has wrong role")
    if collection_receipt.signer_id == execution_receipt.signer_id:
        raise ValueError("collection and run authority must be distinct")
    if execution_receipt.signer_id != collection_permit.run_authority_id:
        raise ValueError("execution receipt signer is not the bound run authority")
    if (
        collection_identity.signer_id != execution_permit.collection_authority_id
        or collection_identity.public_key_sha256
        != execution_permit.collection_authority_public_key_sha256
        or execution_identity.public_key_sha256
        != execution_permit.run_authority_public_key_sha256
        or collection_identity.trust_registry_sha256
        != execution_permit.trust_registry_sha256
        or execution_identity.trust_registry_sha256
        != execution_permit.trust_registry_sha256
    ):
        raise ValueError("permit authority identity/registry binding drift")
    authority_ids = {
        collection_identity.signer_id,
        collection_permit.run_authority_id,
        collection_permit.c7_authority_id,
        execution_permit.oracle_custodian_id,
    }
    if len(authority_ids) != 4:
        raise ValueError("collection/run/C7/oracle authority identities must differ")
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
        collection_identity=collection_identity,
        execution_identity=execution_identity,
    )
