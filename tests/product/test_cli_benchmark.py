from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_os_contracts import (
    BenchmarkTaskValidationError,
    ProviderErrorCode,
    ProviderFailure,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    RunStatus,
    SelfDevelopmentBenchmarkTask,
)
from agent_os_core import (
    BASELINE_DIFF_INVALID,
    RUN_DENIED,
    BenchmarkContainerSandbox,
    ContainerResult,
    SelfDevelopmentValidationError,
    build_benchmark_task,
    prepare_benchmark_task_package,
)
from apps.cli import __main__ as cli

INSTANCE_ID = "django__django-13670"
ISSUE_TEXT = "dateformat crashes on invalid input\n"
TEST_PATCH = "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
GOOD_DIFF = """\
--- a/django/utils/dateformat.py
+++ b/django/utils/dateformat.py
@@ -1,1 +1,1 @@
-old
+new
"""


def _selection_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "instance_id": INSTANCE_ID,
        "repo": "django/django",
        "base_commit": "0" * 40,
        "issue_text_hash": "b" * 64,
        "gold_file_path": "django/utils/dateformat.py",
        "gold_file_bytes": 10850,
        "gold_file_lines": 300,
        "f2p_node_ids": [
            "tests/utils_tests/test_dateformat.py::TestF::test_format"
        ],
        "p2p_node_ids": [
            "tests/utils_tests/test_dateformat.py::TestF::test_other"
        ],
        "p2p_vacuous": False,
        "image_tag": "selfdev2-dryrun-django:py311",
        "interpreter": "python:3.11-slim",
        "verifier_timeout_seconds": 900,
        "min_output_tokens": 8192,
        "gold_validation_evidence_digest": "c" * 64,
        "set": "main",
    }
    entry.update(overrides)
    return entry


def _write_selection(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    path = tmp_path / "selection.json"
    path.write_text(
        json.dumps({"schema": "s", "seed": 1, "rule": "r", "tasks": entries}),
        encoding="utf-8",
    )
    return path


def _write_dataset_task(repo_root: Path, instance_id: str) -> None:
    task_dir = (
        repo_root
        / ".agent_runs"
        / "selfdev-2"
        / "dataset"
        / "tasks"
        / instance_id
    )
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "issue.txt").write_text(ISSUE_TEXT, encoding="utf-8")
    (task_dir / "test.patch").write_text(TEST_PATCH, encoding="utf-8")


def _benchmark_task() -> SelfDevelopmentBenchmarkTask:
    entry = _selection_entry()
    return build_benchmark_task(
        {
            "task_id": entry["instance_id"],
            "repo_url": f"https://github.com/{entry['repo']}",
            "base_commit": entry["base_commit"],
            "issue_text_hash": entry["issue_text_hash"],
            "gold_file_path": entry["gold_file_path"],
            "gold_file_bytes": entry["gold_file_bytes"],
            "f2p_node_ids": cli._str_tuple(entry["f2p_node_ids"]),
            "p2p_node_ids": cli._str_tuple(entry["p2p_node_ids"]),
            "env_manifest": {
                "interpreter": entry["interpreter"],
                "verifier_timeout_seconds": entry[
                    "verifier_timeout_seconds"
                ],
                "min_output_tokens": entry["min_output_tokens"],
            },
        }
    )


@dataclass
class FakeTask:
    task_id: str
    run: object = None


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.run_statuses: list[object] = []
        self.sandbox: object = None

    def create_task(self, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("create", payload))
        return FakeTask("task:benchmark-created")

    def commit_task(self, task_id: str, payload: dict[str, object]) -> FakeTask:
        self.calls.append(("commit", (task_id, payload)))
        return FakeTask(task_id)

    def seal_task_configuration(
        self, task_id: str, payload: dict[str, object]
    ) -> SimpleNamespace:
        self.calls.append(("seal", (task_id, payload)))
        return SimpleNamespace(snapshot_id="task-configuration:fake")

    def record_approval(self, task_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("approve", (task_id, payload)))

    def run_task(
        self,
        task_id: str,
        inputs: dict[str, object],
        configuration_snapshot_id: str | None = None,
    ) -> FakeTask:
        self.calls.append(("run", (task_id, inputs, configuration_snapshot_id)))
        run = (
            SimpleNamespace(status=self.run_statuses.pop(0))
            if self.run_statuses
            else None
        )
        return FakeTask(task_id, run=run)

    def task_json(self, task_id: str) -> dict[str, object]:
        return {"task_id": task_id, "status": "OK"}


