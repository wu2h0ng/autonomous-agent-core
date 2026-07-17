from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from research_tools.nonoracle_discovery.freeze_candidate import (
    FreezeCandidateError,
    _manifest_payload,
    build_freeze_candidate,
    verify_freeze_candidate,
)
from research_tools.nonoracle_discovery.contracts import content_digest


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
    assert "NO_GOLD_INPUT_OR_IO_CHANNEL" in manifest.attack_ids


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


def test_builder_rejects_truth_import_bypass(tmp_path: Path) -> None:
    _copy_bound_tree(tmp_path)
    target = tmp_path / "research_tools/nonoracle_discovery/mechanism.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\nfrom experiments.sachs_task import GROUND_TRUTH\n",
        encoding="utf-8",
    )

    with pytest.raises(FreezeCandidateError, match="oracle channel"):
        build_freeze_candidate(tmp_path)


def test_builder_rejects_file_io_bypass(tmp_path: Path) -> None:
    _copy_bound_tree(tmp_path)
    target = tmp_path / "research_tools/nonoracle_discovery/mechanism.py"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\nLEAKED = open('/tmp/hidden-gold.json').read()\n",
        encoding="utf-8",
    )

    with pytest.raises(FreezeCandidateError, match="oracle channel"):
        build_freeze_candidate(tmp_path)


def _resign(manifest, *, calibration_digest=None, file_bindings=None):
    calibration = calibration_digest or manifest.calibration_digest
    bindings = file_bindings or manifest.file_bindings
    payload = _manifest_payload(calibration, bindings)
    return replace(
        manifest,
        calibration_digest=calibration,
        file_bindings=bindings,
        manifest_digest=content_digest(
            "nonoracle-discovery-freeze-candidate/v1", payload
        ),
    )


def test_verifier_rejects_self_signed_calibration_substitution() -> None:
    manifest = build_freeze_candidate(REPO_ROOT)
    resigned = _resign(manifest, calibration_digest="9" * 64)

    with pytest.raises(FreezeCandidateError, match="calibration"):
        verify_freeze_candidate(resigned, REPO_ROOT)


def test_verifier_rejects_self_signed_binding_deletion() -> None:
    manifest = build_freeze_candidate(REPO_ROOT)
    resigned = _resign(manifest, file_bindings=manifest.file_bindings[:-1])

    with pytest.raises(FreezeCandidateError, match="exact bound paths"):
        verify_freeze_candidate(resigned, REPO_ROOT)
