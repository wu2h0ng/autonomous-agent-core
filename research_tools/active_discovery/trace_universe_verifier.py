from __future__ import annotations

import re
from dataclasses import dataclass

from .canonical import content_digest
from .scoring_contracts import BehaviorTrace, ChallengeSequence


TRACE_UNIVERSE_CERTIFICATE_SCHEMA = "active-discovery-trace-universe-certificate/v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TraceUniverseError(ValueError):
    """The claimed public trace universe is not a complete finite partition."""


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise TraceUniverseError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class TraceWitness:
    configuration_digest: str
    trace: BehaviorTrace
    clean_reset: bool

    def __post_init__(self) -> None:
        _digest(self.configuration_digest, "configuration_digest")
        if not isinstance(self.trace, BehaviorTrace):
            raise TraceUniverseError("trace witness requires a BehaviorTrace")
        if not isinstance(self.clean_reset, bool):
            raise TraceUniverseError("clean_reset must be a boolean")


@dataclass(frozen=True, slots=True)
class TraceUniverseCertificate:
    domain_manifest_digest: str
    challenge_digest: str
    configuration_count: int
    deduplicated_trace_count: int
    ordered_trace_encodings: tuple[str, ...]
    verifier_source_digest: str
    schema_version: str = TRACE_UNIVERSE_CERTIFICATE_SCHEMA

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "domain_manifest_digest": self.domain_manifest_digest,
            "challenge_digest": self.challenge_digest,
            "configuration_count": self.configuration_count,
            "deduplicated_trace_count": self.deduplicated_trace_count,
            "ordered_trace_encodings": list(self.ordered_trace_encodings),
            "verifier_source_digest": self.verifier_source_digest,
        }

    @property
    def certificate_digest(self) -> str:
        return content_digest("trace-universe-certificate/v1", self.to_mapping())


def verify_trace_universe(
    *,
    domain_manifest_digest: str,
    challenge: ChallengeSequence,
    verifier_source_digest: str,
    expected_configuration_digests: tuple[str, ...],
    witnesses: tuple[TraceWitness, ...],
) -> TraceUniverseCertificate:
    """Recompute the full-domain partition without exposing its witness map."""

    _digest(domain_manifest_digest, "domain_manifest_digest")
    _digest(verifier_source_digest, "verifier_source_digest")
    if not isinstance(challenge, ChallengeSequence):
        raise TraceUniverseError("challenge must be a ChallengeSequence")
    for value in expected_configuration_digests:
        _digest(value, "expected_configuration_digest")
    if not expected_configuration_digests or len(expected_configuration_digests) != len(
        set(expected_configuration_digests)
    ):
        raise TraceUniverseError(
            "expected configuration domain must be non-empty and duplicate-free"
        )
    if len(witnesses) != len(expected_configuration_digests):
        raise TraceUniverseError("every configuration requires exactly one configuration witness")
    witness_ids = tuple(item.configuration_digest for item in witnesses)
    if len(witness_ids) != len(set(witness_ids)) or set(witness_ids) != set(
        expected_configuration_digests
    ):
        raise TraceUniverseError("configuration witness set does not match the domain")
    if any(not item.clean_reset for item in witnesses):
        raise TraceUniverseError("every configuration witness requires a clean reset")

    public_encodings = tuple(item.canonical_bytes for item in challenge.traces)
    if len(public_encodings) != len(set(public_encodings)):
        raise TraceUniverseError("public trace universe has duplicate complete-trace encodings")
    if public_encodings != tuple(sorted(public_encodings)):
        raise TraceUniverseError("public trace universe is not in canonical byte order")
    if not 2 <= len(public_encodings) <= 16:
        raise TraceUniverseError("deduplicated trace universe must contain 2-16 traces")

    witnessed_encodings: set[bytes] = set()
    public_set = set(public_encodings)
    for witness in witnesses:
        if len(witness.trace.atoms) != len(challenge.steps):
            raise TraceUniverseError("witness trace step count does not match the challenge")
        encoding = witness.trace.canonical_bytes
        if encoding not in public_set:
            raise TraceUniverseError("configuration maps outside public trace universe")
        witnessed_encodings.add(encoding)
    if witnessed_encodings != public_set:
        raise TraceUniverseError("every public trace requires at least one configuration witness")

    return TraceUniverseCertificate(
        domain_manifest_digest=domain_manifest_digest,
        challenge_digest=challenge.challenge_digest,
        configuration_count=len(expected_configuration_digests),
        deduplicated_trace_count=len(public_encodings),
        ordered_trace_encodings=tuple(item.decode("utf-8") for item in public_encodings),
        verifier_source_digest=verifier_source_digest,
    )
