"""Freeze-blocker guards for the R-STATE-CREDIT-1 recast candidate.

These tests inspect candidate bytes and deterministic development episodes only.
They do not freeze, authorize, contact a provider, or execute a result run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS, ActorAction
from experiments.r_state_credit_1.interactive_env import (
    EpisodeStatus,
    InteractiveEpisode,
    PerturbationClass,
    RecastCheckpointLoss,
)
from experiments.r_state_credit_1.prereg_candidate import (
    build_stage_a_prereg_candidate,
)
from tests.support.git_reference import git_blob


REPO_ROOT = Path(__file__).resolve().parents[1]
RECAST_REFERENCE_HEAD = "0ca38aa3491161fa115c0b58685cf408e5be106b"
LEGACY_PREREG = (
    REPO_ROOT / "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREGISTRATION-2026-07-15.yaml"
)
RECAST_PREREG = (
    REPO_ROOT
    / "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.RECAST-RUN-CONTRACT-CANDIDATE-2026-07-17.json"
)
RECAST_MANIFEST = (
    REPO_ROOT
    / "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.RECAST-EXACT-CONTENT-MANIFEST-2026-07-17.json"
)


def test_candidate_action_set_is_derived_from_complete_actor_grammar() -> None:
    candidate = build_stage_a_prereg_candidate(REPO_ROOT)
    assert candidate["information_parity"]["same_action_set"] == [
        action.value for action in ALL_ACTIONS
    ]


def test_development_seed_recovery_grammar_has_both_deterministic_routes(
    tmp_path: Path,
) -> None:
    observed: set[ActorAction] = set()
    for seed_id in [101, 103, 107, 109, 113, 127, 131]:
        episode = InteractiveEpisode("TEST_FAMILY", seed_id, tmp_path / str(seed_id))
        try:
            while episode.status is EpisodeStatus.RUNNING:
                observation = episode.observe()
                if observation.event_class == PerturbationClass.DETERMINISTIC_RECOVERY:
                    observed.add(episode.referee_correct_action())
                episode.step(episode.referee_correct_action())
        finally:
            episode.cleanup()
    assert observed == {
        ActorAction.RECOVER_ROLLBACK,
        ActorAction.RECOVER_ROLL_FORWARD,
    }


def test_wrong_recovery_choice_is_not_mislabeled_as_effect_replay(
    tmp_path: Path,
) -> None:
    found = False
    for seed_id in range(200):
        episode = InteractiveEpisode("TEST_FAMILY", seed_id, tmp_path / str(seed_id))
        try:
            while episode.status is EpisodeStatus.RUNNING:
                observation = episode.observe()
                if observation.event_class == PerturbationClass.DETERMINISTIC_RECOVERY:
                    losses = episode.referee_loss_map()
                    correct = episode.referee_correct_action()
                    wrong_recovery = (
                        ActorAction.RECOVER_ROLL_FORWARD
                        if correct is ActorAction.RECOVER_ROLLBACK
                        else ActorAction.RECOVER_ROLLBACK
                    )
                    assert losses[wrong_recovery] is (
                        RecastCheckpointLoss.STALE_BELIEF_USE
                    )
                    found = True
                    break
                episode.step(episode.referee_correct_action())
        finally:
            episode.cleanup()
        if found:
            break
    assert found, "development probe did not reach deterministic recovery"


def test_candidate_trajectory_driver_exercises_all_arms_without_result_authority(
    tmp_path: Path,
) -> None:
    from experiments.r_state_credit_1.trajectory_driver import (
        run_checkpointed_episode,
    )

    episode, records = run_checkpointed_episode("TEST_FAMILY", 101, tmp_path / "driver")
    try:
        assert len(records) == 4
        assert all(
            set(record.resolved_actions) == set(record.arm_ids) for record in records
        )
        assert all(record.correct_action in ALL_ACTIONS for record in records)
    finally:
        episode.cleanup()


def test_legacy_formal_prereg_is_retired_and_recast_candidate_is_separate() -> None:
    legacy = LEGACY_PREREG.read_text(encoding="utf-8")
    assert "status: RETIRED_HISTORY_ONLY" in legacy
    assert "active_freeze_input: false" in legacy

    recast = json.loads(RECAST_PREREG.read_text(encoding="utf-8"))
    assert recast["status"] == "RECAST_CANDIDATE_NOT_FROZEN_NOT_RUN"
    assert recast["freeze_authority"] is False
    assert recast["run_authority"] is False
    assert recast["mechanism"]["trajectory_driver"] == (
        "experiments.r_state_credit_1.trajectory_driver.run_checkpointed_episode"
    )
    assert (
        recast["mechanism"]["trajectory_driver_sha256"]
        == hashlib.sha256(
            (
                REPO_ROOT / "experiments/r_state_credit_1/trajectory_driver.py"
            ).read_bytes()
        ).hexdigest()
    )
    files = set(recast["mechanism"]["files"])
    assert "experiments/r_state_credit_1/trajectory_driver.py" in files
    assert "experiments/r_state_credit_1/result_runner.py" not in files
    assert "experiments/r_state_credit_1/arms.py" not in files


def test_recast_exact_manifest_binds_every_declared_candidate_byte() -> None:
    recast = json.loads(RECAST_PREREG.read_text(encoding="utf-8"))
    manifest = json.loads(RECAST_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "CANDIDATE_ONLY_NOT_FROZEN"
    hashes = manifest["mechanism_artifact_hashes"]
    assert set(hashes) == set(recast["mechanism"]["files"]) | {
        RECAST_PREREG.relative_to(REPO_ROOT).as_posix()
    }
    for relative_path, expected in hashes.items():
        actual = hashlib.sha256(
            git_blob(REPO_ROOT, RECAST_REFERENCE_HEAD, relative_path)
        ).hexdigest()
        assert actual == expected, relative_path
    assert RECAST_PREREG.read_bytes() == git_blob(
        REPO_ROOT,
        RECAST_REFERENCE_HEAD,
        RECAST_PREREG.relative_to(REPO_ROOT).as_posix(),
    )
