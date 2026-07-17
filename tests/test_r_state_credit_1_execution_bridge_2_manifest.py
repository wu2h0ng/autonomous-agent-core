from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = (
    "docs/pre_spec/R-STATE-CREDIT-1.EXECUTION-BRIDGE-2-MANIFEST-2026-07-17.json"
)
MANIFEST_PATH = ROOT / MANIFEST_RELATIVE
PREDECESSOR_PATH = (
    "docs/pre_spec/R-STATE-CREDIT-1.EXECUTION-BRIDGE-1-MANIFEST-2026-07-17.json"
)
PREDECESSOR_REFERENCE_HEAD = "2b4fbf92d73fb77a1648d4c0d026ea6075948fab"
PREDECESSOR_SHA256 = "a0a03808fb0fce93a4f1f15490308e4445100ce3012a4f339bb7091c2121fa8d"
TEST_RELATIVE = "tests/test_r_state_credit_1_execution_bridge_2_manifest.py"
CODE_HEAD = "ea0dcb47ab0bb6f04342506db9cf7e80e3b2fadd"


def _expected_artifact_paths() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", CODE_HEAD],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    selected: set[str] = set()
    for relative_path in completed.stdout.splitlines():
        if relative_path in {
            "docs/pre_spec/R-STATE-CREDIT-1.SUCCESSOR-F-CANDIDATE-2026-07-17.json",
            "docs/research/R-STATE-CREDIT-1-successor-f-amendment-2026-07-17.md",
        }:
            selected.add(relative_path)
        elif relative_path.startswith("experiments/r_state_credit_1/"):
            selected.add(relative_path)
        elif relative_path.startswith(
            "tests/test_r_state_credit_1_"
        ) and relative_path.endswith(".py"):
            selected.add(relative_path)
        elif relative_path.startswith("tests/support/"):
            selected.add(relative_path)
    return selected - {MANIFEST_RELATIVE, TEST_RELATIVE}


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


def test_bridge_2_manifest_has_closed_future_candidate_schema_and_coverage() -> None:
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
    assert manifest["schema_version"] == "r-state-credit-1-execution-bridge-manifest-v2"
    assert manifest["manifest_id"] == "R-STATE-CREDIT-1-EXECUTION-BRIDGE-2-20260717"
    assert (
        manifest["status"]
        == "FUTURE_FREEZE_CANDIDATE / NOT_REVIEWED / NOT_FROZEN / NOT_RUN"
    )
    assert manifest["active_freeze_input"] is False
    assert manifest["code_head"] == CODE_HEAD

    artifacts = manifest["artifact_sha256"]
    assert isinstance(artifacts, dict)
    assert set(artifacts) == _expected_artifact_paths()
    assert MANIFEST_RELATIVE not in artifacts
    assert TEST_RELATIVE not in artifacts
    assert PREDECESSOR_PATH not in artifacts
    assert "experiments/r_state_credit_1/execution_bridge.py" in artifacts
    assert "experiments/r_state_credit_1/execution_bridge_cli.py" in artifacts
    assert "experiments/r_state_credit_1/__init__.py" in artifacts
    for relative_path in artifacts:
        path = PurePosixPath(relative_path)
        assert not path.is_absolute()
        assert ".." not in path.parts


def test_bridge_2_manifest_hashes_exact_code_head_and_current_bytes() -> None:
    artifacts = _manifest()["artifact_sha256"]
    assert isinstance(artifacts, dict)
    for relative_path, expected_digest in artifacts.items():
        assert isinstance(relative_path, str)
        assert isinstance(expected_digest, str)
        code_head_bytes = _git_bytes(CODE_HEAD, relative_path)
        current_bytes = (ROOT / relative_path).read_bytes()
        assert current_bytes == code_head_bytes, relative_path
        assert _sha256(code_head_bytes) == expected_digest, relative_path


def test_bridge_1_predecessor_bytes_and_status_are_unchanged() -> None:
    predecessor = _manifest()["predecessor_manifest"]
    assert isinstance(predecessor, dict)
    assert set(predecessor) == {
        "path",
        "reference_head",
        "sha256",
        "status",
        "active_freeze_input",
    }
    assert predecessor == {
        "path": PREDECESSOR_PATH,
        "reference_head": PREDECESSOR_REFERENCE_HEAD,
        "sha256": PREDECESSOR_SHA256,
        "status": "FUTURE_FREEZE_CANDIDATE / NOT_REVIEWED / NOT_FROZEN / NOT_RUN",
        "active_freeze_input": False,
    }

    current_bytes = (ROOT / PREDECESSOR_PATH).read_bytes()
    assert current_bytes == _git_bytes(PREDECESSOR_REFERENCE_HEAD, PREDECESSOR_PATH)
    assert _sha256(current_bytes) == PREDECESSOR_SHA256
    predecessor_document = json.loads(current_bytes)
    assert predecessor_document["status"] == predecessor["status"]
    assert predecessor_document["active_freeze_input"] is False


def test_bridge_2_code_head_is_current_or_an_ancestor_of_current_head() -> None:
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", CODE_HEAD, "HEAD"],
        cwd=ROOT,
        check=True,
    )


def test_bridge_2_overlay_commit_changes_exactly_manifest_and_test() -> None:
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current_head == CODE_HEAD:
        assert MANIFEST_PATH.is_file()
        assert (ROOT / TEST_RELATIVE).is_file()
        return
    changed = subprocess.run(
        ["git", "diff", "--name-only", CODE_HEAD, current_head],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert set(changed) == {MANIFEST_RELATIVE, TEST_RELATIVE}


def test_bridge_2_candidate_has_no_active_or_run_authority() -> None:
    manifest = _manifest()
    assert manifest["active_freeze_input"] is False
    assert "NOT_FROZEN" in str(manifest["status"])
    assert "NOT_RUN" in str(manifest["status"])