def _patch_benchmark_fs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ws: Path,
) -> None:
    monkeypatch.setattr(cli, "_benchmark_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli,
        "_ensure_benchmark_workspace",
        lambda entry, *, repo_root: ws,
    )
    _write_dataset_task(tmp_path, INSTANCE_ID)


def test_cli_benchmark_run_provider_until_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ws = tmp_path / "ws"
    _patch_benchmark_fs(tmp_path, monkeypatch, ws)
    fake = FakeApplication()
    fake.run_statuses = [RunStatus.WAITING_APPROVAL]
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    selection = _write_selection(tmp_path, [_selection_entry()])
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "benchmark-run-provider", str(selection), INSTANCE_ID],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "BENCHMARK_PROVIDER_READY_UNTIL_APPROVAL"
    assert output["instance_id"] == INSTANCE_ID
    assert output["configuration_snapshot_id"] == "task-configuration:fake"
    assert output["task"]["task_id"] == "task:benchmark-created"
    assert [name for name, _ in fake.calls] == [
        "create",
        "commit",
        "seal",
        "run",
    ]
    create_payload = fake.calls[0][1]
    assert isinstance(create_payload, dict)
    statement = str(create_payload["statement"])
    assert "Repository: django/django (base commit " + "0" * 40 + ")" in statement
    assert ISSUE_TEXT.strip() in statement
    assert "Target file: django/utils/dateformat.py" in statement
    assert "tests/utils_tests/test_dateformat.py::TestF::test_format" in statement
    assert "tests/utils_tests/test_dateformat.py::TestF::test_other" in statement
    assert "Replace ONLY the target file." in statement
    assert str(create_payload["goal_id"]).startswith("goal:benchmark:")
    run_call = fake.calls[3][1]
    assert isinstance(run_call, tuple)
    assert run_call[1] == {
        "target_path": "django/utils/dateformat.py",
        "test_command": "python -m pytest",
        "patch_format": "unified_diff",
    }
    assert run_call[2] == "task-configuration:fake"
    assert isinstance(fake.sandbox, BenchmarkContainerSandbox)
    assert fake.sandbox.image_tag == "selfdev2-dryrun-django:py311"
    assert fake.sandbox.f2p_node_ids == cli._str_tuple(
        _selection_entry()["f2p_node_ids"]
    )
    assert fake.sandbox.p2p_node_ids == cli._str_tuple(
        _selection_entry()["p2p_node_ids"]
    )
    assert fake.sandbox.timeout_seconds == 900


def test_cli_benchmark_run_provider_approve_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ws = tmp_path / "ws"
    _patch_benchmark_fs(tmp_path, monkeypatch, ws)
    fake = FakeApplication()
    fake.run_statuses = [RunStatus.WAITING_APPROVAL, RunStatus.SUCCEEDED]
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    selection = _write_selection(tmp_path, [_selection_entry()])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "benchmark-run-provider",
            str(selection),
            INSTANCE_ID,
            "--approve",
        ],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "BENCHMARK_PROVIDER_RUN_COMPLETED"
    assert [name for name, _ in fake.calls] == [
        "create",
        "commit",
        "seal",
        "run",
        "approve",
        "run",
    ]
    approve_call = fake.calls[4][1]
    assert isinstance(approve_call, tuple)
    assert approve_call[1]["disposition"] == "APPROVE"


