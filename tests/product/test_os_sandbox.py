"""OS-SANDBOX-0: Seatbelt execution isolation is opt-in and fail-closed.

Isolation is an OS-level confinement *below* the permit/approval spine. It
never substitutes for approval, never relaxes the shell allowlist and never
enters the policy kernel. ``sandboxed`` is macOS-only and must fail closed if
the OS sandbox is unavailable (never silently fall back to trusted-workspace).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from agent_os_core.capability import CapabilityDenied

from apps.api_server.app import AgentOSApplication
from domain_packs.developer_agent import (
    EXECUTION_ISOLATION_SANDBOXED,
    EXECUTION_ISOLATION_TRUSTED_WORKSPACE,
    WorkspaceSandbox,
)

_MACOS = sys.platform == "darwin"
_HAS_SEATBELT = _MACOS and shutil.which("sandbox-exec") is not None


def _app(root: Path, **kwargs: Any) -> AgentOSApplication:
    return AgentOSApplication(
        database=root / "agent-os.sqlite3", workspace=root, **kwargs
    )


def test_default_isolation_is_trusted_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AGENT_OS_EXECUTION_ISOLATION", raising=False)
    app = _app(tmp_path)
    assert app.execution_isolation == EXECUTION_ISOLATION_TRUSTED_WORKSPACE
    assert app.sandbox.execution_isolation() == EXECUTION_ISOLATION_TRUSTED_WORKSPACE


def test_isolation_opt_in_via_constructor(tmp_path: Path) -> None:
    app = _app(tmp_path, execution_isolation=EXECUTION_ISOLATION_SANDBOXED)
    assert app.sandbox.execution_isolation() == EXECUTION_ISOLATION_SANDBOXED


def test_isolation_opt_in_via_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_OS_EXECUTION_ISOLATION", EXECUTION_ISOLATION_SANDBOXED)
    app = _app(tmp_path)
    assert app.sandbox.execution_isolation() == EXECUTION_ISOLATION_SANDBOXED


def test_invalid_isolation_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="execution_isolation must be one of"):
        WorkspaceSandbox(tmp_path, execution_isolation="unsafe")


def test_sandboxed_without_os_sandbox_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sandboxed must raise rather than silently run unconfined."""
    sandbox = WorkspaceSandbox(
        tmp_path, execution_isolation=EXECUTION_ISOLATION_SANDBOXED
    )
    monkeypatch.setattr(
        "domain_packs.developer_agent.workspace_capability.sys.platform",
        "darwin",
    )
    monkeypatch.setattr(
        "domain_packs.developer_agent.workspace_capability."
        "shutil.which",
        lambda _name: None,
    )
    with pytest.raises(CapabilityDenied, match="OS filesystem sandbox"):
        sandbox._execute_confined(["/bin/echo", "hi"], 10)


def test_sandboxed_off_macos_fails_closed(tmp_path: Path, monkeypatch) -> None:
    sandbox = WorkspaceSandbox(
        tmp_path, execution_isolation=EXECUTION_ISOLATION_SANDBOXED
    )
    monkeypatch.setattr(
        "domain_packs.developer_agent.workspace_capability.sys.platform",
        "linux",
    )
    with pytest.raises(CapabilityDenied, match="only available on macOS"):
        sandbox._execute_confined(["/bin/echo", "hi"], 10)


def test_trusted_mode_still_executes(tmp_path: Path) -> None:
    sandbox = WorkspaceSandbox(tmp_path)
    result, evidence = sandbox._execute_confined(["/bin/echo", "trusted-ok"], 10)
    assert result.returncode == 0
    assert evidence["execution_isolation"] == EXECUTION_ISOLATION_TRUSTED_WORKSPACE


def test_sandboxed_confines_writes_and_network(tmp_path: Path) -> None:
    """On macOS this must assert confinement; elsewhere it must fail closed."""
    if not _HAS_SEATBELT:
        sandbox = WorkspaceSandbox(
            tmp_path, execution_isolation=EXECUTION_ISOLATION_SANDBOXED
        )
        with pytest.raises(CapabilityDenied):
            sandbox._execute_confined(["/bin/echo", "hi"], 10)
        return

    sandbox = WorkspaceSandbox(
        tmp_path, execution_isolation=EXECUTION_ISOLATION_SANDBOXED
    )

    inside = tmp_path / "inside.txt"
    ok, evidence = sandbox._execute_confined(
        ["/bin/sh", "-c", f"echo ok > {inside}"], 10
    )
    assert ok.returncode == 0
    assert inside.read_text(encoding="utf-8").strip() == "ok"
    assert evidence["execution_isolation"] == EXECUTION_ISOLATION_SANDBOXED
    assert evidence["sandbox_profile_sha256"]

    outside = tmp_path.parent / "sandbox-escape.txt"
    if outside.exists():
        outside.unlink()
    escaped, _ = sandbox._execute_confined(
        ["/bin/sh", "-c", f"echo bad > {outside}"], 10
    )
    assert escaped.returncode != 0
    assert not outside.exists()

    read_back, _ = sandbox._execute_confined(["/bin/ls", str(Path.home())], 10)
    assert read_back.returncode != 0

    if shutil.which("curl") is not None:
        net, _ = sandbox._execute_confined(
            ["/usr/bin/curl", "-s", "--max-time", "3", "https://example.com"], 10
        )
        assert net.returncode != 0


