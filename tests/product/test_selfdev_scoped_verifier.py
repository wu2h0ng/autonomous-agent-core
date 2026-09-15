from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
from typing import cast

import pytest

import domain_packs.developer_agent.workspace_capability as capability_module
from agent_os_contracts import (
    ExpectedOutcome,
    OutcomeStatus,
    SelfDevelopmentWorkSpec,
    content_digest,
)
from agent_os_core import (
    CapabilityDenied,
    DeterministicOutcomeEvaluator,
    ValidatedTestReport,
)
from agent_os_core.self_development_organ import (
    SelfDevelopmentAgentLoopState,
    SelfDevelopmentOrgan,
    SelfDevelopmentOrganBlocked,
)
from domain_packs.developer_agent import (
    DeveloperRepositoryPatchProfile,
    WorkspaceSandbox,
)
from tests.product.test_responsibility_controller import _linked_worktree


def _base_binding(workspace: Path, head: str, path: str) -> dict[str, str]:
    blob = subprocess.run(
        ["git", "-C", str(workspace), "show", f"{head}:{path}"],
        check=True,
        capture_output=True,
    ).stdout
    return {
        "schema_version": "1.0",
        "path": path,
        "base_blob_sha256": hashlib.sha256(blob).hexdigest(),
    }


def _binding_digest(bindings: list[dict[str, str]]) -> str:
    return content_digest({"verifier_bindings": bindings})