def test_cli_benchmark_run_provider_unknown_instance_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_benchmark_repo_root", lambda: tmp_path)
    selection = _write_selection(tmp_path, [_selection_entry()])
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "benchmark-run-provider", str(selection), "org__name-999"],
    )
    with pytest.raises(ValueError, match="not in the frozen selection"):
        cli.main()


def _make_workspace_repo(root: Path) -> str:
    import subprocess

    ws = root / ".agent_runs" / "selfdev-2" / "workspaces" / INSTANCE_ID
    ws.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=ws, capture_output=True, check=True)
    (ws / "django").mkdir()
    (ws / "django" / "x.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=ws, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "i"],
        cwd=ws,
        capture_output=True,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ws,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_ensure_benchmark_workspace_happy_path(tmp_path: Path) -> None:
    head = _make_workspace_repo(tmp_path)
    entry = _selection_entry(base_commit=head)
    ws = cli._ensure_benchmark_workspace(entry, repo_root=tmp_path)
    assert ws == tmp_path / ".agent_runs" / "selfdev-2" / "workspaces" / INSTANCE_ID


def test_ensure_benchmark_workspace_fails_closed_when_missing(
    tmp_path: Path,
) -> None:
    try:
        cli._ensure_benchmark_workspace(_selection_entry(), repo_root=tmp_path)
    except SelfDevelopmentValidationError as exc:
        assert exc.code == RUN_DENIED
        assert "benchmark workspace missing" in exc.detail
    else:
        raise AssertionError("missing workspace must fail closed")


def test_ensure_benchmark_workspace_fails_closed_on_head_drift(
    tmp_path: Path,
) -> None:
    _make_workspace_repo(tmp_path)
    try:
        cli._ensure_benchmark_workspace(_selection_entry(), repo_root=tmp_path)
    except SelfDevelopmentValidationError as exc:
        assert exc.code == RUN_DENIED
        assert "head drift" in exc.detail
    else:
        raise AssertionError("head drift must fail closed")


def test_ensure_benchmark_workspace_fails_closed_when_dirty(
    tmp_path: Path,
) -> None:
    head = _make_workspace_repo(tmp_path)
    ws = tmp_path / ".agent_runs" / "selfdev-2" / "workspaces" / INSTANCE_ID
    (ws / "stray.txt").write_text("dirty\n", encoding="utf-8")
    try:
        cli._ensure_benchmark_workspace(
            _selection_entry(base_commit=head), repo_root=tmp_path
        )
    except SelfDevelopmentValidationError as exc:
        assert exc.code == RUN_DENIED
        assert "not clean" in exc.detail
    else:
        raise AssertionError("dirty workspace must fail closed")


def test_prepare_benchmark_task_package_shape() -> None:
    task = _benchmark_task()
    package = prepare_benchmark_task_package(
        task,
        task_id="task:bench-1",
        created_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
        statement="benchmark statement",
        duration_seconds=3600,
    )
    payload = package.task_commit_payload
    commitment = payload["commitment"]
    assert isinstance(commitment, dict)
    assert commitment["authority_scopes"] == [
        "workspace:read",
        "workspace:write",
        "task.configuration.snapshot",
    ]
    assert commitment["budget"] == {
        "max_cost_usd": "10",
        "max_duration_seconds": 3600,
        "max_provider_tokens": 100000,
        "max_tool_calls": 20,
    }
    digest12 = task.task_digest()[:12]
    assert commitment["goal_id"] == f"goal:benchmark:{digest12}"
    assert commitment["commitment_id"] == f"commitment:benchmark:{digest12}"
    assert commitment["expires_at"] == "2026-07-23T01:00:00+00:00"
    workflow = payload["workflow"]
    assert isinstance(workflow, dict)
    nodes = workflow["nodes"]
    assert [node["node_id"] for node in nodes] == [
        "read",
        "provider",
        "approve",
        "apply",
        "tests",
        "evaluate",
        "done",
    ]
    assert [node["kind"] for node in nodes] == [
        "tool",
        "provider",
        "approval",
        "tool",
        "tool",
        "evaluation",
        "terminal",
    ]
    expected = payload["expected_outcome"]
    assert isinstance(expected, dict)
    assert expected["evaluator_type"] == "pytest"
    assert expected["evidence_requirements"] == ["test-report"]
    assert expected["observation_window_seconds"] == 3600
    assert payload["statement"] == "benchmark statement"
    assert package.run_inputs == {
        "target_path": task.gold_file_path,
        "test_command": "python -m pytest",
        "patch_format": "unified_diff",
    }
    assert package.benchmark_task is task


def test_prepare_benchmark_task_package_fails_closed() -> None:
    task = _benchmark_task()
    with pytest.raises(BenchmarkTaskValidationError):
        prepare_benchmark_task_package(
            task, task_id="task:bench-1", duration_seconds=0
        )
    with pytest.raises(BenchmarkTaskValidationError):
        prepare_benchmark_task_package(task, task_id="  ")


def test_extract_unified_diff_from_fenced_output() -> None:
    text = (
        "Here is the fix:\n"
        "```diff\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n"
        "+b\n"
        "```\n"
    )
    assert cli._extract_unified_diff(text) == (
        "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
    )


def test_extract_unified_diff_from_raw_output() -> None:
    text = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
    assert cli._extract_unified_diff(text) == text


def test_extract_unified_diff_missing_fails_closed() -> None:
    with pytest.raises(BenchmarkTaskValidationError) as excinfo:
        cli._extract_unified_diff("no diff here\njust prose\n")
    assert excinfo.value.code == BASELINE_DIFF_INVALID


class FakeProvider:
    def __init__(self, response: ProviderResponse | ProviderFailure) -> None:
        self.response = response
        self.requests: list[ProviderRequest] = []

    def complete(
        self, request: ProviderRequest
    ) -> ProviderResponse | ProviderFailure:
        self.requests.append(request)
        return self.response


def _provider_response(text: str) -> ProviderResponse:
    return ProviderResponse(
        response_id="response:fake",
        request_id="request:fake",
        text=text,
        tool_proposals=(),
        usage=ProviderUsage(
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
            estimated_cost_usd=Decimal("0"),
        ),
        finish_reason="stop",
        received_at=datetime.now(timezone.utc),
    )


class FakeVerifierExecutor:
    """Scripted VerifierExecutor for the baseline CLI flow."""

    def __init__(self, exits: list[int]) -> None:
        self._exits = list(exits)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def apply_candidate(
        self, work_dir: Path, *, content: str | None, diff: str | None
    ) -> None:
        self.calls.append(("apply_candidate", (content, diff)))

    def apply_test_patch(self, work_dir: Path, test_patch: str) -> None:
        self.calls.append(("apply_test_patch", (test_patch,)))

    def run_pytest(
        self,
        work_dir: Path,
        node_ids: tuple[str, ...],
        timeout_seconds: int,
    ) -> ContainerResult:
        self.calls.append(("run_pytest", (node_ids, timeout_seconds)))
        exit_code = self._exits.pop(0) if self._exits else 0
        return ContainerResult(
            exit_code=exit_code, stdout="", stderr="", duration_seconds=0.1
        )

    def restore(self, work_dir: Path) -> None:
        self.calls.append(("restore", ()))

    def method_order(self) -> list[str]:
        return [name for name, _ in self.calls]


def _patch_baseline_runtime(
    monkeypatch: pytest.MonkeyPatch,
    provider: FakeProvider,
    executor: FakeVerifierExecutor,
) -> None:
    monkeypatch.setattr(
        cli,
        "_benchmark_baseline_provider_from_env",
        lambda: (provider, 60),
    )
    monkeypatch.setattr(
        cli,
        "ContainerVerifierExecutor",
        lambda **kwargs: executor,
    )


def test_cli_benchmark_run_baseline_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ws = tmp_path / "ws"
    gold = ws / "django" / "utils" / "dateformat.py"
    gold.parent.mkdir(parents=True)
    gold.write_text("old\n", encoding="utf-8")
    _patch_benchmark_fs(tmp_path, monkeypatch, ws)
    provider = FakeProvider(_provider_response(GOOD_DIFF))
    executor = FakeVerifierExecutor([0, 0])
    _patch_baseline_runtime(monkeypatch, provider, executor)
    selection = _write_selection(tmp_path, [_selection_entry()])
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "benchmark-run-baseline", str(selection), INSTANCE_ID],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["instance_id"] == INSTANCE_ID
    assert output["solved"] is True
    assert output["f2p_passed"] is True
    assert output["p2p_passed"] is True
    assert len(output["evidence_digest"]) == 64
    assert output["usage"]["total_tokens"] == 3
    assert len(provider.requests) == 1
    prompt = provider.requests[0].messages[0].content
    assert ISSUE_TEXT.strip() in prompt
    assert "old\n" in prompt
    assert "Output ONLY a unified diff" in prompt
    assert "django/utils/dateformat.py" in prompt
    assert executor.calls[0] == ("apply_candidate", (None, GOOD_DIFF))
    assert executor.calls[1] == ("apply_test_patch", (TEST_PATCH,))
    assert executor.method_order() == [
        "apply_candidate",
        "apply_test_patch",
        "run_pytest",
        "run_pytest",
        "restore",
    ]