def test_sandbox_profile_digest_is_stable(tmp_path: Path) -> None:
    if not _MACOS:
        pytest.skip("Seatbelt profile digest requires macOS")
    if not _HAS_SEATBELT:
        pytest.fail("macOS without sandbox-exec must fail closed, not skip")
    sandbox = WorkspaceSandbox(
        tmp_path, execution_isolation=EXECUTION_ISOLATION_SANDBOXED
    )
    _, first = sandbox._execute_confined(["/bin/echo", "one"], 10)
    _, second = sandbox._execute_confined(["/bin/echo", "two"], 10)
    assert first["sandbox_profile_sha256"] == second["sandbox_profile_sha256"]

    other_root = tmp_path.parent / "other-workspace"
    other_root.mkdir()
    other = WorkspaceSandbox(
        other_root, execution_isolation=EXECUTION_ISOLATION_SANDBOXED
    )
    _, third = other._execute_confined(["/bin/echo", "three"], 10)
    assert third["sandbox_profile_sha256"] != first["sandbox_profile_sha256"]


def test_shell_sandboxed_fails_closed_when_os_sandbox_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = WorkspaceSandbox(
        tmp_path,
        shell_allowlist=("pytest",),
        execution_isolation=EXECUTION_ISOLATION_SANDBOXED,
    )
    monkeypatch.setattr(
        "domain_packs.developer_agent.workspace_capability.sys.platform",
        "darwin",
    )
    monkeypatch.setattr(
        "domain_packs.developer_agent.workspace_capability.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(CapabilityDenied, match="OS filesystem sandbox"):
        sandbox._shell({"command": "pytest"}, "action:shell")


def test_seatbelt_path_guard_rejects_unsafe_characters() -> None:
    from domain_packs.developer_agent.workspace_capability import (
        _assert_seatbelt_paths,
    )

    with pytest.raises(CapabilityDenied, match="unsafe characters"):
        _assert_seatbelt_paths(("/tmp/ok", '/tmp/bad"name'))
    with pytest.raises(CapabilityDenied, match="unsafe characters"):
        _assert_seatbelt_paths(("/tmp/back\\slash",))
    _assert_seatbelt_paths(("/tmp/ok", "/tmp/also-ok"))


def test_read_roots_exclude_filesystem_root_and_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from domain_packs.developer_agent.workspace_capability import (
        _sandbox_read_roots,
    )

    monkeypatch.setenv("PATH", os.pathsep.join((str(Path.home()), "/")))
    roots = {str(value) for value in _sandbox_read_roots(tmp_path)}
    assert str(Path.home().resolve()) not in roots
    assert "/" not in roots
    assert str(tmp_path.resolve()) in roots


def test_shell_report_records_isolation_evidence(tmp_path: Path) -> None:
    sandbox = WorkspaceSandbox(
        tmp_path,
        shell_allowlist=("pytest",),
        execution_isolation=EXECUTION_ISOLATION_TRUSTED_WORKSPACE,
    )
    result = sandbox._shell({"command": "pytest"}, "action:shell")
    artifact = sandbox.artifacts / str(result["digest"])
    report = __import__("json").loads(artifact.read_text(encoding="utf-8"))
    assert report["execution_isolation"] == EXECUTION_ISOLATION_TRUSTED_WORKSPACE


def test_run_tests_sandboxed_blocks_filesystem_escape(tmp_path: Path) -> None:
    if not _MACOS:
        pytest.skip("Seatbelt confinement requires macOS")
    if not _HAS_SEATBELT:
        pytest.fail("macOS without sandbox-exec must fail closed, not skip")
    (tmp_path / "test_escape_probe.py").write_text(
        "import pathlib\n"
        "def test_escape():\n"
        "    target = pathlib.Path(__file__).resolve().parent.parent / 'escaped.txt'\n"
        "    target.write_text('x')\n",
        encoding="utf-8",
    )
    escaped = tmp_path.parent / "escaped.txt"
    if escaped.exists():
        escaped.unlink()
    sandbox = WorkspaceSandbox(
        tmp_path, execution_isolation=EXECUTION_ISOLATION_SANDBOXED
    )
    result = sandbox._run_tests(
        {"command": "pytest", "timeout_seconds": 60}, "action:test"
    )
    assert result["exit_code"] != 0
    assert not escaped.exists()
