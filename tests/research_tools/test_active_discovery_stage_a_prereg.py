from __future__ import annotations

import ast
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from research_tools.active_discovery import stage_a_prereg as prereg
from research_tools.active_discovery.canonical import content_digest
from research_tools.active_discovery.families.manifest import FamilyManifest
from research_tools.active_discovery.families.unified import UnifiedFamilyAdapter


REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_PATH = (
    REPO_ROOT / "research_tools/active_discovery/stage_a_prereg_candidate.json"
)
TOP_LEVEL_FIELDS = {
    "schema_version",
    "experiment_id",
    "mode",
    "candidate_state",
    "freeze_state",
    "run_state",
    "evidence_state",
    "authority_state",
    "approved_mechanism_base",
    "family_bindings",
    "family_matrix_digest",
    "arm_bindings",
    "random_arm_seed",
    "hidden_truth_contract",
    "qualification_metrics",
    "missing_data_policy",
    "leakage_policy",
    "c7_stop_policy",
    "verdict_grammar",
    "source_manifest",
    "source_manifest_digest",
    "candidate_digest",
}
EXPECTED_SOURCE_PATHS = (
    "research_tools/active_discovery/arm_runner.py",
    "research_tools/active_discovery/budget.py",
    "research_tools/active_discovery/canonical.py",
    "research_tools/active_discovery/catalogue.py",
    "research_tools/active_discovery/contracts.py",
    "research_tools/active_discovery/families/manifest.py",
    "research_tools/active_discovery/families/opaque_cli.py",
    "research_tools/active_discovery/families/opaque_expiry.py",
    "research_tools/active_discovery/families/opaque_graph.py",
    "research_tools/active_discovery/families/opaque_quota.py",
    "research_tools/active_discovery/families/unified.py",
    "research_tools/active_discovery/referee.py",
    "research_tools/active_discovery/selector.py",
    "research_tools/active_discovery/stage_a_prereg.py",
)


def test_stage_a_prereg_module_exists() -> None:
    assert (
        importlib.util.find_spec("research_tools.active_discovery.stage_a_prereg")
        is not None
    )


def test_materialized_stage_a_candidate_exists() -> None:
    assert CANDIDATE_PATH.is_file()


def test_materialized_stage_a_candidate_equals_builder_and_loads_read_only() -> None:
    raw = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))

    assert raw == prereg.build_stage_a_candidate(REPO_ROOT)
    validated = prereg.load_stage_a_candidate(CANDIDATE_PATH, REPO_ROOT)
    assert validated.candidate_digest == raw["candidate_digest"]


def test_stage_a_validator_exposes_no_run_freeze_or_write_authority() -> None:
    source_path = Path(prereg.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert imported_roots.isdisjoint(
        {"anthropic", "openai", "requests", "socket", "subprocess", "urllib"}
    )
    for forbidden_name in (
        "freeze_stage_a_candidate",
        "run_stage_a_candidate",
        "write_stage_a_candidate",
    ):
        assert not hasattr(prereg, forbidden_name)


def test_stage_a_candidate_has_closed_non_authoritative_states_and_verdicts() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)

    assert set(raw) == TOP_LEVEL_FIELDS
    assert raw["schema_version"] == prereg.STAGE_A_PREREG_SCHEMA
    assert raw["experiment_id"] == prereg.EXPERIMENT_ID
    assert raw["mode"] == "NOT_EVIDENCE"
    assert raw["candidate_state"] == "FREEZE_READY_CANDIDATE"
    assert raw["freeze_state"] == "NOT_FROZEN"
    assert raw["run_state"] == "NOT_RUN"
    assert raw["evidence_state"] == "NOT_EVIDENCE"
    assert raw["authority_state"] == "VALIDATION_ONLY"
    assert raw["approved_mechanism_base"] == prereg.APPROVED_MECHANISM_BASE
    assert set(raw["verdict_grammar"]) == {
        "QUALIFIED_FOR_NEXT_SCORING_SPEC",
        "REVISE",
        "INVALID_LEAKAGE",
        "INVALID_HIDDEN_TRUTH_ACCESS",
        "INVALID_MANIFEST_OR_SPLIT",
        "INVALID_SOURCE_DRIFT",
        "INVALID_BUDGET_MISMATCH",
        "INVALID_MISSING_DATA",
        "INVALID_C7_STOP_VIOLATION",
        "STOPPED_NO_VERDICT",
    }
    serialized_verdicts = " ".join(raw["verdict_grammar"])
    for forbidden in ("PASS", "MET", "NOT_MET", "NULL", "VOI_ADVANTAGE"):
        assert forbidden not in serialized_verdicts


