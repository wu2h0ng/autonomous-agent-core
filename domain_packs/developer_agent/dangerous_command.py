"""Typed dangerous-command classification for the developer workspace shell.

Defense-in-depth: the developer sandbox refuses a shell command by *exact-match
allowlist* already, which fail-closes everything not explicitly listed. This module
adds a second, independent check that runs **before** the allowlist — at both the
preflight and the execution site — so that even an allowlisted command which matches
a dangerous pattern is refused and carries a machine-consumable reason code
(``ShellDenialReason``).

This is a deterministic classifier, **not** an OS sandbox: it recognises a bounded
set of clearly destructive command shapes (including common wrappers, path-qualified
binaries and shell chains) and can never be treated as isolation. It is deliberately
narrow (few false positives) and does not implement a full shell parser.
"""

from __future__ import annotations

import re
from collections.abc import Container
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
    """Enumerable, machine-consumable reason on every shell denial."""

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


def require_safe_shell_command(
    command: str,
    allowlist: Container[str],
    unlisted_detail: str,
) -> None:
    """Refuse a dangerous command, then enforce the exact-match allowlist.

    Shared by the shell preflight and the execution sites so the classifier cannot
    be bypassed by reaching execution without a preflight pass.
    """

    classes = classify_dangerous_command(command)
    if classes:
        raise ShellCommandDenied(
            ShellDenialReason.DANGEROUS_PATTERN,
            "command matches dangerous patterns: "
            + ",".join(command_class.value for command_class in classes),
            classes=classes,
        )
    if command not in allowlist:
        raise ShellCommandDenied(ShellDenialReason.NOT_IN_ALLOWLIST, unlisted_detail)


# Benign launchers stripped before classifying a segment, so `env rm -rf x` is
# treated like `rm -rf x`. Privilege launchers (sudo/doas/su) are intentionally
# NOT stripped — they are themselves a signal.
_LAUNCHERS = frozenset(
    {
        "env",
        "command",
        "time",
        "nohup",
        "nice",
        "ionice",
        "xargs",
        "busybox",
        "eval",
        "exec",
        "stdbuf",
        "setsid",
    }
)
_SEGMENT_SPLIT = re.compile(r"[;&|\n]+")
_PATH_PREFIX = re.compile(r"^/?(?:[A-Za-z0-9._+-]+/)+")

# kind="seg" matches a launcher-stripped, lower-cased segment anchored at its start
# (a command position). kind="full" matches the whole normalised command line (for
# pipeline/redirect/chain shapes that span separators).
_RULES: tuple[tuple[DangerousCommandClass, str, re.Pattern[str]], ...] = (
    (
        DangerousCommandClass.RECURSIVE_DELETE,
        "seg",
        # recursive delete: the rm argument list must contain a flag with an r/R
        # (-r / -rf / -Rf / -f -r / --recursive), order-independent; plain rm/-f is clean
        re.compile(r"^rm\s+(?=[^;&|]*-{1,2}[\w-]*r[\w-]*\b)"),
    ),
    (
        DangerousCommandClass.PRIVILEGE_ESCALATION,
        "seg",
        re.compile(r"^(sudo|doas|su)\s+(?!(-h|-V|--help|--version)\b)"),
    ),
    (
        DangerousCommandClass.REMOTE_CODE_EXECUTION,
        "full",
        re.compile(
            r"\b(curl|wget)\b.*\|(\s*\S+\s*\|)*\s*"
            r"(?:(?:sudo|doas|env|command)\s+)?(?:\S*/)?"
            r"(sh|bash|zsh|dash|ksh|python[0-9.]*|perl|ruby)\b"
        ),
    ),
    (
        DangerousCommandClass.DEVICE_OVERWRITE,
        "full",
        re.compile(
            r"\bdd\b[^|]*\bof=/dev/(sd|hd|nvme|disk|rdisk|mmcblk|vd|xvd)"
            r"|>>?\s*/dev/(sd|hd|nvme|disk|rdisk|mmcblk|vd|xvd)"
        ),
    ),
    (
        DangerousCommandClass.FILESYSTEM_DESTRUCTION,
        "seg",
        re.compile(r"^(mkfs(\.[a-z0-9]+)?|wipefs|shred)\b"),
    ),
    (
        DangerousCommandClass.FILESYSTEM_DESTRUCTION,
        "full",
        re.compile(
            r"\bgit\s+clean\b[^|]*\s-\w*[fd]"
            r"|\bfind\b[^|]*(-delete\b|-exec\s+(?:\S*/)?rm\b)"
        ),
    ),
    (
        DangerousCommandClass.PERMISSION_WIDENING,
        "seg",
        re.compile(r"^chmod\s+(-{1,2}[\w-]+\s+)*(777|0777|a\+rwx)\b"),
    ),
    (
        DangerousCommandClass.FORK_BOMB,
        "full",
        # a function definition whose body pipes/backgrounds itself (fork bomb),
        # e.g. ':(){ :|:& };:' or 'f(){ f|f& };f'
        re.compile(r"([^\s(){}]+)\s*\(\s*\)\s*\{[^}]*(?:\1\s*[|&]|[|&]\s*\1)[^}]*\}"),
    ),
)


def _command_segments(command: str) -> list[str]:
    """Split on shell separators and strip benign launcher/path prefixes."""

    segments: list[str] = []
    for raw in _SEGMENT_SPLIT.split(command):
        tokens = raw.strip().split()
        index = 0
        while index < len(tokens):
            head = _PATH_PREFIX.sub("", tokens[index].lower())
            if head in _LAUNCHERS:
                index += 1
                continue
            tokens[index] = head
            break
        if index < len(tokens):
            segments.append(" ".join(tokens[index:]).lower())
    return segments


def classify_dangerous_command(command: str) -> tuple[DangerousCommandClass, ...]:
    """Return the dangerous classes a command matches (empty = none)."""

    normalized = " ".join(command.split()).lower()
    if not normalized:
        return ()
    segments = _command_segments(command)
    seen: list[DangerousCommandClass] = []
    for command_class, kind, pattern in _RULES:
        if command_class in seen:
            continue
        if kind == "seg":
            hit = any(pattern.search(segment) for segment in segments)
        else:
            hit = pattern.search(normalized) is not None
        if hit:
            seen.append(command_class)
    return tuple(seen)


def is_dangerous_command(command: str) -> bool:
    """True iff the command matches at least one dangerous class."""

    return bool(classify_dangerous_command(command))
