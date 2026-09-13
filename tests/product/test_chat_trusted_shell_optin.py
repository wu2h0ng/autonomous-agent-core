"""M2: the trusted shell profile is opt-in only (mainstream-aligned, fail-closed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_os_core.trusted_commands import TRUSTED_SHELL_PROFILE_V1

from apps.api_server.app import AgentOSApplication


def _app(root: Path, **kwargs: Any) -> AgentOSApplication:
    return AgentOSApplication(
        database=root / "agent-os.sqlite3", workspace=root, **kwargs
    )


def _allowlist(app: AgentOSApplication) -> tuple[str, ...]:
    return tuple(getattr(app.sandbox, "_shell_allowlist"))


def test_trusted_shell_profile_is_off_by_default(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AGENT_OS_TRUSTED_SHELL_PROFILE", raising=False)
    allowlist = _allowlist(_app(tmp_path))
    assert "git status" not in allowlist
    assert allowlist != TRUSTED_SHELL_PROFILE_V1


def test_trusted_shell_profile_opt_in_via_constructor(tmp_path: Path) -> None:
    allowlist = _allowlist(_app(tmp_path, trusted_shell_profile=True))
    assert allowlist == TRUSTED_SHELL_PROFILE_V1


def test_trusted_shell_profile_opt_in_via_env(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_OS_TRUSTED_SHELL_PROFILE", "1")
    assert _allowlist(_app(tmp_path)) == TRUSTED_SHELL_PROFILE_V1
