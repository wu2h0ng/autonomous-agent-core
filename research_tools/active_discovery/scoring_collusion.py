from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .canonical import content_digest


COLLUSION_MANIFEST_SCHEMA = "active-discovery-scorer-candidate-collusion/v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CollusionError(ValueError):
    """A collusion audit or its fixed Q-SCORE manifest is malformed."""


class ProvenanceRole(str, Enum):
    ACTOR = "ACTOR"
    SCORER = "SCORER"
    CHALLENGE = "CHALLENGE"
    TARGET = "TARGET"
    CONTRAST = "CONTRAST"
    WITNESS = "WITNESS"
    ADJUDICATOR = "ADJUDICATOR"


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise CollusionError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ProvenanceNode:
    role: ProvenanceRole
    principal_id: str
    workspace_digest: str
    source_generator_digest: str
    prompt_digest: str
    seed_stream_digest: str
    candidate_writable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.role, ProvenanceRole):
            raise CollusionError("provenance role is outside the closed enum")
        if not isinstance(self.principal_id, str) or not self.principal_id.strip():
            raise CollusionError("principal_id must be non-empty")
        for field_name in (
            "workspace_digest",
            "source_generator_digest",
            "prompt_digest",
            "seed_stream_digest",
        ):
            _digest(getattr(self, field_name), field_name)
        if not isinstance(self.candidate_writable, bool):
            raise CollusionError("candidate_writable must be a boolean")

    @property
    def origin_coordinates(self) -> tuple[str, ...]:
        return (
            self.principal_id,
            self.workspace_digest,
            self.source_generator_digest,
            self.prompt_digest,
            self.seed_stream_digest,
        )


@dataclass(frozen=True, slots=True)
class CollusionAudit:
    provenance_nodes: tuple[ProvenanceNode, ...]
    candidate_control_fields: tuple[str, ...] = ()
    identity_metric_drift: bool = False
    commitment_echo_used_as_truth: bool = False
    no_probe_exact_recovery: bool = False
    reused_commitment_across_roles: bool = False
    score_feedback_before_all_sealed: bool = False
    public_deterministic_formula: bool = True

    def __post_init__(self) -> None:
        if not self.provenance_nodes:
            raise CollusionError("collusion audit requires provenance nodes")
        roles = tuple(item.role for item in self.provenance_nodes)
        required = {
            ProvenanceRole.ACTOR,
            ProvenanceRole.SCORER,
            ProvenanceRole.CHALLENGE,
            ProvenanceRole.TARGET,
            ProvenanceRole.CONTRAST,
            ProvenanceRole.WITNESS,
        }
        if not required.issubset(roles) or len(roles) != len(set(roles)):
            raise CollusionError("audit requires exactly one node for each protected role")
        if any(
            not isinstance(item, str) or not item
            for item in self.candidate_control_fields
        ):
            raise CollusionError("candidate control fields must be non-empty strings")
        object.__setattr__(
            self,
            "candidate_control_fields",
            tuple(sorted(set(self.candidate_control_fields))),
        )
        for field_name in (
            "identity_metric_drift",
            "commitment_echo_used_as_truth",
            "no_probe_exact_recovery",
            "reused_commitment_across_roles",
            "score_feedback_before_all_sealed",
            "public_deterministic_formula",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise CollusionError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class CollusionResult:
    disposition: str
    reasons: tuple[str, ...]

    @property
    def result_digest(self) -> str:
        return content_digest(
            "scorer-candidate-collusion-result/v1",
            {"disposition": self.disposition, "reasons": list(self.reasons)},
        )


def evaluate_collusion(audit: CollusionAudit) -> CollusionResult:
    reasons: set[str] = set()
    if audit.candidate_control_fields:
        reasons.add("CANDIDATE_CONTROLLED_SCORER")
    if audit.identity_metric_drift:
        reasons.add("IDENTITY_METRIC_DRIFT")
    if audit.commitment_echo_used_as_truth:
        reasons.add("COMMITMENT_ECHO")
    if audit.no_probe_exact_recovery:
        reasons.add("NO_PROBE_HIDDEN_RECOVERY")
    if audit.reused_commitment_across_roles:
        reasons.add("CROSS_ROLE_COMMITMENT_REUSE")
    if audit.score_feedback_before_all_sealed:
        reasons.add("PRESEAL_SCORE_FEEDBACK")

    actor = next(
        item for item in audit.provenance_nodes if item.role is ProvenanceRole.ACTOR
    )
    protected = tuple(
        item
        for item in audit.provenance_nodes
        if item.role not in {ProvenanceRole.ACTOR, ProvenanceRole.ADJUDICATOR}
    )
    actor_origins = set(actor.origin_coordinates)
    if any(actor_origins & set(item.origin_coordinates) for item in protected):
        reasons.add("SAME_ORIGIN_PROVENANCE")
    if any(item.candidate_writable for item in protected):
        reasons.add("CANDIDATE_WRITABLE_PROTECTED_ROLE")

    ordered = tuple(sorted(reasons))
    return CollusionResult(
        disposition=(
            "INVALID_SCORER_CANDIDATE_COLLUSION"
            if ordered
            else "PASS_PROVENANCE_SEPARATED_CONTROL"
        ),
        reasons=ordered,
    )


def build_collusion_manifest() -> dict[str, object]:
    fixtures = (
        ("candidate-controlled-scorer", "CANDIDATE_CONTROLLED_SCORER"),
        ("identity-metric-drift", "IDENTITY_METRIC_DRIFT"),
        ("commitment-echo", "COMMITMENT_ECHO"),
        ("no-probe-hidden-recovery", "NO_PROBE_HIDDEN_RECOVERY"),
        ("cross-role-commitment-reuse", "CROSS_ROLE_COMMITMENT_REUSE"),
        ("same-origin-generation", "SAME_ORIGIN_PROVENANCE"),
        ("candidate-writable-hidden", "CANDIDATE_WRITABLE_PROTECTED_ROLE"),
        ("preseal-score-feedback", "PRESEAL_SCORE_FEEDBACK"),
    )
    payload: dict[str, object] = {
        "schema_version": COLLUSION_MANIFEST_SCHEMA,
        "mode": "NOT_EVIDENCE",
        "split": "Q-SCORE",
        "scientific_use": "PERMANENTLY_EXCLUDED",
        "adversarial_fixture_count": len(fixtures),
        "control_fixture_count": 1,
        "adversarial_fixtures": [
            {"fixture_id": fixture_id, "required_reason": reason}
            for fixture_id, reason in fixtures
        ],
        "control_fixture": {
            "fixture_id": "provenance-separated-behavior-control",
            "expected_disposition": "PASS_PROVENANCE_SEPARATED_CONTROL",
            "public_deterministic_formula": "PERMITTED",
        },
    }
    return {
        **payload,
        "manifest_digest": content_digest("scoring-collusion-manifest/v1", payload),
    }


def load_collusion_manifest(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollusionError("collusion manifest could not be read") from exc
    if not isinstance(raw, dict) or raw != build_collusion_manifest():
        raise CollusionError("collusion manifest does not match the closed fixtures")
    return raw
