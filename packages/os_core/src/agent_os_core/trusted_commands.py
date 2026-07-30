"""Trusted shell command profiles for Agent CLI sessions."""

from __future__ import annotations

from typing import Protocol


class TrustedShellProfileTarget(Protocol):
    def set_shell_allowlist(self, allowlist: tuple[str, ...]) -> None: ...


TRUSTED_SHELL_PROFILE_V1: tuple[str, ...] = (
    "pytest",
    "python -m pytest",
    "python3 -m pytest",
    "git status",
    "git diff",
    "git diff --stat",
    "git log -5 --oneline",
    "ruff check",
    "ruff check .",
)


def apply_trusted_shell_profile(sandbox: TrustedShellProfileTarget) -> None:
    """Replace sandbox shell allowlist with the Agent CLI trusted profile."""
    sandbox.set_shell_allowlist(TRUSTED_SHELL_PROFILE_V1)
