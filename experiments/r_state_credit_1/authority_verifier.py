"""Independent authority artifact verification for R-STATE-CREDIT-1.

The verifier checks that the five required authority artifacts were issued by
distinct, allowed identities (not the builder), that their signatures verify,
that they have not expired, that witness references are present, and that the
cross-references between artifacts are internally consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from experiments.r_state_credit_1.authority_artifacts import (
    AuthorityArtifact,
    AuthorityArtifactBundle,
    compute_payload_digest,
)
from experiments.r_state_credit_1.signature_backend import SignatureBackend


class AuthorityVerificationError(ValueError):
    """Raised when an authority bundle fails an independent verification check."""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of verifying an authority artifact bundle."""

    accepted: bool
    rejection_reason: str | None
    verified_identities: tuple[str, ...]


class AuthorityVerifier:
    """Verify an ``AuthorityArtifactBundle`` against frozen signer lists.

    Parameters
    ----------
    allowed_signers:
        Set of canonical identity keys ``"{principal_id}:{instance_id}"`` that
        are permitted to sign authority artifacts. The five required artifact
        types must each be signed by a distinct key from this set.
    builder_identities:
        Set of identity keys that represent the builder. Any artifact signed by
        one of these keys is rejected immediately (G8 authority builder
        rejection).
    backend:
        Pluggable signature backend. Tests use ``TestHmacBackend``; production
        code is expected to substitute a real Ed25519 backend.
    witness_repository:
        Optional local root of the separate witness repository. When supplied,
        each witness reference is required to resolve to an existing file or
        directory under this root.
    now:
        ISO-8601 UTC timestamp used as the expiration comparison point. Defaults
        to the current UTC time at construction.
    """

    def __init__(
        self,
        *,
        allowed_signers: set[str],
        builder_identities: set[str],
        backend: SignatureBackend,
        witness_repository: Path | None = None,
        now: str | None = None,
    ) -> None:
        self._allowed_signers = set(allowed_signers)
        self._builder_identities = set(builder_identities)
        self._backend = backend
        self._witness_repository = witness_repository
        if now is None:
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self._now = now

    def _fail(self, reason: str) -> VerificationResult:
        return VerificationResult(
            accepted=False,
            rejection_reason=reason,
            verified_identities=(),
        )

    def _verify_single_artifact(
        self,
        artifact: AuthorityArtifact,
        expected_type: str,
    ) -> VerificationResult:
        identity = artifact.identity_key()

        if identity in self._builder_identities:
            return self._fail(
                f"builder identity {identity!r} is not allowed to mint "
                f"{expected_type} artifacts"
            )

        if identity not in self._allowed_signers:
            return self._fail(
                f"identity {identity!r} is not in the allowed signer list "
                f"for {expected_type}"
            )

        if artifact.artifact_type != expected_type:
            return self._fail(
                f"expected artifact_type {expected_type!r}, got "
                f"{artifact.artifact_type!r}"
            )

        if artifact.expires_at < self._now:
            return self._fail(
                f"artifact {artifact.artifact_id!r} expired at "
                f"{artifact.expires_at} (now {self._now})"
            )

        if not artifact.witness_refs:
            return self._fail(
                f"artifact {artifact.artifact_id!r} has no witness references"
            )

        if self._witness_repository is not None:
            for witness_ref in artifact.witness_refs:
                resolved = self._witness_repository / witness_ref
                try:
                    resolved.resolve().relative_to(
                        self._witness_repository.resolve()
                    )
                except ValueError:
                    return self._fail(
                        f"witness reference {witness_ref!r} escapes witness repository"
                    )
                if not resolved.exists():
                    return self._fail(
                        f"witness reference {witness_ref!r} does not exist"
                    )

        recomputed = compute_payload_digest(artifact.content_mapping())
        if recomputed != artifact.payload_digest:
            return self._fail(
                f"payload digest mismatch for {artifact.artifact_id!r}: "
                f"expected {recomputed}, got {artifact.payload_digest}"
            )

        message = bytes.fromhex(artifact.payload_digest)
        if not self._backend.verify(identity, message, artifact.signature_bytes):
            return self._fail(
                f"signature verification failed for {artifact.artifact_id!r} "
                f"signed by {identity}"
            )

        return VerificationResult(
            accepted=True,
            rejection_reason=None,
            verified_identities=(identity,),
        )

    def _verify_cross_references(
        self,
        bundle: AuthorityArtifactBundle,
    ) -> VerificationResult:
        prereg = bundle.prereg_acceptance
        arch = bundle.architecture_acceptance
        freeze = bundle.native_freeze_lock
        c7 = bundle.c7_acceptance
        authz = bundle.run_authorization

        checks: list[tuple[str, AuthorityArtifact, str, str]] = [
            (
                "prereg_acceptance_digest",
                prereg,
                freeze.prereg_acceptance_digest,
                "native-freeze-lock",
            ),
            (
                "architecture_acceptance_digest",
                arch,
                freeze.architecture_acceptance_digest,
                "native-freeze-lock",
            ),
            (
                "freeze_lock_digest",
                freeze,
                c7.freeze_lock_digest,
                "c7-acceptance",
            ),
            (
                "c7_acceptance_digest",
                c7,
                authz.c7_acceptance_digest,
                "run-authorization",
            ),
            (
                "freeze_lock_digest",
                freeze,
                authz.freeze_lock_digest,
                "run-authorization",
            ),
        ]

        for field_name, source, expected_digest, target_label in checks:
            actual = compute_payload_digest(source.content_mapping())
            if actual != expected_digest:
                return self._fail(
                    f"cross-reference mismatch: {field_name} in {target_label} "
                    f"expected {expected_digest}, artifact digest is {actual}"
                )

        return VerificationResult(
            accepted=True,
            rejection_reason=None,
            verified_identities=(),
        )

    def _check_acceptance_flags(
        self,
        bundle: AuthorityArtifactBundle,
    ) -> VerificationResult:
        # native-freeze-lock does not carry an acceptance flag per amendment §5.2.3.
        for artifact, expected_type in (
            (bundle.prereg_acceptance, "prereg-acceptance"),
            (bundle.architecture_acceptance, "architecture-acceptance"),
            (bundle.c7_acceptance, "c7-acceptance"),
            (bundle.run_authorization, "run-authorization"),
        ):
            content = artifact.content_mapping()
            if content.get("acceptance") is not True:
                return self._fail(
                    f"{expected_type} artifact acceptance flag is not true"
                )

        authz_content = bundle.run_authorization.content_mapping()
        if authz_content.get("max_runs") != 1 or authz_content.get("result_bearing") is not True:
            return self._fail(
                "run authorization must authorize exactly one result-bearing run"
            )

        return VerificationResult(
            accepted=True,
            rejection_reason=None,
            verified_identities=(),
        )

    def verify(
        self,
        bundle: AuthorityArtifactBundle,
        *,
        prereg_payload_digest: str | None = None,
    ) -> VerificationResult:
        """Verify ``bundle`` and return a typed ``VerificationResult``.

        Parameters
        ----------
        bundle:
            The five authority artifacts required for a run.
        prereg_payload_digest:
            Optional SHA-256 digest of the run's preregistration candidate. When
            supplied, the prereg-acceptance artifact's ``prereg_sha256`` field
            must match it.

        Returns
        -------
        VerificationResult
            ``accepted`` is ``True`` only if every check passes and the five
            artifacts were signed by five distinct allowed identities.
        """
        try:
            typed_checks: list[
                tuple[AuthorityArtifact, str]
            ] = [
                (bundle.prereg_acceptance, "prereg-acceptance"),
                (bundle.architecture_acceptance, "architecture-acceptance"),
                (bundle.native_freeze_lock, "native-freeze-lock"),
                (bundle.c7_acceptance, "c7-acceptance"),
                (bundle.run_authorization, "run-authorization"),
            ]
        except AttributeError as exc:
            return self._fail(f"bundle is missing a required artifact: {exc}")

        identities: set[str] = set()
        verified: list[str] = []

        for artifact, expected_type in typed_checks:
            result = self._verify_single_artifact(artifact, expected_type)
            if not result.accepted:
                return result

            identity = artifact.identity_key()
            if identity in identities:
                return self._fail(
                    f"identity {identity!r} signed more than one artifact"
                )
            identities.add(identity)
            verified.append(identity)

        cross_ref_result = self._verify_cross_references(bundle)
        if not cross_ref_result.accepted:
            return cross_ref_result

        acceptance_result = self._check_acceptance_flags(bundle)
        if not acceptance_result.accepted:
            return acceptance_result

        if (
            prereg_payload_digest is not None
            and bundle.prereg_acceptance.prereg_sha256 != prereg_payload_digest
        ):
            return self._fail(
                "prereg-acceptance prereg_sha256 does not match the supplied "
                "run preregistration payload digest"
            )

        if len(verified) != 5:
            return self._fail("bundle must contain five distinct signer identities")

        return VerificationResult(
            accepted=True,
            rejection_reason=None,
            verified_identities=tuple(verified),
        )

    def verify_binding_artifacts(
        self,
        builder_id: str,
        bundle: AuthorityArtifactBundle,
    ) -> VerificationResult:
        """Convenience entry point matching the design amendment outline.

        Verifies the bundle and additionally rejects any artifact whose
        ``signer_principal_id`` equals ``builder_id``.
        """
        builder_keys = {f"{builder_id}:{builder_id}"} | self._builder_identities
        if builder_id not in self._builder_identities:
            builder_keys.add(builder_id)
        original_builder = self._builder_identities
        self._builder_identities = builder_keys
        try:
            return self.verify(bundle)
        finally:
            self._builder_identities = original_builder
