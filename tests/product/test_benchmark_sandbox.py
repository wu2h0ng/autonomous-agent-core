from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from agent_os_contracts import BenchmarkTaskValidationError
from agent_os_core import (
    BENCHMARK_CONTAINER_UNAVAILABLE,
    BenchmarkContainerError,
    BenchmarkContainerSandbox,
    CapabilityDenied,
    ContainerResult,
    WorkspaceSandbox,
)

F2P = ("tests/test_x.py::test_a", "tests/test_x.py::test_b")
P2P = ("tests/test_y.py::test_c",)
IMAGE_TAG = "selfdev2-dryrun-django:py311"


class FakeContainerRunner:
    """Scripted container runner: records run_verifier, replays exits."""

    def __init__(self, exits: list[int]) -> None:
        self._exits = list(exits)
        self.calls: list[dict[str, object]] = []
        self.error: BenchmarkContainerError | None = None

    def run_verifier(
        self,
        image_tag: str,
        *,
        work_dir: Path,
        argv: list[str],
        timeout_seconds: int,
        env_allowlist: tuple[str, ...] = (),
    ) -> ContainerResult:
        self.calls.append(
            {
                "image_tag": image_tag,
                "work_dir": work_dir,
                "argv": list(argv),
                "timeout_seconds": timeout_seconds,
                "env_allowlist": env_allowlist,
            }
        )
        if self.error is not None:
            raise self.error
        exit_code = self._exits.pop(0) if self._exits else 0
        return ContainerResult(
            exit_code=exit_code,
            stdout=f"stdout:{argv[-1]}",
            stderr=f"stderr:{argv[-1]}",
            duration_seconds=0.1,
        )


def _sandbox(
    repo: Path,
    runner: FakeContainerRunner,
    *,
    p2p: tuple[str, ...] = P2P,
    timeout: int = 900,
) -> BenchmarkContainerSandbox:
    return BenchmarkContainerSandbox(
        repo, IMAGE_TAG, F2P, p2p, timeout, runner
    )


def _report(
    sandbox: WorkspaceSandbox, output: dict[str, object]
) -> dict[str, object]:
    artifact_ids = output["artifact_ids"]
    assert isinstance(artifact_ids, tuple) and len(artifact_ids) == 1
    raw = sandbox.read_artifact_bytes(str(artifact_ids[0]))
    assert raw is not None
    report = json.loads(raw.decode("utf-8"))
    assert isinstance(report, dict)
    return report


def test_f2p_and_p2p_green_produce_zero_exit_report(tmp_path: Path) -> None:
    runner = FakeContainerRunner([0, 0])
    sandbox = _sandbox(tmp_path, runner)
    output = sandbox._dispatch(
        "workspace.run_tests", {"command": "python -m pytest"}, "action-key-1"
    )
    assert output["exit_code"] == 0
    assert runner.calls == [
        {
            "image_tag": IMAGE_TAG,
            "work_dir": sandbox.root,
            "argv": ["python", "-m", "pytest", *F2P],
            "timeout_seconds": 900,
            "env_allowlist": (),
        },
        {
            "image_tag": IMAGE_TAG,
            "work_dir": sandbox.root,
            "argv": ["python", "-m", "pytest", *P2P],
            "timeout_seconds": 900,
            "env_allowlist": (),
        },
    ]
    report = _report(sandbox, output)
    assert report["schema_version"] == "test-report.v1"
    assert report["exit_code"] == 0
    assert report["command"] == (
        f"python -m pytest {F2P[0]} {F2P[1]}"
        f" && python -m pytest {P2P[0]}"
    )
    assert report["action_key_sha256"] == hashlib.sha256(
        b"action-key-1"
    ).hexdigest()
    stdout = str(report["stdout"])
    assert stdout.index("=== phase f2p:") < stdout.index("=== phase p2p:")
    assert "stderr" in report


