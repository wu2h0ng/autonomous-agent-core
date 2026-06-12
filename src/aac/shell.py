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