def _bound_manifest(raw: object) -> FamilyManifest:
    assert isinstance(raw, dict)
    manifest_raw = raw["manifest"]
    assert isinstance(manifest_raw, dict)
    manifest = FamilyManifest.from_mapping(manifest_raw)
    assert raw["manifest_digest"] == manifest.manifest_digest
    assert UnifiedFamilyAdapter.from_manifest(manifest).manifest == manifest
    return manifest


def test_stage_a_candidate_binds_exact_family_split_and_manifests() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    bindings_raw = raw["family_bindings"]
    assert isinstance(bindings_raw, list)
    bindings: dict[str, dict[str, Any]] = {
        row["family_code"]: row for row in bindings_raw
    }
    expected = {
        "F1": ("QUALIFICATION_FAMILY", 101, 1009),
        "F2": ("QUALIFICATION_FAMILY", 103, 1013),
        "F3": ("QUALIFICATION_FAMILY", 107, 1019),
        "F4": ("HELD_OUT_FAMILY", None, 1021),
    }
    assert set(bindings) == set(expected)

    qualification_seeds: set[int] = set()
    evaluation_seeds: set[int] = set()
    for family_code, (role, qualification_seed, evaluation_seed) in expected.items():
        row = bindings[family_code]
        assert row["family_role"] == role
        if qualification_seed is None:
            assert row["qualification_manifest"] is None
        else:
            qualification = _bound_manifest(row["qualification_manifest"])
            assert qualification.family_code.value == family_code
            assert qualification.seed == qualification_seed
            assert qualification.probe_budget_units == 4
            qualification_seeds.add(qualification.seed)
        evaluation = _bound_manifest(row["evaluation_manifest"])
        assert evaluation.family_code.value == family_code
        assert evaluation.seed == evaluation_seed
        assert evaluation.probe_budget_units == 4
        evaluation_seeds.add(evaluation.seed)

    assert qualification_seeds.isdisjoint(evaluation_seeds)
    assert len(qualification_seeds | evaluation_seeds) == 7


def test_stage_a_candidate_binds_three_arms_to_one_exact_budget_and_matrix() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    arms = raw["arm_bindings"]
    assert isinstance(arms, list)

    assert [row["arm_kind"] for row in arms] == ["SYSTEMATIC", "RANDOM", "VOI"]
    assert {row["budget_units"] for row in arms} == {4}
    assert {row["family_matrix_digest"] for row in arms} == {
        raw["family_matrix_digest"]
    }
    assert raw["family_matrix_digest"] != "0" * 64
    assert raw["random_arm_seed"] == 1701


def test_stage_a_candidate_binds_exact_source_bytes() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    manifest = raw["source_manifest"]
    assert isinstance(manifest, list)

    assert tuple(row["path"] for row in manifest) == EXPECTED_SOURCE_PATHS
    assert tuple(row["path"] for row in manifest) == tuple(
        sorted(row["path"] for row in manifest)
    )
    for row in manifest:
        assert (
            row["sha256"]
            == hashlib.sha256((REPO_ROOT / row["path"]).read_bytes()).hexdigest()
        )
    assert raw["source_manifest_digest"] == content_digest(
        "active-discovery-stage-a-source-manifest", manifest
    )


def test_stage_a_candidate_commits_hidden_truth_for_post_seal_access_only() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    contract = raw["hidden_truth_contract"]
    assert isinstance(contract, dict)
    commitments = [
        {
            "family_code": row["family_code"],
            "evaluation_manifest_digest": row["evaluation_manifest"]["manifest_digest"],
            "hidden_configuration_digest": row["evaluation_manifest"]["manifest"][
                "hidden_configuration_digest"
            ],
        }
        for row in raw["family_bindings"]
    ]

    assert contract == {
        "access_policy": "REFEREE_ONLY_AFTER_TRANSCRIPT_SEAL",
        "committed_family_count": 4,
        "seal_digest": content_digest(
            "active-discovery-stage-a-hidden-truth-seal",
            {
                "source_manifest_digest": raw["source_manifest_digest"],
                "family_commitments": commitments,
            },
        ),
    }


