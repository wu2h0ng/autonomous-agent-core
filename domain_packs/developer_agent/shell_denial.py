"""Typed, enumerable denial for the developer workspace shell.

The developer sandbox refuses a shell command by *exact-match allowlist*, which
fail-closes everything not explicitly listed. Previously the denial was a bare
``CapabilityDenied`` with a free-text message, so a harness could not consume the
denial reason. This module gives every shell denial a machine-consumable
``ShellDenialReason`` while preserving the fail-closed exact-match behaviour.

Scope note: this deliberately does NOT try to classify "dangerous" commands from a
string. A regex classifier proved brittle (missed wrappers/quoted forms) and
introduced catastrophic backtracking on the product path; a sound classifier needs a
real command parser/token analysis behind its own gate. Here one allowlist refusal
reason is the whole contract.
"""

from __future__ import annotations

from collections.abc import Container
from enum import Enum

from agent_os_core import CapabilityDenied


class ShellDenialReason(str, Enum):
    """Enumerable, machine-consumable reason on every shell denial."""

    NOT_IN_ALLOWLIST = "NOT_IN_ALLOWLIST"


class ShellCommandDenied(CapabilityDenied):
    """Fail-closed shell denial carrying an enumerable reason code.

    Remains a ``CapabilityDenied`` (hence a ``PermissionError``) so existing callers
    and the broker's error handling are unchanged.
    """

    def __init__(
        self,
        reason_code: ShellDenialReason,
        detail: str,
    ) -> None:
        self.reason_code = ShellDenialReason(reason_code)
        super().__init__(detail)


def require_allowlisted_command(
    command: str,
    allowlist: Container[str],
    unlisted_detail: str,
) -> None:
    """Enforce the exact-match allowlist and fail closed with a typed reason.

    Shared by the shell preflight and the execution sites so the allowlist cannot be
    bypassed by reaching execution without a preflight pass.
    """

    if command not in allowlist:
        raise ShellCommandDenied(ShellDenialReason.NOT_IN_ALLOWLIST, unlisted_detail)
