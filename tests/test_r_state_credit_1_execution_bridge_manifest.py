from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / (
    "docs/pre_spec/R-STATE-CREDIT-1.EXECUTION-BRIDGE-1-MANIFEST-2026-07-17.json"
)
PREDECESSOR_PATH = "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-MANIFEST-2026-07-17.json"
PREDECESSOR_REFERENCE_HEAD = "96eb79e1292d6b8f36ad990d3f97c554a9c33f3b"
CODE_HEAD = "38f850e73da5a4fd41f0418e15d156939731e046"
MANIFEST_COMMIT = "2b4fbf92d73fb77a1648d4c0d026ea6075948fab"

EXPECTED_MECHANISM_PATHS = {
    "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-CANDIDATE-2026-07-17.json",
    "docs/research/R-STATE-CREDIT-1-successor-f-amendment-2026-07-17.md",
    "experiments/r_state_credit_1/__init__.py",
    "experiments/r_state_credit_1/action_grammar.py",
    "experiments/r_state_credit_1/actor_interface.py",
    "experiments/r_state_credit_1/ark_responses_actor.py",
    "experiments/r_state_credit_1/arm_blinding.py",
    "experiments/r_state_credit_1/arms.py",
    "experiments/r_state_credit_1/authority_artifacts.py",
    "experiments/r_state_credit_1/authority_verifier.py",
    "experiments/r_state_credit_1/bindings/ark-agent-plan-actor-candidate.json",
    "experiments/r_state_credit_1/bindings/c7-signal-candidate.json",
    "experiments/r_state_credit_1/bindings/run-authority-candidate.json",
    "experiments/r_state_credit_1/bindings/system-prompt.txt",
    "experiments/r_state_credit_1/bindings/tool-schema.json",
    "experiments/r_state_credit_1/contracts.py",
    "experiments/r_state_credit_1/corpus/public-case-manifest.json",
    "experiments/r_state_credit_1/corpus/sealed-referee-manifest.json",
    "experiments/r_state_credit_1/episode_generator.py",
    "experiments/r_state_credit_1/execution_bridge.py",
    "experiments/r_state_credit_1/external_c7.py",
    "experiments/r_state_credit_1/interactive_env.py",
    "experiments/r_state_credit_1/observation.py",
    "experiments/r_state_credit_1/prereg_candidate.py",
    "experiments/r_state_credit_1/prereg_resolution.py",
    "experiments/r_state_credit_1/qualifier.py",
    "experiments/r_state_credit_1/real_corpus.py",
    "experiments/r_state_credit_1/real_scorer.py",
    "experiments/r_state_credit_1/recast_arms.py",
    "experiments/r_state_credit_1/recast_freeze_contracts.py",
    "experiments/r_state_credit_1/recast_provider_actor.py",
    "experiments/r_state_credit_1/recast_result_runner.py",
    "experiments/r_state_credit_1/recast_scorer.py",
    "experiments/r_state_credit_1/result_runner.py",
    "experiments/r_state_credit_1/run_contracts.py",
    "experiments/r_state_credit_1/scenarios.py",
    "experiments/r_state_credit_1/signature_backend.py",
    "experiments/r_state_credit_1/statistical_integrity.py",
    "experiments/r_state_credit_1/trajectory_driver.py",
}


def _reference_execution_and_attack_tests() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", CODE_HEAD, "tests"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        path
        for path in completed.stdout.splitlines()
        if PurePosixPath(path).name.startswith("test_r_state_credit_1_")
        and path != Path(__file__).relative_to(ROOT).as_posix()
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_bytes(revision: str, relative_path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{relative_path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_uses_closed_candidate_only_schema_and_relative_paths() -> None:
    manifest = _manifest()
    assert set(manifest) == {
        "schema_version",
        "manifest_id",
        "status",
        "active_freeze_input",
        "code_head",
        "predecessor_manifest",
        "artifact_sha256",
    }
    assert manifest["schema_version"] == "r-state-credit-1-execution-bridge-manifest-v1"
    assert manifest["manifest_id"] == "R-STATE-CREDIT-1-EXECUTION-BRIDGE-1-20260717"
    assert (
        manifest["status"]
        == "FUTURE_FREEZE_CANDIDATE / NOT_REVIEWED / NOT_FROZEN / NOT_RUN"
    )
    assert manifest["active_freeze_input"] is False
    assert manifest["code_head"] == CODE_HEAD

    artifacts = manifest["artifact_sha256"]
    assert isinstance(artifacts, dict)
    assert set(artifacts) == EXPECTED_MECHANISM_PATHS | (
        _reference_execution_and_attack_tests()
    )
    assert MANIFEST_PATH.relative_to(ROOT).as_posix() not in artifacts
    for relative_path in artifacts:
        path = PurePosixPath(relative_path)
        assert not path.is_absolute()
        assert ".." not in path.parts


def test_manifest_hashes_exact_historical_code_head_bytes() -> None:
    manifest = _manifest()
    artifacts = manifest["artifact_sha256"]
    assert isinstance(artifacts, dict)
    for relative_path, expected_digest in artifacts.items():
        assert isinstance(relative_path, str)
        assert isinstance(expected_digest, str)
        code_head_bytes = _git_bytes(CODE_HEAD, relative_path)
        assert _sha256(code_head_bytes) == expected_digest, relative_path
    assert MANIFEST_PATH.read_bytes() == _git_bytes(
        MANIFEST_COMMIT, MANIFEST_PATH.relative_to(ROOT).as_posix()
    )


def test_historical_bridge_manifest_is_not_active_on_current_head() -> None:
    manifest = _manifest()
    artifacts = manifest["artifact_sha256"]
    assert isinstance(artifacts, dict)
    drifted = [
        relative_path
        for relative_path, expected_digest in artifacts.items()
        if _sha256((ROOT / relative_path).read_bytes()) != expected_digest
    ]
    assert drifted
    assert manifest["active_freeze_input"] is False
    assert "NOT_FROZEN" in str(manifest["status"])


def test_predecessor_manifest_is_byte_unchanged_but_drifted_not_freezable() -> None:
    manifest = _manifest()
    predecessor = manifest["predecessor_manifest"]
    assert isinstance(predecessor, dict)
    assert set(predecessor) == {
        "path",
        "reference_head",
        "sha256",
        "status",
        "drifted_artifacts",
    }
    assert predecessor["path"] == PREDECESSOR_PATH
    assert predecessor["reference_head"] == PREDECESSOR_REFERENCE_HEAD
    assert predecessor["status"] == "DRIFTED / NOT_FREEZABLE"

    current_bytes = (ROOT / PREDECESSOR_PATH).read_bytes()
    assert current_bytes == _git_bytes(PREDECESSOR_REFERENCE_HEAD, PREDECESSOR_PATH)
    assert _sha256(current_bytes) == predecessor["sha256"]

    old_manifest = json.loads(current_bytes)
    old_artifacts = old_manifest["artifact_sha256"]
    actual_drift = sorted(
        relative_path
        for relative_path, expected_digest in old_artifacts.items()
        if _sha256((ROOT / relative_path).read_bytes()) != expected_digest
    )
    assert actual_drift == predecessor["drifted_artifacts"]
    assert actual_drift


def test_code_head_is_current_or_an_ancestor_of_current_head() -> None:
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", CODE_HEAD, "HEAD"],
        cwd=ROOT,
        check=True,
    )