def test_scoped_verifier_uses_only_bound_paths_and_records_exact_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _, head = _linked_worktree(tmp_path)
    verifier_path = "tests/product/test_selfdev_fixture.py"
    binding = _base_binding(workspace, head, verifier_path)
    artifacts = tmp_path / "artifacts"
    sandbox = WorkspaceSandbox(workspace, artifacts=artifacts)
    real_run = subprocess.run
    observed_argv: list[str] = []

    def capture_scoped_pytest(argv, **kwargs):
        if argv and str(argv[0]).endswith("sandbox-exec"):
            observed_argv.extend(str(value) for value in argv)
            return subprocess.CompletedProcess(argv, 0, "1 passed\n", "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(capability_module.shutil, "which", lambda _: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(capability_module.subprocess, "run", capture_scoped_pytest)

    result = sandbox._dispatch(
        "workspace.run_tests",
        {
            "command": "pytest",
            "selfdev_verification_snapshot": {
                "repository_head": head,
                "verifier_bindings": [binding],
                "verifier_binding_digest": _binding_digest([binding]),
            },
        },
        "action:selfdev:scoped-verifier",
    )

    assert observed_argv[-7:] == [
        "-S",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-q",
        verifier_path,
    ]
    report = json.loads((artifacts / str(result["digest"])).read_text())
    assert report["verifier_bindings"] == [binding]
    assert report["verifier_binding_digest"] == _binding_digest([binding])
    assert report["argv"][-7:] == observed_argv[-7:]
    assert report["command"] == "pytest"
    assert report["execution_isolation"] == "sandboxed"
    assert report["sandbox_profile_sha256"]


def test_selfdev_organ_fails_unbound_before_agent_loop_and_forwards_sealed_binding(
    tmp_path: Path,
) -> None:
    workspace, branch, head = _linked_worktree(tmp_path)
    verifier_path = "tests/product/test_selfdev_fixture.py"
    binding = _base_binding(workspace, head, verifier_path)
    contexts: list[dict[str, object]] = []
    agent_loop_calls = 0

    def execute_agent_loop(*_args):
        nonlocal agent_loop_calls
        agent_loop_calls += 1
        return SelfDevelopmentAgentLoopState.COMPLETED

    organ = SelfDevelopmentOrgan(
        workspace=workspace,
        execute_task=lambda _task_id, context, _assert_current, _effect: contexts.append(context),
        execute_agent_loop=execute_agent_loop,
    )
    base = {
        "repository_head": head,
        "isolated_branch": branch,
        "target_path": "packages/os_core/src/agent_os_core/selfdev_fixture.py",
        "edit_mode": "agent_loop_precise",
        "verifier_command": "pytest",
    }
    with pytest.raises(SelfDevelopmentOrganBlocked, match="UNBOUND"):
        organ(
            "task:unbound",
            SelfDevelopmentWorkSpec.model_validate(base),
            lambda _phase: None,
            object(),
        )
    assert agent_loop_calls == 0

    organ(
        "task:bound",
        SelfDevelopmentWorkSpec.model_validate(
            {**base, "verifier_bindings": [binding]}
        ),
        lambda _phase: None,
        object(),
    )
    assert agent_loop_calls == 1
    envelope = cast(
        dict[str, object], contexts[0]["selfdev_execution_envelope"]
    )
    assert envelope["verifier_bindings"] == [binding]


def test_run_coordinator_snapshot_contains_only_head_and_sealed_verifier_bindings() -> None:
    binding = {
        "schema_version": "1.0",
        "path": "tests/product/test_provider_robustness.py",
        "base_blob_sha256": "a" * 64,
    }

    arguments = DeveloperRepositoryPatchProfile().tool_arguments(
        "workspace.run_tests",
        {
            "test_command": "pytest",
            "selfdev_execution_envelope": {
                "repository_head": "b" * 40,
                "allowed_write_path": "packages/os_core/src/agent_os_core/provider.py",
                "allowed_write_paths": [
                    "packages/os_core/src/agent_os_core/provider.py"
                ],
                "verifier_bindings": [binding],
                "verifier_binding_digest": _binding_digest([binding]),
            },
        },
    )

    assert arguments == {
        "command": "pytest",
        "selfdev_verification_snapshot": {
            "repository_head": "b" * 40,
            "verifier_bindings": [binding],
            "verifier_binding_digest": _binding_digest([binding]),
        },
    }


def test_scoped_verifier_rejects_snapshot_reorder_extra_digest_and_worktree_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _, _ = _linked_worktree(tmp_path)
    second_path = "tests/product/test_second_oracle.py"
    (workspace / second_path).write_text("def test_second():\n    assert True\n")
    subprocess.run(["git", "-C", str(workspace), "add", second_path], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m", "second oracle"],
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    paths = ("tests/product/test_selfdev_fixture.py", second_path)
    bindings = [_base_binding(workspace, head, path) for path in paths]
    snapshot = {
        "repository_head": head,
        "verifier_bindings": bindings,
        "verifier_binding_digest": _binding_digest(bindings),
    }
    sandbox = WorkspaceSandbox(workspace, artifacts=tmp_path / "artifacts")
    real_run = subprocess.run

    def allow_only_if_tamper_was_missed(argv, **kwargs):
        if argv and str(argv[0]).endswith("sandbox-exec"):
            return subprocess.CompletedProcess(argv, 0, "unexpected run\n", "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(capability_module.shutil, "which", lambda _: "/usr/bin/sandbox-exec")
    monkeypatch.setattr(
        capability_module.subprocess,
        "run",
        allow_only_if_tamper_was_missed,
    )
    tampered_snapshots = (
        {**snapshot, "verifier_bindings": list(reversed(bindings))},
        {**snapshot, "unexpected": "field"},
        {
            **snapshot,
            "verifier_bindings": [
                {**bindings[0], "base_blob_sha256": "0" * 64},
                bindings[1],
            ],
        },
    )
    for tampered in tampered_snapshots:
        with pytest.raises(CapabilityDenied):
            sandbox._dispatch(
                "workspace.run_tests",
                {"command": "pytest", "selfdev_verification_snapshot": tampered},
                "action:selfdev:tamper",
            )

    oracle = workspace / paths[0]
    oracle.write_text("def test_tampered():\n    assert False\n")
    with pytest.raises(CapabilityDenied, match="drift"):
        sandbox._dispatch(
            "workspace.run_tests",
            {"command": "pytest", "selfdev_verification_snapshot": snapshot},
            "action:selfdev:worktree-drift",
        )


def test_scoped_pass_ignores_unrelated_failure_and_test_write_attempt_fails_closed(
    tmp_path: Path,
) -> None:
    workspace, _, _ = _linked_worktree(tmp_path)
    passing_path = "tests/product/test_scoped_pass.py"
    unrelated_path = "tests/product/test_unrelated_failure.py"
    write_path = "tests/product/test_oracle_write.py"
    (workspace / passing_path).write_text("def test_scoped_pass():\n    assert True\n")
    (workspace / unrelated_path).write_text(
        "def test_unrelated_failure():\n    assert False\n"
    )
    (workspace / write_path).write_text(
        "from pathlib import Path\n\n"
        "def test_oracle_write():\n"
        "    Path(__file__).write_text('tampered')\n"
    )
    subprocess.run(
        ["git", "-C", str(workspace), "add", passing_path, unrelated_path, write_path],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m", "scoped oracle cases"],
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    artifacts = tmp_path / "artifacts"
    sandbox = WorkspaceSandbox(workspace, artifacts=artifacts)

    def run_path(path: str) -> tuple[dict[str, object], dict[str, object]]:
        binding = _base_binding(workspace, head, path)
        result = sandbox._dispatch(
            "workspace.run_tests",
            {
                "command": "pytest",
                "selfdev_verification_snapshot": {
                    "repository_head": head,
                    "verifier_bindings": [binding],
                    "verifier_binding_digest": _binding_digest([binding]),
                },
            },
            f"action:selfdev:{path}",
        )
        report = json.loads((artifacts / str(result["digest"])).read_text())
        return result, report

    passing, passing_report = run_path(passing_path)
    assert passing["exit_code"] == 0
    assert unrelated_path not in str(passing_report["stdout"])
    passing_bindings = cast(
        list[dict[str, str]], passing_report["verifier_bindings"]
    )
    assert passing_bindings[0]["path"] == passing_path

    preimage = (workspace / write_path).read_bytes()
    denied, denied_report = run_path(write_path)
    assert denied["exit_code"] != 0
    denied_bindings = cast(
        list[dict[str, str]], denied_report["verifier_bindings"]
    )
    assert denied_bindings[0]["path"] == write_path
    assert (workspace / write_path).read_bytes() == preimage

    frozen_at = datetime(2026, 8, 8, tzinfo=timezone.utc)
    expected = ExpectedOutcome(
        expected_outcome_id="expected:scoped-verifier",
        task_id="task:scoped-verifier",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=frozen_at,
    )

    def outcome_for(result: dict[str, object]):
        raw_artifact_ids = result["artifact_ids"]
        assert isinstance(raw_artifact_ids, (list, tuple))
        artifact_ids = tuple(str(value) for value in raw_artifact_ids)
        exit_code = result["exit_code"]
        assert isinstance(exit_code, int)
        report = ValidatedTestReport(
            artifact_ids=artifact_ids,
            exit_code=exit_code,
            node_id="tests",
            action_id="action:scoped",
            receipt_id="receipt:scoped",
            completed_sequence=10,
            completed_at=frozen_at + timedelta(seconds=10),
        )
        return DeterministicOutcomeEvaluator(
            lambda _task_id, _run_id: report
        ).evaluate(
            expected,
            task_id=expected.task_id,
            run_id="run:scoped-verifier",
            tenant_id=expected.tenant_id,
            workspace_id=expected.workspace_id,
            evidence_refs=artifact_ids,
            test_exit_code=report.exit_code,
            now=frozen_at + timedelta(seconds=20),
        )

    assert outcome_for(passing).status is OutcomeStatus.VERIFIED
    assert outcome_for(denied).status is OutcomeStatus.NOT_MET