def test_cli_benchmark_run_baseline_not_solved_still_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ws = tmp_path / "ws"
    gold = ws / "django" / "utils" / "dateformat.py"
    gold.parent.mkdir(parents=True)
    gold.write_text("old\n", encoding="utf-8")
    _patch_benchmark_fs(tmp_path, monkeypatch, ws)
    provider = FakeProvider(_provider_response(GOOD_DIFF))
    executor = FakeVerifierExecutor([1])
    _patch_baseline_runtime(monkeypatch, provider, executor)
    selection = _write_selection(tmp_path, [_selection_entry()])
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "benchmark-run-baseline", str(selection), INSTANCE_ID],
    )
    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert output["solved"] is False
    assert output["f2p_passed"] is False
    assert output["p2p_passed"] is False


def test_cli_benchmark_run_baseline_provider_failure_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = tmp_path / "ws"
    gold = ws / "django" / "utils" / "dateformat.py"
    gold.parent.mkdir(parents=True)
    gold.write_text("old\n", encoding="utf-8")
    _patch_benchmark_fs(tmp_path, monkeypatch, ws)
    failure = ProviderFailure(
        failure_id="failure:fake",
        request_id="request:fake",
        code=ProviderErrorCode.UNAVAILABLE,
        retryable=False,
        safe_message="provider unavailable",
        occurred_at=datetime.now(timezone.utc),
    )
    provider = FakeProvider(failure)
    executor = FakeVerifierExecutor([])
    _patch_baseline_runtime(monkeypatch, provider, executor)
    selection = _write_selection(tmp_path, [_selection_entry()])
    monkeypatch.setattr(
        sys,
        "argv",
        ["agent-os", "benchmark-run-baseline", str(selection), INSTANCE_ID],
    )
    with pytest.raises(SelfDevelopmentValidationError) as excinfo:
        cli.main()
    assert excinfo.value.code == RUN_DENIED
    assert executor.calls == []


def test_baseline_provider_from_env_requires_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_OS_PROVIDER_BASE_URL", raising=False)
    with pytest.raises(SelfDevelopmentValidationError) as excinfo:
        cli._benchmark_baseline_provider_from_env()
    assert excinfo.value.code == RUN_DENIED


def test_baseline_provider_from_env_validates_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1"
    )
    monkeypatch.setenv("AGENT_OS_PROVIDER_TIMEOUT_SECONDS", "not-an-int")
    with pytest.raises(ValueError, match="must be an integer"):
        cli._benchmark_baseline_provider_from_env()
