"""Typed dangerous-command classification for the developer workspace shell.

Defense-in-depth: the developer sandbox refuses a shell command by *exact-match
allowlist* already, which fail-closes everything not explicitly listed. This module
adds a second, independent check that runs **before** the allowlist, so that even an
allowlisted command which matches a dangerous pattern is refused and carries a
machine-consumable reason code (``ShellDenialReason``).

This is a deterministic classifier, **not** an OS sandbox: it recognises a bounded
set of clearly destructive command shapes and can never be treated as isolation.
Classification is intentionally narrow (few false positives); it does not parse
shell grammar.
"""

from __future__ import annotations

import re
from enum import Enum

from agent_os_core import CapabilityDenied


class DangerousCommandClass(str, Enum):
    """Bounded categories of clearly destructive/invasive shell commands."""

    RECURSIVE_DELETE = "RECURSIVE_DELETE"
    PRIVILEGE_ESCALATION = "PRIVILEGE_ESCALATION"
    REMOTE_CODE_EXECUTION = "REMOTE_CODE_EXECUTION"
    DEVICE_OVERWRITE = "DEVICE_OVERWRITE"
    FILESYSTEM_DESTRUCTION = "FILESYSTEM_DESTRUCTION"
    PERMISSION_WIDENING = "PERMISSION_WIDENING"
    FORK_BOMB = "FORK_BOMB"


class ShellDenialReason(str, Enum):
    """Enumerable, machine-consumable reason on every shell preflight denial."""

    NOT_IN_ALLOWLIST = "NOT_IN_ALLOWLIST"
    DANGEROUS_PATTERN = "DANGEROUS_PATTERN"


class ShellCommandDenied(CapabilityDenied):
    """Fail-closed shell denial carrying an enumerable reason code."""

    def __init__(
        self,
        reason_code: ShellDenialReason,
        detail: str,
        *,
        classes: tuple[DangerousCommandClass, ...] = (),
    ) -> None:
        self.reason_code = ShellDenialReason(reason_code)
        self.classes = tuple(classes)
        super().__init__(detail)


# Rule table, evaluated against the whitespace-normalised, lower-cased command.
# Each entry is (class, compiled pattern). Patterns target unambiguous destructive
# shapes only; see the S1 gate doc for the explicit non-goal (not a sandbox).
_RULES: tuple[tuple[DangerousCommandClass, re.Pattern[str]], ...] = (
    (
        DangerousCommandClass.RECURSIVE_DELETE,
        re.compile(r"(^|[;&|]\s*)rm\s+(-\w*[rf]\w*|--recursive|--force)(\s|$)"),
    ),
    (
        DangerousCommandClass.PRIVILEGE_ESCALATION,
        re.compile(r"(^|[;&|]\s*)(sudo|doas|su)(\s|$)"),
    ),
    (
        DangerousCommandClass.REMOTE_CODE_EXECUTION,
        re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh|dash|python[0-9.]*)\b"),
    ),
    (
        DangerousCommandClass.DEVICE_OVERWRITE,
        re.compile(r"\bdd\b[^|]*\bof=/dev/|\bof=/dev/[a-z]"),
    ),
    (
        DangerousCommandClass.FILESYSTEM_DESTRUCTION,
        re.compile(r"(^|[;&|]\s*)(mkfs(\.[a-z0-9]+)?|wipefs|shred)(\s|$)"),
    ),
    (
        DangerousCommandClass.PERMISSION_WIDENING,
        re.compile(r"(^|[;&|]\s*)chmod\s+(-\w+\s+)*(777|a\+rwx)(\s|$)"),
    ),
    (
        DangerousCommandClass.FORK_BOMB,
        re.compile(r":\s*\(\s*\)\s*\{"),
    ),
)


def classify_dangerous_command(command: str) -> tuple[DangerousCommandClass, ...]:
    """Return the dangerous classes a command matches (empty = none)."""

    normalized = " ".join(command.split()).lower()
    if not normalized:
        return ()
    seen: list[DangerousCommandClass] = []
    for command_class, pattern in _RULES:
        if pattern.search(normalized) and command_class not in seen:
            seen.append(command_class)
    return tuple(seen)


def is_dangerous_command(command: str) -> bool:
    """True iff the command matches at least one dangerous class."""

    return bool(classify_dangerous_command(command))
