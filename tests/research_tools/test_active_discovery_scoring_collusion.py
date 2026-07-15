from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from research_tools.active_discovery.scoring_collusion import (
    COLLUSION_MANIFEST_SCHEMA,
    CollusionAudit,
    ProvenanceNode,
    ProvenanceRole,
    build_collusion_manifest,
    evaluate_collusion,
    load_collusion_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "research_tools/active_discovery/scoring_collusion_manifest.json"


def _node(role: ProvenanceRole, index: int, *, candidate_writable: bool = False) -> ProvenanceNode:
    def digest(label: str) -> str:
        return hashlib.sha256(f"{label}-{index}".encode()).hexdigest()

    return ProvenanceNode(
        role=role,
        principal_id=f"principal-{index}",
        workspace_digest=digest("workspace"),
        source_generator_digest=digest("source"),
        prompt_digest=digest("prompt"),
        seed_stream_digest=digest("seed"),
        candidate_writable=candidate_writable,
    )


def _control() -> CollusionAudit:
    roles = (
        ProvenanceRole.ACTOR,
        ProvenanceRole.SCORER,
        ProvenanceRole.CHALLENGE,
        ProvenanceRole.TARGET,
        ProvenanceRole.CONTRAST,
        ProvenanceRole.WITNESS,
    )
    return CollusionAudit(provenance_nodes=tuple(_node(role, 1 + index * 5) for index, role in enumerate(roles)))


def test_provenance_separated_behavior_grounded_control_passes() -> None:
    result = evaluate_collusion(_control())

    assert result.disposition == "PASS_PROVENANCE_SEPARATED_CONTROL"
    assert result.reasons == ()


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"candidate_control_fields": ("scorer_path",)}, "CANDIDATE_CONTROLLED_SCORER"),
        ({"identity_metric_drift": True}, "IDENTITY_METRIC_DRIFT"),
        ({"commitment_echo_used_as_truth": True}, "COMMITMENT_ECHO"),
        ({"no_probe_exact_recovery": True}, "NO_PROBE_HIDDEN_RECOVERY"),
        ({"reused_commitment_across_roles": True}, "CROSS_ROLE_COMMITMENT_REUSE"),
        ({"score_feedback_before_all_sealed": True}, "PRESEAL_SCORE_FEEDBACK"),
    ),
)
def test_closed_trap_kills_each_explicit_candidate_collusion_path(
    changes: dict[str, object], reason: str
) -> None:
    result = evaluate_collusion(replace(_control(), **changes))

    assert result.disposition == "INVALID_SCORER_CANDIDATE_COLLUSION"
    assert reason in result.reasons


def test_same_origin_and_candidate_writable_hidden_roles_are_killed() -> None:
    control = _control()
    actor = control.provenance_nodes[0]
    target = control.provenance_nodes[3]
    same_origin_target = replace(target, principal_id=actor.principal_id)
    result = evaluate_collusion(
        replace(
            control,
            provenance_nodes=(
                *control.provenance_nodes[:3],
                same_origin_target,
                *control.provenance_nodes[4:],
            ),
        )
    )
    assert result.disposition == "INVALID_SCORER_CANDIDATE_COLLUSION"
    assert "SAME_ORIGIN_PROVENANCE" in result.reasons

    writable = replace(target, candidate_writable=True)
    writable_result = evaluate_collusion(
        replace(
            control,
            provenance_nodes=(
                *control.provenance_nodes[:3],
                writable,
                *control.provenance_nodes[4:],
            ),
        )
    )
    assert "CANDIDATE_WRITABLE_PROTECTED_ROLE" in writable_result.reasons


def test_public_deterministic_score_formula_alone_is_not_a_false_positive() -> None:
    result = evaluate_collusion(
        replace(
            _control(),
            public_deterministic_formula=True,
            no_probe_exact_recovery=False,
        )
    )
    assert result.disposition == "PASS_PROVENANCE_SEPARATED_CONTROL"


def test_collusion_manifest_is_q_score_only_and_replays_exactly() -> None:
    expected = build_collusion_manifest()
    materialized = load_collusion_manifest(MANIFEST_PATH)

    assert materialized == expected
    assert materialized["schema_version"] == COLLUSION_MANIFEST_SCHEMA
    assert materialized["split"] == "Q-SCORE"
    assert materialized["scientific_use"] == "PERMANENTLY_EXCLUDED"
    assert isinstance(materialized["adversarial_fixture_count"], int)
    assert materialized["adversarial_fixture_count"] >= 7
    assert materialized["control_fixture_count"] == 1
