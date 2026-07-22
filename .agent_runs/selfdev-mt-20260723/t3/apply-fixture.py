"""Materialize frozen fixture F3 (prereg §10) into the T3 workspace.

Patches tests/product/test_cli_surface.py:
1. adds RunExecutionError to the agent_os_core import block;
2. adds FakeApplication.run_error state;
3. raises run_error at the top of FakeApplication.run_task;
4. appends test_cli_selfdev_run_provider_reports_structured_failure_without_traceback.
Every anchor must match exactly; the script fails loudly otherwise.
"""

from pathlib import Path
import sys

MARKER = "test_cli_selfdev_run_provider_reports_structured_failure_without_traceback"

IMPORT_OLD = """from agent_os_core import (
    INVALID_SELFDEV_TARGET,
    RUN_DENIED,
    SelfDevelopmentValidationError,
)"""
IMPORT_NEW = """from agent_os_core import (
    INVALID_SELFDEV_TARGET,
    RUN_DENIED,
    RunExecutionError,
    SelfDevelopmentValidationError,
)"""

INIT_ANCHOR = "        self.run_statuses: list[object] = []\n"
INIT_NEW = (
    "        self.run_statuses: list[object] = []\n"
    "        self.run_error: Exception | None = None\n"
)

RUN_ANCHOR = (
    '        self.calls.append(("run", (task_id, inputs, configuration_snapshot_id)))\n'
)
RUN_NEW = RUN_ANCHOR + (
    "        if self.run_error is not None:\n"
    "            raise self.run_error\n"
)

FIXTURE = '''

def test_cli_selfdev_run_provider_reports_structured_failure_without_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("AGENT_OS_PROVIDER_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL", "frontier-model")
    monkeypatch.setenv("AGENT_OS_PROVIDER_API_KEY_ENV", "AGENT_OS_TEST_PROVIDER_KEY")
    monkeypatch.setenv("AGENT_OS_TEST_PROVIDER_KEY", "redacted-test-key")
    fake = FakeApplication()
    fake.run_error = RunExecutionError(
        "provider patch arguments must contain only path and content"
    )
    monkeypatch.setattr(cli, "AgentOSApplication", lambda **kwargs: fake)
    spec_path = _write_selfdev_spec(tmp_path, branch="codex/selfdev-cli-failure")
    baseline_path = _write_selfdev_baseline_record(
        tmp_path,
        branch="codex/selfdev-cli-failure",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent-os",
            "selfdev-run-provider",
            str(spec_path),
            "--baseline-record",
            str(baseline_path),
        ],
    )

    cli.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["mode"] == "REAL_PROVIDER_RUN_FAILED"
    assert output["task"]["task_id"] == "task:selfdev-created"
    assert captured.err == ""
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique or missing: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    target = Path("tests/product/test_cli_surface.py")
    if not target.is_file():
        raise SystemExit(f"anchor file missing: {target}")
    text = target.read_text(encoding="utf-8")
    if MARKER in text:
        raise SystemExit("fixture already applied")
    text = _replace_once(text, IMPORT_OLD, IMPORT_NEW, "agent_os_core import block")
    text = _replace_once(text, INIT_ANCHOR, INIT_NEW, "FakeApplication.__init__")
    text = _replace_once(text, RUN_ANCHOR, RUN_NEW, "FakeApplication.run_task")
    text = text.rstrip("\n") + "\n" + FIXTURE
    target.write_text(text, encoding="utf-8")
    print(f"fixture F3 applied to {target}")


if __name__ == "__main__":
    sys.exit(main())
