from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .contracts import content_digest
from .mechanism import StabilityCalibration


ROUTE_ID = "R-NONORACLE-INTERVENTION-SHIFT-1"
BOUND_PATHS = (
    "research_tools/nonoracle_discovery/__init__.py",
    "research_tools/nonoracle_discovery/contracts.py",
    "research_tools/nonoracle_discovery/mechanism.py",
    "research_tools/nonoracle_discovery/baselines.py",
    "research_tools/nonoracle_discovery/qualification.py",
    "research_tools/nonoracle_discovery/freeze_candidate.py",
    "research_tools/nonoracle_discovery/sealed_runner.py",
    "tests/research_tools/test_nonoracle_discovery_contracts.py",
    "tests/research_tools/test_nonoracle_intervention_stability.py",
    "tests/research_tools/test_nonoracle_discovery_qualification.py",
    "tests/research_tools/test_nonoracle_discovery_attacks.py",
    "tests/research_tools/test_nonoracle_discovery_freeze_candidate.py",
)
BASELINE_IDS = (
    "FINITE_SCREEN_ALL_LEGAL_PAIRS",
    "FIXED_THRESHOLD_POOLED_MEAN_SHIFT",
    "OBSERVATIONAL_ABS_CORRELATION_MATCHED_K",
)
ATTACK_IDS = (
    "CONTRADICTORY_BINDING_FAIL_CLOSED",
    "DUPLICATE_TARGET_BINDING_FAIL_CLOSED",
    "SEALED_EXACT_SOURCE_ISOLATED_SUBPROCESS",
    "OPAQUE_PREDICTOR_CODEC_STATE_FORBIDDEN",
    "PUBLIC_EVIDENCE_SENSITIVITY",
    "REAL_TRUTH_IMPORT_SCAN",
    "VARIABLE_RENAME_EQUIVARIANCE",
)


class FreezeCandidateError(ValueError):
    """Freeze-candidate bytes are missing, unsafe, or drifted."""


@dataclass(frozen=True, slots=True)
class FileBinding:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class FreezeCandidateManifest:
    schema_version: str
    route_id: str
    status: str
    claim_ceiling: str
    freeze_authorized: bool
    run_authorized: bool
    real_result_artifacts: tuple[str, ...]
    calibration_digest: str
    baseline_ids: tuple[str, ...]
    attack_ids: tuple[str, ...]
    file_bindings: tuple[FileBinding, ...]
    manifest_digest: str


def _binding(repo_root: Path, relative_path: str) -> FileBinding:
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != relative_path
    ):
        raise FreezeCandidateError(f"unsafe bound path: {relative_path}")
    path = repo_root / relative_path
    cursor = repo_root
    if repo_root.is_symlink():
        raise FreezeCandidateError("resolved repository root must not be a symlink")
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise FreezeCandidateError(f"bound path contains symlink: {relative_path}")
    if not path.is_file():
        raise FreezeCandidateError(
            f"bound file must be a regular non-symlink: {relative_path}"
        )
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(repo_root):
        raise FreezeCandidateError(
            f"bound path escapes repository root: {relative_path}"
        )
    return FileBinding(relative_path, hashlib.sha256(resolved.read_bytes()).hexdigest())


_EXPECTED_EXECUTABLE_PACKAGE_PATHS = frozenset(
    path
    for path in BOUND_PATHS
    if path.startswith("research_tools/nonoracle_discovery/")
)


def _validate_executable_file_set(repo_root: Path) -> None:
    package = repo_root / "research_tools/nonoracle_discovery"
    discovered = frozenset(
        path.relative_to(repo_root).as_posix() for path in package.rglob("*.py")
    )
    if discovered != _EXPECTED_EXECUTABLE_PACKAGE_PATHS:
        raise FreezeCandidateError(
            "executable file set differs from frozen package manifest"
        )


