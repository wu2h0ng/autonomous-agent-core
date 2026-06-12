from __future__ import annotations

import copy
from typing import Any

from .audit import AuditLog


class CorrigibilityShell:
    """The shell: observe / pause / rollback / tighten — driven from OUTSIDE.

    The agent holds a reference to the shell but is given no method to clear a
    pause, widen a tightening, or edit the audit log. Those operations live only
    on the operator-facing surface (``op_*``). In a real deployment ``op_*``
    sit behind infrastructure/account-level auth the agent process cannot reach;
    in this prototype the separation is by convention + tests.
    """

    def __init__(self) -> None:
        self.audit = AuditLog()
        self._paused = False
        self._forbidden: set[int] = set()
        self._snapshots: dict[str, Any] = {}

    # --- agent-facing (read-only intent) ---
    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def forbidden(self) -> frozenset[int]:
        return frozenset(self._forbidden)

    def observe(self, payload: dict[str, Any]) -> None:
        self.audit.append(payload)

    # --- operator-facing: the four pillars ---
    def op_pause(self) -> None:
        self._paused = True
        self.audit.append({"event": "pause"})

    def op_resume(self) -> None:
        self._paused = False
        self.audit.append({"event": "resume"})

    def op_tighten(self, action: int) -> None:
        self._forbidden.add(action)
        self.audit.append({"event": "tighten", "action": action})

    def op_snapshot(self, label: str, state: Any) -> None:
        self._snapshots[label] = copy.deepcopy(state)
        self.audit.append({"event": "snapshot", "label": label})

    def op_rollback(self, label: str) -> Any:
        self.audit.append({"event": "rollback", "label": label})
        return copy.deepcopy(self._snapshots[label])

    # --- ISO-1: hand the agent a capability view, never the shell itself ---
    def view(self) -> ShellView:
        """Return the agent-facing capability view (ISO-1, ADR-0009).

        The operator keeps ``self``; the agent is given only this view, which
        exposes the read-only intent surface (``paused``/``forbidden``/
        ``observe``) and no ``op_*``. The agent therefore holds no writable
        reference to ``_paused``/``_forbidden``/``_snapshots``.
        """
        return ShellView(
            paused_getter=lambda: self._paused,
            forbidden_getter=lambda: self.forbidden,
            observe=self.observe,
        )


class ShellView:
    """Agent-facing capability view of the shell (ISO-1, ADR-0009).

    Holds no writable reference to the shell's pause/forbidden/snapshot state
    and exposes no ``op_*`` operator surface. ``__slots__`` blocks the agent
    from even setting a stray ``_paused`` attribute. The agent receives only
    this view; the operator keeps the :class:`CorrigibilityShell`.

    ISO-1 honesty (ADR-0009): this removes the *direct reference* path only.
    In-process introspection (``gc.get_objects``, ``__closure__``,
    ``type.__subclasses__``) can still reach the shell object. Hard
    unreachability is ISO-2 (out-of-process); see ``shell_ipc`` reference.
    """

    __slots__ = ("_paused_getter", "_forbidden_getter", "_observe")

    def __init__(self, *, paused_getter: Any, forbidden_getter: Any, observe: Any) -> None:
        self._paused_getter = paused_getter
        self._forbidden_getter = forbidden_getter
        self._observe = observe

    @property
    def paused(self) -> bool:
        return bool(self._paused_getter())

    @property
    def forbidden(self) -> frozenset[int]:
        return self._forbidden_getter()

    def observe(self, payload: dict[str, Any]) -> None:
        self._observe(payload)