def test_stage_a_candidate_freezes_integrity_metrics_and_missing_data_only() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)

    assert raw["qualification_metrics"] == {
        "metric_scope": "INSTRUMENT_INTEGRITY_ONLY",
        "expected_evaluation_cells": 12,
        "required_complete_sealed_receipts": 12,
        "required_exact_budget_receipts": 12,
        "maximum_preseal_hidden_truth_accesses": 0,
        "maximum_leakage_violations": 0,
        "maximum_c7_post_stop_adapter_accesses": 0,
        "scientific_arm_comparison": "FORBIDDEN",
    }
    assert raw["missing_data_policy"] == {
        "expected_cell_count": 12,
        "imputation": "FORBIDDEN",
        "arm_or_family_drop": "FORBIDDEN",
        "duplicate_cell_action": "INVALID_MISSING_DATA",
        "extra_cell_action": "INVALID_MISSING_DATA",
        "non_halt_missing_cell_action": "INVALID_MISSING_DATA",
        "clean_halt_missing_cell_action": "STOPPED_NO_VERDICT",
    }


def test_stage_a_candidate_freezes_leakage_and_c7_stop_policies() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    leakage = raw["leakage_policy"]
    assert isinstance(leakage, dict)
    assert leakage["actor_surface_violation_verdict"] == "INVALID_LEAKAGE"
    assert leakage["preseal_hidden_truth_verdict"] == "INVALID_HIDDEN_TRUTH_ACCESS"
    assert set(leakage["forbidden_actor_channels"]) == {
        "SOURCE_IDENTITY",
        "VERSION_LABEL",
        "FAMILY_IDENTITY",
        "HIDDEN_TEST",
        "REFEREE_SCORE",
        "ORACLE_OUTPUT",
        "MANIFEST_OR_SEAL_PAYLOAD",
    }
    for term in (
        "source_precedence",
        "repeat_mode",
        "unknown_mode",
        "empty_is_missing",
        "atomic_on_error",
        "opaquecli",
    ):
        assert term in leakage["forbidden_actor_terms"]

    assert raw["c7_stop_policy"] == {
        "halt_check": "BEFORE_DYNAMIC_ADAPTER_STATE_OR_EXECUTE",
        "post_halt_adapter_access_limit": 0,
        "clean_halt_verdict": "STOPPED_NO_VERDICT",
        "halt_after_integrity_violation": "PRESERVE_INVALID",
        "partial_verdict": "FORBIDDEN",
    }


def _redigest(raw: dict[str, Any]) -> dict[str, Any]:
    raw["candidate_digest"] = prereg.candidate_digest(raw)
    return raw


def test_stage_a_validator_accepts_exact_candidate_and_key_permutation() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    reordered = dict(reversed(tuple(raw.items())))

    validated = prereg.validate_stage_a_candidate(raw, REPO_ROOT)
    validated_reordered = prereg.validate_stage_a_candidate(reordered, REPO_ROOT)

    assert validated == validated_reordered
    assert validated.candidate_digest == raw["candidate_digest"]
    assert validated.source_manifest_digest == raw["source_manifest_digest"]
    assert validated.family_matrix_digest == raw["family_matrix_digest"]
    assert validated.candidate_state == "FREEZE_READY_CANDIDATE"


def test_stage_a_validator_rejects_unknown_top_level_field() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    raw["freeze_lock"] = "forbidden"
    _redigest(raw)

    with pytest.raises(prereg.StageAPreregValidationError, match="unknown fields"):
        prereg.validate_stage_a_candidate(raw, REPO_ROOT)


def test_stage_a_validator_rejects_candidate_digest_mismatch() -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    raw["candidate_digest"] = "0" * 64

    with pytest.raises(prereg.StageAPreregValidationError, match="digest mismatch"):
        prereg.validate_stage_a_candidate(raw, REPO_ROOT)