def _manifest_payload(
    calibration_digest: str,
    bindings: tuple[FileBinding, ...],
) -> dict[str, object]:
    return {
        "schema_version": "nonoracle-discovery-freeze-candidate/v1",
        "route_id": ROUTE_ID,
        "status": "FREEZE_CANDIDATE_ONLY",
        "claim_ceiling": "SYNTHETIC_QUALIFICATION_ONLY",
        "freeze_authorized": False,
        "run_authorized": False,
        "real_result_artifacts": [],
        "calibration_digest": calibration_digest,
        "baseline_ids": list(BASELINE_IDS),
        "attack_ids": list(ATTACK_IDS),
        "file_bindings": [
            {"path": item.path, "sha256": item.sha256} for item in bindings
        ],
    }


def build_freeze_candidate(repo_root: Path) -> FreezeCandidateManifest:
    root = repo_root.resolve()
    if len(BOUND_PATHS) != len(set(BOUND_PATHS)):
        raise FreezeCandidateError("bound file paths must be unique")
    _validate_executable_file_set(root)
    bindings = tuple(_binding(root, relative) for relative in BOUND_PATHS)
    calibration = StabilityCalibration(
        exact_null_quantile_micros=950_000,
        max_exact_combinations=20_000,
        minimum_effect_micros=500_000,
    )
    payload = _manifest_payload(calibration.digest, bindings)
    return FreezeCandidateManifest(
        schema_version=str(payload["schema_version"]),
        route_id=ROUTE_ID,
        status="FREEZE_CANDIDATE_ONLY",
        claim_ceiling="SYNTHETIC_QUALIFICATION_ONLY",
        freeze_authorized=False,
        run_authorized=False,
        real_result_artifacts=(),
        calibration_digest=calibration.digest,
        baseline_ids=BASELINE_IDS,
        attack_ids=ATTACK_IDS,
        file_bindings=bindings,
        manifest_digest=content_digest(
            "nonoracle-discovery-freeze-candidate/v1", payload
        ),
    )


def verify_freeze_candidate(
    manifest: FreezeCandidateManifest,
    repo_root: Path,
) -> bool:
    expected_calibration = StabilityCalibration(
        exact_null_quantile_micros=950_000,
        max_exact_combinations=20_000,
        minimum_effect_micros=500_000,
    )
    if (
        manifest.schema_version != "nonoracle-discovery-freeze-candidate/v1"
        or manifest.route_id != ROUTE_ID
        or manifest.status != "FREEZE_CANDIDATE_ONLY"
        or manifest.claim_ceiling != "SYNTHETIC_QUALIFICATION_ONLY"
        or manifest.freeze_authorized
        or manifest.run_authorized
        or manifest.real_result_artifacts
        or manifest.baseline_ids != BASELINE_IDS
        or manifest.attack_ids != ATTACK_IDS
    ):
        raise FreezeCandidateError("freeze-candidate authority boundary drift")
    if manifest.calibration_digest != expected_calibration.digest:
        raise FreezeCandidateError("freeze-candidate calibration drift")
    if tuple(item.path for item in manifest.file_bindings) != BOUND_PATHS:
        raise FreezeCandidateError("freeze-candidate exact bound paths drift")
    if len(manifest.file_bindings) != len(
        set(item.path for item in manifest.file_bindings)
    ):
        raise FreezeCandidateError("freeze-candidate duplicate bound paths")
    _validate_executable_file_set(repo_root.resolve())
    current = tuple(
        _binding(repo_root.resolve(), item.path) for item in manifest.file_bindings
    )
    if current != manifest.file_bindings:
        raise FreezeCandidateError("freeze-candidate file digest drift")
    payload = _manifest_payload(manifest.calibration_digest, manifest.file_bindings)
    expected = content_digest("nonoracle-discovery-freeze-candidate/v1", payload)
    if expected != manifest.manifest_digest:
        raise FreezeCandidateError("freeze-candidate manifest digest drift")
    return True
