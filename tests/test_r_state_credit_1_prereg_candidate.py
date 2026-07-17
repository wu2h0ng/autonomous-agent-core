"""Stage-A preregistration-candidate guards.

These tests validate candidate structure and exact bytes only. They do not
freeze a preregistration, execute an arm, score an outcome, or create evidence.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily
from tests.support.git_reference import git_blob, materialize_git_files


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_A_REFERENCE_HEAD = "0ca38aa3491161fa115c0b58685cf408e5be106b"


def _prereg_module():
    from experiments.r_state_credit_1 import prereg_candidate

    return prereg_candidate


def _candidate():
    module = _prereg_module()
    return module.build_stage_a_prereg_candidate(REPO_ROOT)


def test_stage_a_candidate_declares_complete_non_authorizing_protocol() -> None:
    module = _prereg_module()
    candidate = _candidate()
    receipt = module.validate_stage_a_prereg_candidate(
        candidate,
        repo_root=REPO_ROOT,
    )

    assert receipt.status is module.CandidateValidationStatus.VALID_CANDIDATE_ONLY
    assert receipt.freeze_authority is False
    assert receipt.run_authority is False
    assert receipt.training_authority is False
    assert candidate["status"] == [
        "NOT_PREREGISTERED",
        "NOT_FROZEN",
        "NOT_RUN",
        "NO_TRAINING",
    ]
    assert {arm["arm_id"] for arm in candidate["arms"]} == {
        arm_id.value for arm_id in ArmId
    }
    assert {item["family"] for item in candidate["scenario_protocol"]["families"]} == {
        family.value for family in ScenarioFamily
    }
    assert candidate["scenario_protocol"]["held_out_episode_count"] == 140
    assert candidate["scenario_protocol"]["episode_length_turns_range_inclusive"] == [
        20,
        60,
    ]
    assert candidate["scenario_protocol"]["checkpoint_protocol"]["count"] == 4
    assert (
        candidate["scenario_protocol"]["checkpoint_protocol"]["selection_algorithm"]
        == "SEED_DETERMINED_COMBINATION_ENUMERATION_WITH_MIN_3_TURN_SPACING"
    )
    assert candidate["budgets"] == {
        "max_observable_bytes": 131_072,
        "max_representation_bytes": 65_536,
        "max_steps": 72,
        "max_tool_calls": 8,
        "max_wall_clock_units": 80,
        "token_proxy": "ceil_utf8_bytes_div_4",
        "o_max": 8_192,
        "b_a0": 262_144,
        "b_arm": 65_536,
    }
    assert candidate["metrics"]["primary"]["comparison_baseline"] == (
        ArmId.A0_FULL_LOG.value
    )
    assert candidate["missing_and_undefined"]["imputation"] == "FORBIDDEN"
    assert candidate["c7_and_authority"]["c7_may_abort"] is True
    assert candidate["c7_and_authority"]["c7_may_edit_scores"] is False
    assert candidate["verdict_grammar"]["allowed_verdicts"] == [
        "MET",
        "NOT_MET",
        "INVALID",
    ]
    assert {item["binding_id"] for item in candidate["required_freeze_bindings"]} == {
        "ACTOR_BINDING",
        "CORPUS_BINDING",
        "SCORER_BINDING",
        "REVIEW_AND_RUN_AUTHORITY_BINDING",
    }


def test_committed_candidate_matches_reference_generator_and_exact_bytes(
    tmp_path: Path,
) -> None:
    module = _prereg_module()
    candidate_relative = module.DEFAULT_CANDIDATE_RELATIVE_PATH
    reference_raw = git_blob(REPO_ROOT, STAGE_A_REFERENCE_HEAD, candidate_relative)
    candidate = json.loads(reference_raw)
    historical_root = materialize_git_files(
        REPO_ROOT,
        STAGE_A_REFERENCE_HEAD,
        [item["path"] for item in candidate["source_manifest"]] + [candidate_relative],
        tmp_path / "historical-stage-a",
    )
    candidate_path = historical_root / candidate_relative
    expected = (
        module.canonical_candidate_json(
            module.build_stage_a_prereg_candidate(historical_root)
        )
        + "\n"
    )

    assert reference_raw == expected.encode()
    assert (REPO_ROOT / candidate_relative).read_bytes() == reference_raw
    receipt = module.validate_stage_a_prereg_candidate_file(
        candidate_path, repo_root=historical_root
    )
    assert receipt.status is module.CandidateValidationStatus.VALID_CANDIDATE_ONLY


def test_validator_rejects_result_fields() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["result"] = {"selected_arm": ArmId.A3_TYPED_STATE.value}

    with pytest.raises(module.PreregCandidateViolation, match="FORBIDDEN_RESULT_FIELD"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_status_upgrade() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["status"] = ["PREREGISTERED", "FROZEN", "NOT_RUN", "NO_TRAINING"]

    with pytest.raises(module.PreregCandidateViolation, match="STATUS_BOUNDARY"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_missing_strong_full_log_baseline() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["arms"] = [
        arm for arm in candidate["arms"] if arm["arm_id"] != ArmId.A0_FULL_LOG.value
    ]

    with pytest.raises(module.PreregCandidateViolation, match="ARM_SET_MISMATCH"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_scenario_family_drift() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["scenario_protocol"]["families"].pop()

    with pytest.raises(module.PreregCandidateViolation, match="SCENARIO_SET_MISMATCH"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_budget_drift() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["budgets"]["max_steps"] = 65

    with pytest.raises(module.PreregCandidateViolation, match="BUDGET_DRIFT"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_seed_overlap() -> None:
    module = _prereg_module()
    candidate = _candidate()
    development_seed = candidate["seed_and_split_protocol"]["development_seeds"][0]
    candidate["seed_and_split_protocol"]["held_out_seeds"][0] = development_seed

    with pytest.raises(module.PreregCandidateViolation, match="SEED_SPLIT_OVERLAP"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_missing_value_imputation() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["missing_and_undefined"]["imputation"] = "ZERO"

    with pytest.raises(module.PreregCandidateViolation, match="MISSING_POLICY_DRIFT"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_c7_or_run_authority_expansion() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["c7_and_authority"]["candidate_grants_run_authority"] = True

    with pytest.raises(module.PreregCandidateViolation, match="AUTHORITY_BOUNDARY"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_verdict_grammar_expansion() -> None:
    module = _prereg_module()
    candidate = _candidate()
    candidate["verdict_grammar"]["allowed_verdicts"].append("INCONCLUSIVE")

    with pytest.raises(module.PreregCandidateViolation, match="VERDICT_GRAMMAR"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_rejects_source_manifest_drift() -> None:
    module = _prereg_module()
    candidate = copy.deepcopy(_candidate())
    candidate["source_manifest"][0]["sha256"] = "0" * 64

    with pytest.raises(module.PreregCandidateViolation, match="SOURCE_MANIFEST_DRIFT"):
        module.validate_stage_a_prereg_candidate(candidate, repo_root=REPO_ROOT)


def test_validator_cli_checks_only_and_emits_non_authorizing_receipt(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _prereg_module()
    candidate_relative = module.DEFAULT_CANDIDATE_RELATIVE_PATH
    candidate = json.loads(
        git_blob(REPO_ROOT, STAGE_A_REFERENCE_HEAD, candidate_relative)
    )
    historical_root = materialize_git_files(
        REPO_ROOT,
        STAGE_A_REFERENCE_HEAD,
        [item["path"] for item in candidate["source_manifest"]] + [candidate_relative],
        tmp_path / "historical-stage-a-cli",
    )
    candidate_path = historical_root / candidate_relative
    monkeypatch.setattr(module, "_default_repo_root", lambda: historical_root)

    assert module.main(["--check", str(candidate_path)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "VALID_CANDIDATE_ONLY"
    assert receipt["freeze_authority"] is False
    assert receipt["run_authority"] is False
    assert receipt["training_authority"] is False