def test_f2p_failure_skips_p2p_and_reports_nonzero(tmp_path: Path) -> None:
    runner = FakeContainerRunner([1])
    sandbox = _sandbox(tmp_path, runner)
    output = sandbox._dispatch(
        "workspace.run_tests", {"command": "python -m pytest"}, "action-key-2"
    )
    assert output["exit_code"] == 1
    assert len(runner.calls) == 1
    report = _report(sandbox, output)
    assert report["exit_code"] == 1
    assert "=== phase f2p:" in str(report["stdout"])
    assert "=== phase p2p:" not in str(report["stdout"])
    assert report["command"] == f"python -m pytest {F2P[0]} {F2P[1]}"


def test_p2p_failure_reported_when_f2p_green(tmp_path: Path) -> None:
    runner = FakeContainerRunner([0, 2])
    sandbox = _sandbox(tmp_path, runner)
    output = sandbox._dispatch(
        "workspace.run_tests", {"command": "python -m pytest"}, "action-key-3"
    )
    assert output["exit_code"] == 2
    assert len(runner.calls) == 2
    report = _report(sandbox, output)
    assert report["exit_code"] == 2


def test_without_p2p_ids_single_phase_runs(tmp_path: Path) -> None:
    runner = FakeContainerRunner([0])
    sandbox = _sandbox(tmp_path, runner, p2p=())
    output = sandbox._dispatch(
        "workspace.run_tests", {"command": "python -m pytest"}, "action-key-4"
    )
    assert output["exit_code"] == 0
    assert len(runner.calls) == 1
    assert "=== phase p2p:" not in str(_report(sandbox, output)["stdout"])


def test_report_matches_base_workspace_sandbox_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "PATH",
        f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
    )
    (tmp_path / "test_smoke.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    base = WorkspaceSandbox(tmp_path)
    base_output = base._dispatch(
        "workspace.run_tests", {"command": "python -m pytest"}, "action-key-b"
    )
    assert base_output["exit_code"] == 0
    base_report = _report(base, base_output)
    sandbox = _sandbox(tmp_path, FakeContainerRunner([0]), p2p=())
    output = sandbox._dispatch(
        "workspace.run_tests", {"command": "python -m pytest"}, "action-key-c"
    )
    report = _report(sandbox, output)
    assert set(report) == set(base_report)
    assert report["schema_version"] == base_report["schema_version"]


def test_read_and_apply_patch_behaviors_are_inherited(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path, FakeContainerRunner([]))
    with pytest.raises(FileNotFoundError):
        sandbox._dispatch("workspace.read", {"path": "missing.txt"}, "k1")
    applied = sandbox._dispatch(
        "workspace.apply_patch",
        {"path": "src/x.py", "content": "x = 1\n"},
        "k2",
    )
    assert applied["compensation_ref"]
    assert (tmp_path / "src" / "x.py").read_text(encoding="utf-8") == "x = 1\n"
    read = sandbox._dispatch("workspace.read", {"path": "src/x.py"}, "k3")
    assert read["content"] == "x = 1\n"


def test_disallowed_test_command_fails_closed(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path, FakeContainerRunner([]))
    with pytest.raises(CapabilityDenied):
        sandbox._dispatch(
            "workspace.run_tests", {"command": "make test"}, "k4"
        )


def test_construction_validates_ids_and_timeout(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkTaskValidationError):
        BenchmarkContainerSandbox(
            tmp_path, IMAGE_TAG, (), (), 60, FakeContainerRunner([])
        )
    with pytest.raises(BenchmarkTaskValidationError):
        BenchmarkContainerSandbox(
            tmp_path,
            IMAGE_TAG,
            ("not a node id",),
            (),
            60,
            FakeContainerRunner([]),
        )
    with pytest.raises(BenchmarkTaskValidationError):
        BenchmarkContainerSandbox(
            tmp_path, IMAGE_TAG, F2P, (), 0, FakeContainerRunner([])
        )


def test_container_infra_error_propagates(tmp_path: Path) -> None:
    runner = FakeContainerRunner([])
    runner.error = BenchmarkContainerError(
        BENCHMARK_CONTAINER_UNAVAILABLE, "docker daemon down"
    )
    sandbox = _sandbox(tmp_path, runner)
    with pytest.raises(BenchmarkContainerError) as excinfo:
        sandbox._dispatch(
            "workspace.run_tests", {"command": "python -m pytest"}, "k5"
        )
    assert excinfo.value.code == BENCHMARK_CONTAINER_UNAVAILABLE
