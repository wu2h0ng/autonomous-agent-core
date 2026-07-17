from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from research_tools.nonoracle_discovery.freeze_candidate import (
    FreezeCandidateError,
    build_freeze_candidate,
    verify_freeze_candidate,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_is_exact_and_grants_no_run_authority() -> None:
    manifest = build_freeze_candidate(REPO_ROOT)

    assert manifest.route_id == "R-NONORACLE-INTERVENTION-SHIFT-1"
    assert manifest.status == "FREEZE_CANDIDATE_ONLY"
    assert manifest.run_authorized is False
    assert manifest.freeze_authorized is False
    assert manifest.real_result_artifacts == ()
    assert manifest.claim_ceiling == "SYNTHETIC_QUALIFICATION_ONLY"
    assert verify_freeze_candidate(manifest, REPO_ROOT) is True


def test_manifest_binds_every_mechanism_baseline_qualification_and_attack_file() -> None:
    manifest = build_freeze_candidate(REPO_ROOT)
    paths = {item.path for item in manifest.file_bindings}

    assert "research_tools/nonoracle_discovery/mechanism.py" in paths
    assert "research_tools/nonoracle_discovery/baselines.py" in paths
    assert "research_tools/nonoracle_discovery/qualification.py" in paths
    assert "tests/research_tools/test_nonoracle_discovery_attacks.py" in paths
    assert "tests/research_tools/test_nonoracle_discovery_freeze_candidate.py" in paths
    assert manifest.baseline_ids == (
        "FINITE_SCREEN_ALL_LEGAL_PAIRS",
        "FIXED_THRESHOLD_POOLED_MEAN_SHIFT",
        "OBSERVATIONAL_ABS_CORRELATION_MATCHED_K",
    )
    assert "VARIABLE_RENAME_EQUIVARIANCE" in manifest.attack_ids
    assert "HIDDEN_GOLD_MUTATION_INVARIANCE" in manifest.attack_ids


def _copy_bound_tree(destination: Path) -> None:
    manifest = build_freeze_candidate(REPO_ROOT)
    for binding in manifest.file_bindings:
        target = destination / binding.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / binding.path, target)


def test_verifier_detects_bound_file_drift(tmp_path: Path) -> None:
    _copy_bound_tree(tmp_path)
    manifest = build_freeze_candidate(tmp_path)
    target = tmp_path / "research_tools/nonoracle_discovery/mechanism.py"
    target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(FreezeCandidateError, match="digest drift"):
        verify_freeze_candidate(manifest, tmp_path)


def test_builder_rejects_symlinked_bound_file(tmp_path: Path) -> None:
    _copy_bound_tree(tmp_path)
    target = tmp_path / "research_tools/nonoracle_discovery/mechanism.py"
    real = tmp_path / "mechanism-real.py"
    target.rename(real)
    target.symlink_to(real)

    with pytest.raises(FreezeCandidateError, match="regular non-symlink"):
        build_freeze_candidate(tmp_path)