def test_stage_a_validator_rejects_nested_contract_tampering() -> None:
    baseline = prereg.build_stage_a_candidate(REPO_ROOT)

    def family_role(raw: dict[str, Any]) -> None:
        raw["family_bindings"][3]["family_role"] = "QUALIFICATION_FAMILY"

    def manifest_seed(raw: dict[str, Any]) -> None:
        raw["family_bindings"][0]["evaluation_manifest"]["manifest"]["seed"] = 9

    def arm_budget(raw: dict[str, Any]) -> None:
        raw["arm_bindings"][1]["budget_units"] = 5

    def matrix_digest(raw: dict[str, Any]) -> None:
        raw["family_matrix_digest"] = "1" * 64

    def hidden_seal(raw: dict[str, Any]) -> None:
        raw["hidden_truth_contract"]["seal_digest"] = "2" * 64

    def metric(raw: dict[str, Any]) -> None:
        raw["qualification_metrics"]["scientific_arm_comparison"] = "ALLOWED"

    def missing_policy(raw: dict[str, Any]) -> None:
        raw["missing_data_policy"]["imputation"] = "MEAN"

    def leakage_policy(raw: dict[str, Any]) -> None:
        raw["leakage_policy"]["forbidden_actor_terms"] = []

    def c7_policy(raw: dict[str, Any]) -> None:
        raw["c7_stop_policy"]["post_halt_adapter_access_limit"] = 1

    def verdict_grammar(raw: dict[str, Any]) -> None:
        raw["verdict_grammar"].append("PASS")

    mutators: tuple[Callable[[dict[str, Any]], None], ...] = (
        family_role,
        manifest_seed,
        arm_budget,
        matrix_digest,
        hidden_seal,
        metric,
        missing_policy,
        leakage_policy,
        c7_policy,
        verdict_grammar,
    )
    for mutate in mutators:
        tampered = copy.deepcopy(baseline)
        mutate(tampered)
        _redigest(tampered)
        with pytest.raises(
            prereg.StageAPreregValidationError,
            match="deterministic Stage-A contract",
        ):
            prereg.validate_stage_a_candidate(tampered, REPO_ROOT)


def test_stage_a_validator_rejects_source_byte_drift(tmp_path: Path) -> None:
    raw = prereg.build_stage_a_candidate(REPO_ROOT)
    for relative_path in EXPECTED_SOURCE_PATHS:
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPO_ROOT / relative_path).read_bytes())

    prereg.validate_stage_a_candidate(raw, tmp_path)
    drifted = tmp_path / "research_tools/active_discovery/canonical.py"
    drifted.write_bytes(drifted.read_bytes() + b"\n# source drift\n")

    with pytest.raises(prereg.StageAPreregValidationError, match="source drift"):
        prereg.validate_stage_a_candidate(raw, tmp_path)


def test_qualification_verdict_clean_early_halt_precedes_halt_caused_missing() -> None:
    audit = prereg.QualificationAudit(
        halted=True,
        missing_cells=12,
        halt_caused_missing_cells=12,
    )

    assert prereg.qualification_verdict(audit).value == "STOPPED_NO_VERDICT"


def test_qualification_verdict_preserves_violation_that_precedes_halt() -> None:
    audit = prereg.QualificationAudit(
        halted=True,
        missing_cells=12,
        halt_caused_missing_cells=12,
        leakage_violations=1,
    )

    assert prereg.qualification_verdict(audit).value == "INVALID_LEAKAGE"


@pytest.mark.parametrize(
    ("audit", "expected"),
    (
        (
            prereg.QualificationAudit(preseal_hidden_truth_accesses=1),
            "INVALID_HIDDEN_TRUTH_ACCESS",
        ),
        (
            prereg.QualificationAudit(manifest_or_split_violations=1),
            "INVALID_MANIFEST_OR_SPLIT",
        ),
        (
            prereg.QualificationAudit(source_drift_violations=1),
            "INVALID_SOURCE_DRIFT",
        ),
        (
            prereg.QualificationAudit(budget_mismatch_violations=1),
            "INVALID_BUDGET_MISMATCH",
        ),
        (
            prereg.QualificationAudit(c7_post_stop_accesses=1),
            "INVALID_C7_STOP_VIOLATION",
        ),
    ),
)
def test_qualification_verdict_maps_integrity_failures(
    audit: prereg.QualificationAudit, expected: str
) -> None:
    assert prereg.qualification_verdict(audit).value == expected


def test_qualification_verdict_orders_missing_revise_and_qualified() -> None:
    assert (
        prereg.qualification_verdict(prereg.QualificationAudit(missing_cells=1)).value
        == "INVALID_MISSING_DATA"
    )
    assert (
        prereg.qualification_verdict(
            prereg.QualificationAudit(qualification_failures=1)
        ).value
        == "REVISE"
    )
    assert (
        prereg.qualification_verdict(prereg.QualificationAudit()).value
        == "QUALIFIED_FOR_NEXT_SCORING_SPEC"
    )
