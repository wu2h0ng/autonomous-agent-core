"""Typed hooks runtime (shard B) — isolated, fail-closed event observers.

Conservative defaults, enforced in CODE (not just docs) and pinned in
ADR-0062 (pending founder ratification):

1. **Off by default.** A hook dispatcher with no configuration (or the
   global kill-switch ``AGENT_OS_HOOKS_DISABLED=1``) dispatches NOTHING and
   leaves the baseline behavior byte-identical.
2. **In-repo / workspace sources forbidden.** Hooks may only be loaded from
   operator-owned files outside the workspace. The workspace is writable by
   the agent itself, so a workspace-sourced hook would make model output
   executable code.
3. **Isolated process.** Hooks are NEVER executed inside the daemon process.
   Each dispatch spawns a short-lived subprocess with a restricted
   environment; the daemon process does not ``exec`` or ``eval`` hook code.
4. **No authority.** The v1 hook return value is always ``None`` (observer
   only). A hook receives a frozen read-only snapshot on stdin and returns a
   small JSON record on stdout; it never receives a permit, an approval
   gateway, the correction admin port, or any write handle.
5. **Not an MCP/skills carrier.** A hook only reacts to typed events; it
   does not expose tools or skills.

This module intentionally does NOT touch ``agent_loop`` / ``task_service`` /
``child_agent`` (other shards). It is a self-contained library that the
composition root can wire in later; hermetic tests drive it directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Final

from agent_os_contracts import (
    FORBIDDEN_SUBPROCESS_ENV_NAMES,
    HookConfig,
    HookDispatchRecord,
    HookEvent,
    HookOnError,
    HookOutcome,
    HookSourceKind,
)

#: Global kill-switch. When set to a truthy value, no hook runs.
HOOKS_DISABLED_ENV: Final = "AGENT_OS_HOOKS_DISABLED"

#: Default per-dispatch subprocess timeout (seconds). Hooks are observers;
#: they must never stall a turn.
DEFAULT_HOOK_TIMEOUT_SECONDS: Final = 2.0

#: Baseline environment passed to a hook subprocess. This is deliberately
#: minimal: only what a portable script needs. No provider keys, no daemon
#: env. The operator may add explicitly-allow-listed vars at construction.
_BASE_HOOK_ENV: Final[dict[str, str]] = {
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
}


class HookConfigurationError(ValueError):
    """Raised when a hook configuration is structurally unacceptable."""


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip() not in {"", "0", "false", "False"}


def hooks_globally_disabled() -> bool:
    """Return True when the operator kill-switch is on."""

    return _truthy(os.environ.get(HOOKS_DISABLED_ENV))


def _restricted_env(extra_allow: tuple[str, ...]) -> dict[str, str]:
    """Build the environment for a hook subprocess.

    Only the baseline env plus the explicitly allow-listed names are
    included. Provider keys and any name in
    ``FORBIDDEN_SUBPROCESS_ENV_NAMES`` are never passed, even if they appear
    in ``extra_allow`` (defense in depth).
    """

    env: dict[str, str] = dict(_BASE_HOOK_ENV)
    for name in extra_allow:
        if name in FORBIDDEN_SUBPROCESS_ENV_NAMES:
            continue
        if name in os.environ:
            env[name] = os.environ[name]
    return env


@dataclass(frozen=True)
class HookSnapshot:
    """A frozen, read-only event snapshot handed to a hook.

    Carries no credentials, no write handles, and no authority object. The
    payload is the only thing a hook ever sees.
    """

    event: HookEvent
    payload: dict[str, Any] = field(default_factory=dict)


class HookRegistry:
    """Loads and validates operator-owned hook configurations.

    Fail-closed: an unknown event, a forbidden source kind, or an integrity
    mismatch rejects that hook (and, for an unknown event, the whole
    configuration) rather than silently dropping it.
    """

    def __init__(
        self,
        *,
        allowed_source_root: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self._hooks: dict[str, HookConfig] = {}
        # Operator-owned root hooks must live under. When None, only the
        # in-config absolute path policy (outside workspace) is enforced.
        self._allowed_source_root = allowed_source_root
        self._workspace_root = (
            os.path.abspath(workspace_root) if workspace_root else None
        )

    @property
    def is_empty(self) -> bool:
        return len(self._hooks) == 0

    def register(self, config: HookConfig) -> None:
        """Validate and register a single hook configuration.

        Raises HookConfigurationError on any fail-closed condition.
        """

        if config.source_kind is not HookSourceKind.OPERATOR_FILE:
            raise HookConfigurationError(
                f"hook {config.hook_id!r}: only operator_file sources are "
                f"allowed in v1 (got {config.source_kind!r}); workspace/"
                f"in-repo hook sources are forbidden"
            )

        source = os.path.abspath(config.source_path)

        # In-repo / workspace sources are forbidden.
        if self._workspace_root is not None and source.startswith(
            self._workspace_root + os.sep
        ):
            raise HookConfigurationError(
                f"hook {config.hook_id!r}: source {source!r} is inside the "
                f"workspace ({self._workspace_root!r}); workspace hook "
                f"sources are forbidden by default"
            )

        if self._allowed_source_root is not None:
            root = os.path.abspath(self._allowed_source_root)
            if not source.startswith(root + os.sep):
                raise HookConfigurationError(
                    f"hook {config.hook_id!r}: source {source!r} is outside "
                    f"the allowed operator root {root!r}"
                )

        # Integrity pin: the operator pins the sha256 of the hook bytes. We
        # verify it lazily at dispatch time (we may not have the file yet in a
        # hermetic unit test), but the pin itself must look sane here.
        if len(config.sha256) != 64 or any(c not in "0123456789abcdef" for c in config.sha256):
            raise HookConfigurationError(
                f"hook {config.hook_id!r}: sha256 pin must be 64 lowercase "
                f"hex chars"
            )

        self._hooks[config.hook_id] = config

    def for_event(self, event: HookEvent) -> list[HookConfig]:
        return [h for h in self._hooks.values() if h.enabled and h.event is event]

    def get(self, hook_id: str) -> HookConfig | None:
        return self._hooks.get(hook_id)


def _verify_integrity(config: HookConfig) -> None:
    """Verify the hook bytes match the pinned sha256. Fail-closed on mismatch."""

    import hashlib

    try:
        data = open(config.source_path, "rb").read()
    except OSError as exc:
        raise HookConfigurationError(
            f"hook {config.hook_id!r}: cannot read source: {exc}"
        ) from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != config.sha256:
        raise HookConfigurationError(
            f"hook {config.hook_id!r}: integrity mismatch (expected "
            f"{config.sha256}, got {digest}); hook not loaded"
        )


class HookDispatcher:
    """Dispatches typed events to isolated hook subprocesses.

    Lifecycle:
    - ``dispatch(event, payload)`` runs every enabled hook for the event in a
      fresh subprocess and records a durable ``HookDispatchRecord``.
    - ``close()`` is a no-op cleanup hook (subprocesses are already reaped
      per-dispatch with a timeout); it exists so callers have an explicit
      lifecycle point.
    """

    def __init__(
        self,
        registry: HookRegistry,
        *,
        extra_env_allow: tuple[str, ...] = (),
        timeout_seconds: float = DEFAULT_HOOK_TIMEOUT_SECONDS,
        python_executable: str | None = None,
    ) -> None:
        self._registry = registry
        self._extra_env_allow = extra_env_allow
        self._timeout = timeout_seconds
        self._python = python_executable or sys.executable
        self.records: list[HookDispatchRecord] = []
        self._closed = False

    @property
    def enabled(self) -> bool:
        """The dispatcher is active only when hooks are not globally disabled
        and there is at least one registered hook."""

        return not hooks_globally_disabled() and not self._registry.is_empty

    def dispatch(self, event: HookEvent, payload: dict[str, Any]) -> list[HookDispatchRecord]:
        """Dispatch an event. Never raises into the caller.

        When hooks are globally disabled or there are no hooks, this returns
        an empty list and spawns nothing (baseline byte-identical behavior).
        """

        if self._closed:
            return []
        if hooks_globally_disabled():
            return []
        hooks = self._registry.for_event(event)
        if not hooks:
            return []

        snapshot = HookSnapshot(event=event, payload=payload)
        results: list[HookDispatchRecord] = []
        for config in hooks:
            record = self._run_one(config, snapshot)
            results.append(record)
            self.records.append(record)
        return results

    def _run_one(
        self, config: HookConfig, snapshot: HookSnapshot
    ) -> HookDispatchRecord:
        started = time.monotonic()
        try:
            _verify_integrity(config)
        except HookConfigurationError as exc:
            outcome = (
                HookOutcome.FAILED
                if config.on_error is HookOnError.FAIL_CLOSED
                else HookOutcome.SKIPPED
            )
            return HookDispatchRecord(
                hook_id=config.hook_id,
                event=snapshot.event,
                outcome=outcome,
                latency_ms=int((time.monotonic() - started) * 1000),
                reason=f"integrity: {exc}",
            )

        env = _restricted_env(self._extra_env_allow)
        request = json.dumps(
            {"event": snapshot.event.value, "payload": snapshot.payload},
            ensure_ascii=False,
        )
        argv = [self._python, config.source_path, "--entry", config.entry]
        try:
            proc = subprocess.run(
                argv,
                input=request,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._record(
                config, snapshot, started, HookOutcome.SKIPPED, "timeout"
            )
        except OSError as exc:
            return self._record(
                config,
                snapshot,
                started,
                HookOutcome.FAILED,
                f"spawn: {exc}",
            )

        if proc.returncode != 0:
            outcome = (
                HookOutcome.FAILED
                if config.on_error is HookOnError.FAIL_CLOSED
                else HookOutcome.SKIPPED
            )
            return self._record(
                config,
                snapshot,
                started,
                outcome,
                f"exit_{proc.returncode}",
            )

        # v1 observer hooks return no authority object. We only record that
        # they ran cleanly; any "deny" semantics are deferred to P2 and are
        # out of scope for this minimal slice.
        return self._record(config, snapshot, started, HookOutcome.OK, "ran")

    def _record(
        self,
        config: HookConfig,
        snapshot: HookSnapshot,
        started: float,
        outcome: HookOutcome,
        reason: str,
    ) -> HookDispatchRecord:
        return HookDispatchRecord(
            hook_id=config.hook_id,
            event=snapshot.event,
            outcome=outcome,
            latency_ms=int((time.monotonic() - started) * 1000),
            reason=reason,
        )

    def close(self) -> None:
        """Explicit lifecycle cleanup. Per-dispatch subprocesses are already
        reaped by ``subprocess.run`` with a timeout, so this is a marker."""

        self._closed = True
