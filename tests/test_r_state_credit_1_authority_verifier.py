"""Phase 3 authority artifact verification tests.

These tests validate the non-self-minting, distinct-identity, signature, and
witness properties required by R-STATE-CREDIT-1 recast amendment §5.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from experiments.r_state_credit_1.authority_artifacts import (
    ArchitectureAcceptanceArtifact,
    AuthorityArtifactBundle,
    C7AcceptanceArtifact,
    NativeFreezeLockArtifact,
    PreregAcceptanceArtifact,
    RunAuthorizationArtifact,
)
from experiments.r_state_credit_1.authority_verifier import AuthorityVerifier
from experiments.r_state_credit_1.signature_backend import TestHmacBackend


BUILDER_IDENTITY = "builder:codex-1"
PREREG_IDENTITY = "reviewer:prereg-1"
ARCHITECTURE_IDENTITY = "reviewer:architecture-1"
FREEZER_IDENTITY = "freezer:native-1"
C7_IDENTITY = "c7-owner:security-1"
AUTHORIZER_IDENTITY = "founder:cto-1"

ALL_ALLOWED = {
    PREREG_IDENTITY,
    ARCHITECTURE_IDENTITY,
    FREEZER_IDENTITY,
    C7_IDENTITY,
    AUTHORIZER_IDENTITY,
}

SIGNED_AT = "2026-07-16T00:00:00+00:00"
EXPIRES_AT = "2099-12-31T23:59:59+00:00"
EXPIRED_AT = "2020-01-01T00:00:00+00:00"
CANDIDATE_SHA = "a" * 40
PREREG_SHA256 = "b" * 64


def _fresh_backend() -> TestHmacBackend:
    return TestHmacBackend(master_secret=b"phase-3-test-secret")


def _sign(
    artifact: Any,
    identity: str,
    witness_refs: tuple[str, ...],
    backend: TestHmacBackend,
    expires_at: str = EXPIRES_AT,
) -> None:
    principal, instance = identity.split(":", 1)
    artifact.sign(
        backend,
        identity,
        principal_id=principal,
        instance_id=instance,
        signed_at=SIGNED_AT,
        expires_at=expires_at,
        witness_refs=witness_refs,
    )


def _make_prereg(
    identity: str,
    backend: TestHmacBackend,
    witness_refs: tuple[str, ...] = ("reviews/R-STATE-CREDIT-1/prereg-acceptance.json",),
    expires_at: str = EXPIRES_AT,
) -> PreregAcceptanceArtifact:
    artifact = PreregAcceptanceArtifact(
        artifact_id="prereg-1",
        artifact_type="prereg-acceptance",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=SIGNED_AT,
        expires_at=expires_at,
        witness_refs=witness_refs,
        reviewer_id=identity.split(":", 1)[0],
        reviewed_at=SIGNED_AT,
        candidate_repo="autonomous-agent-core",
        candidate_branch="codex/r-state-credit-1-real-bindings-20260715",
        candidate_commit_sha=CANDIDATE_SHA,
        candidate_sha256=PREREG_SHA256,
        prereg_path="docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-16.json",
        prereg_sha256=PREREG_SHA256,
        acceptance=True,
        conditions=("INSTANCE_INDEPENDENCE_VALID",),
        notes="",
    )
    _sign(artifact, identity, witness_refs, backend, expires_at=expires_at)
    return artifact


def _make_architecture(
    identity: str,
    backend: TestHmacBackend,
    witness_refs: tuple[str, ...] = ("reviews/R-STATE-CREDIT-1/architecture-acceptance.json",),
    expires_at: str = EXPIRES_AT,
) -> ArchitectureAcceptanceArtifact:
    artifact = ArchitectureAcceptanceArtifact(
        artifact_id="arch-1",
        artifact_type="architecture-acceptance",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=SIGNED_AT,
        expires_at=expires_at,
        witness_refs=witness_refs,
        reviewer_id=identity.split(":", 1)[0],
        reviewed_at=SIGNED_AT,
        candidate_commit_sha=CANDIDATE_SHA,
        candidate_sha256=PREREG_SHA256,
        rr_0029_delta="docs/research/RR-0029-delta.md",
        rr_0031_delta="docs/research/RR-0031-delta.md",
        mechanism_file_hashes={
            "experiments/r_state_credit_1/real_corpus.py": "c" * 64,
        },
        acceptance=True,
        notes="",
    )
    _sign(artifact, identity, witness_refs, backend, expires_at=expires_at)
    return artifact


def _make_freeze(
    identity: str,
    backend: TestHmacBackend,
    prereg: PreregAcceptanceArtifact,
    architecture: ArchitectureAcceptanceArtifact,
    witness_refs: tuple[str, ...] = ("reviews/R-STATE-CREDIT-1/native-freeze-lock.json",),
    expires_at: str = EXPIRES_AT,
) -> NativeFreezeLockArtifact:
    from experiments.r_state_credit_1.authority_artifacts import compute_payload_digest

    artifact = NativeFreezeLockArtifact(
        artifact_id="freeze-1",
        artifact_type="native-freeze-lock",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=SIGNED_AT,
        expires_at=expires_at,
        witness_refs=witness_refs,
        freezer_id=identity.split(":", 1)[0],
        frozen_at=SIGNED_AT,
        candidate_commit_sha=CANDIDATE_SHA,
        candidate_sha256=PREREG_SHA256,
        prereg_acceptance_digest=compute_payload_digest(prereg.content_mapping()),
        architecture_acceptance_digest=compute_payload_digest(
            architecture.content_mapping()
        ),
        review_record_digests=("d" * 64,),
        builder_id="builder",
        builder_id_included_for_audit_only=True,
    )
    _sign(artifact, identity, witness_refs, backend, expires_at=expires_at)
    return artifact


def _make_c7(
    identity: str,
    backend: TestHmacBackend,
    freeze: NativeFreezeLockArtifact,
    witness_refs: tuple[str, ...] = ("reviews/R-STATE-CREDIT-1/c7-acceptance.json",),
    expires_at: str = EXPIRES_AT,
) -> C7AcceptanceArtifact:
    from experiments.r_state_credit_1.authority_artifacts import compute_payload_digest

    artifact = C7AcceptanceArtifact(
        artifact_id="c7-1",
        artifact_type="c7-acceptance",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=SIGNED_AT,
        expires_at=expires_at,
        witness_refs=witness_refs,
        owner_id=identity.split(":", 1)[0],
        epoch="epoch-1",
        capability_token_sha256="e" * 64,
        stop_path="reviews/R-STATE-CREDIT-1/stop.json",
        freeze_lock_digest=compute_payload_digest(freeze.content_mapping()),
        issued_at=SIGNED_AT,
        acceptance=True,
    )
    _sign(artifact, identity, witness_refs, backend, expires_at=expires_at)
    return artifact


def _make_authorization(
    identity: str,
    backend: TestHmacBackend,
    freeze: NativeFreezeLockArtifact,
    c7: C7AcceptanceArtifact,
    witness_refs: tuple[str, ...] = ("reviews/R-STATE-CREDIT-1/run-authorization.json",),
    expires_at: str = EXPIRES_AT,
) -> RunAuthorizationArtifact:
    from experiments.r_state_credit_1.authority_artifacts import compute_payload_digest

    artifact = RunAuthorizationArtifact(
        artifact_id="authz-1",
        artifact_type="run-authorization",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=SIGNED_AT,
        expires_at=expires_at,
        witness_refs=witness_refs,
        authorizer_id=identity.split(":", 1)[0],
        authorized_at=SIGNED_AT,
        freeze_lock_digest=compute_payload_digest(freeze.content_mapping()),
        c7_acceptance_digest=compute_payload_digest(c7.content_mapping()),
        max_runs=1,
        result_bearing=True,
        acceptance=True,
        notes="",
    )
    _sign(artifact, identity, witness_refs, backend, expires_at=expires_at)
    return artifact


def _make_bundle(
    backend: TestHmacBackend,
    identities: dict[str, str] | None = None,
    witness_root: Path | None = None,
) -> AuthorityArtifactBundle:
    ids = {
        "prereg": PREREG_IDENTITY,
        "architecture": ARCHITECTURE_IDENTITY,
        "freeze": FREEZER_IDENTITY,
        "c7": C7_IDENTITY,
        "authorization": AUTHORIZER_IDENTITY,
    }
    if identities is not None:
        ids.update(identities)

    def _witness(artifact_type: str) -> tuple[str, ...]:
        ref = f"reviews/R-STATE-CREDIT-1/{artifact_type}.json"
        if witness_root is not None:
            (witness_root / "reviews" / "R-STATE-CREDIT-1").mkdir(parents=True, exist_ok=True)
            (witness_root / ref).write_text("witness", encoding="utf-8")
        return (ref,)

    prereg = _make_prereg(ids["prereg"], backend, witness_refs=_witness("prereg-acceptance"))
    architecture = _make_architecture(
        ids["architecture"], backend, witness_refs=_witness("architecture-acceptance")
    )
    freeze = _make_freeze(
        ids["freeze"], backend, prereg, architecture, witness_refs=_witness("native-freeze-lock")
    )
    c7 = _make_c7(ids["c7"], backend, freeze, witness_refs=_witness("c7-acceptance"))
    authorization = _make_authorization(
        ids["authorization"], backend, freeze, c7, witness_refs=_witness("run-authorization")
    )
    bundle = AuthorityArtifactBundle(
        prereg_acceptance=prereg,
        architecture_acceptance=architecture,
        native_freeze_lock=freeze,
        c7_acceptance=c7,
        run_authorization=authorization,
    )
    if witness_root is not None:
        for artifact in bundle.all_artifacts():
            for ref in artifact.witness_refs:
                (witness_root / ref).write_text(
                    artifact.payload_digest, encoding="utf-8"
                )
    return bundle


def _verifier(
    *,
    builder_identities: set[str] | None = None,
    witness_repository: Path | None = None,
    now: str | None = None,
) -> AuthorityVerifier:
    return AuthorityVerifier(
        allowed_signers=ALL_ALLOWED,
        builder_identities=builder_identities or {BUILDER_IDENTITY},
        backend=_fresh_backend(),
        witness_repository=witness_repository,
        now=now,
    )


def test_builder_minted_artifact_rejected() -> None:
    backend = _fresh_backend()
    bundle = _make_bundle(backend, identities={"prereg": BUILDER_IDENTITY})
    verifier = _verifier()
    result = verifier.verify(bundle)
    assert not result.accepted
    assert "builder" in (result.rejection_reason or "").lower()
    assert BUILDER_IDENTITY in (result.rejection_reason or "")


def test_missing_signer_rejected() -> None:
    backend = _fresh_backend()
    unknown = "unknown:external-1"
    bundle = _make_bundle(backend, identities={"prereg": unknown})
    verifier = _verifier()
    result = verifier.verify(bundle)
    assert not result.accepted
    assert unknown in (result.rejection_reason or "")


def test_tampered_payload_rejected() -> None:
    backend = _fresh_backend()
    bundle = _make_bundle(backend)
    # Tamper with the content layer without re-signing.
    bundle.prereg_acceptance.reviewer_id = "tampered"
    verifier = _verifier()
    result = verifier.verify(bundle)
    assert not result.accepted
    assert "payload digest mismatch" in (result.rejection_reason or "")


def test_expired_artifact_rejected() -> None:
    backend = _fresh_backend()
    bundle = _make_bundle(
        backend,
        identities={"prereg": PREREG_IDENTITY},
    )
    # Re-create the prereg artifact with a past expiration.
    prereg = _make_prereg(
        PREREG_IDENTITY, backend, expires_at=EXPIRED_AT
    )
    bundle = AuthorityArtifactBundle(
        prereg_acceptance=prereg,
        architecture_acceptance=bundle.architecture_acceptance,
        native_freeze_lock=bundle.native_freeze_lock,
        c7_acceptance=bundle.c7_acceptance,
        run_authorization=bundle.run_authorization,
    )
    verifier = _verifier(now="2026-07-16T12:00:00+00:00")
    result = verifier.verify(bundle)
    assert not result.accepted
    assert "expired" in (result.rejection_reason or "").lower()


def test_distinct_identity_topology_required() -> None:
    backend = _fresh_backend()
    # Reuse the prereg reviewer identity for the architecture artifact.
    bundle = _make_bundle(backend, identities={"architecture": PREREG_IDENTITY})
    verifier = _verifier()
    result = verifier.verify(bundle)
    assert not result.accepted
    assert "signed more than one artifact" in (result.rejection_reason or "")


def test_valid_bundle_accepted() -> None:
    backend = _fresh_backend()
    with tempfile.TemporaryDirectory() as tmp:
        witness_root = Path(tmp)
        bundle = _make_bundle(backend, witness_root=witness_root)
        verifier = _verifier(witness_repository=witness_root)
        result = verifier.verify(bundle)
        assert result.accepted
        assert result.rejection_reason is None
        assert set(result.verified_identities) == ALL_ALLOWED


def test_witness_ref_required() -> None:
    backend = _fresh_backend()
    bundle = _make_bundle(backend)
    # Re-create the prereg artifact without any witness references.
    prereg = PreregAcceptanceArtifact(
        artifact_id="prereg-no-witness",
        artifact_type="prereg-acceptance",
        payload_digest="0" * 64,
        signer_principal_id="x",
        signer_instance_id="x",
        signature_bytes=b"",
        signed_at=SIGNED_AT,
        expires_at=EXPIRES_AT,
        witness_refs=(),
        reviewer_id=PREREG_IDENTITY.split(":", 1)[0],
        reviewed_at=SIGNED_AT,
        candidate_repo="autonomous-agent-core",
        candidate_branch="codex/r-state-credit-1-real-bindings-20260715",
        candidate_commit_sha=CANDIDATE_SHA,
        candidate_sha256=PREREG_SHA256,
        prereg_path="docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-16.json",
        prereg_sha256=PREREG_SHA256,
        acceptance=True,
        conditions=("INSTANCE_INDEPENDENCE_VALID",),
        notes="",
    )
    _sign(prereg, PREREG_IDENTITY, (), backend)
    bundle = AuthorityArtifactBundle(
        prereg_acceptance=prereg,
        architecture_acceptance=bundle.architecture_acceptance,
        native_freeze_lock=bundle.native_freeze_lock,
        c7_acceptance=bundle.c7_acceptance,
        run_authorization=bundle.run_authorization,
    )
    verifier = _verifier()
    result = verifier.verify(bundle)
    assert not result.accepted
    assert "no witness" in (result.rejection_reason or "").lower()


def test_witness_ref_must_exist_when_repository_supplied() -> None:
    backend = _fresh_backend()
    with tempfile.TemporaryDirectory() as tmp:
        witness_root = Path(tmp)
        bundle = _make_bundle(backend)
        verifier = _verifier(witness_repository=witness_root)
        result = verifier.verify(bundle)
        assert not result.accepted
        assert "does not exist" in (result.rejection_reason or "")


def test_witness_file_must_contain_artifact_digest() -> None:
    """A witness file that exists but lacks the artifact digest is rejected."""
    backend = _fresh_backend()
    with tempfile.TemporaryDirectory() as tmp:
        witness_root = Path(tmp)
        bundle = _make_bundle(backend, witness_root=witness_root)
        # Corrupt the prereg witness file so it no longer contains the digest.
        for ref in bundle.prereg_acceptance.witness_refs:
            (witness_root / ref).write_text("stale-or-empty-witness", encoding="utf-8")
        verifier = _verifier(witness_repository=witness_root)
        result = verifier.verify(bundle)
        assert not result.accepted
        assert "does not contain artifact payload digest" in (result.rejection_reason or "")


def test_builder_principal_any_instance_rejected() -> None:
    """An artifact signed with the builder principal and any instance is rejected."""
    backend = _fresh_backend()
    builder_id = "builder"
    builder_any_instance = "builder:external-1"
    allowed = ALL_ALLOWED | {builder_any_instance}
    with tempfile.TemporaryDirectory() as tmp:
        witness_root = Path(tmp)
        bundle = _make_bundle(
            backend,
            witness_root=witness_root,
            identities={"prereg": builder_any_instance},
        )
        verifier = AuthorityVerifier(
            allowed_signers=allowed,
            builder_identities={BUILDER_IDENTITY},
            backend=backend,
            witness_repository=witness_root,
        )
        result = verifier.verify_binding_artifacts(builder_id, bundle)
        assert not result.accepted
        assert "builder" in (result.rejection_reason or "").lower()
        assert builder_id in (result.rejection_reason or "")
