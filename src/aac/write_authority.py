"""WriteAuthorityLedger — the auditable write-authority declaration surface (Stage-3).

Formal model: docs/pre_spec/STAGE3-GOAL-SYSTEM.FORMAL-MODEL-2026-07-03.md (9644089).

HONEST WORDING (RR-0035 critic adopted): the enum's absence of gate_write / shell_write /
terminal_goal_write / audit_write is the DECLARATION leg only. The load-bearing legs of
the SD4 structural prohibition are (i) shell process isolation (shell_ipc: the agent holds
no write handle) and (ii) the GovernedDecisionGate being a frozen pure function with no
reachable parameter surface. This module adds the third leg: every write channel must be
DECLARED here; an unknown authority raises (unrepresentable), an undeclared writer is
refused and audited — so a silent new write channel cannot appear without tripping either
the type or the audit chain.
"""

from __future__ import annotations

from typing import Callable, Optional

BELIEF_WRITE = "belief_write"
MEMORY_WRITE = "memory_write"
GOAL_DECOMPOSITION_WRITE = "goal_decomposition_write"
PROPOSAL_ORDERING_WRITE = "proposal_ordering_write"
ORGAN_PARAM_UPDATE_OFFLINE = "organ_param_update_offline"

ALLOWED = frozenset({
    BELIEF_WRITE, MEMORY_WRITE, GOAL_DECOMPOSITION_WRITE,
    PROPOSAL_ORDERING_WRITE, ORGAN_PARAM_UPDATE_OFFLINE,
})


class UnknownAuthority(ValueError):
    """gate/shell/terminal-goal/audit writes are not representable authorities."""


class WriteAuthorityLedger:
    def __init__(self, observe: Optional[Callable[[dict], None]] = None) -> None:
        self._grants: set[tuple[str, str]] = set()
        self._observe = observe

    def _emit(self, payload: dict) -> None:
        if self._observe is not None:
            self._observe(payload)

    def grant(self, writer: str, authority: str) -> None:
        if authority not in ALLOWED:
            raise UnknownAuthority(
                f"'{authority}' is not a representable write authority (SD4 declaration leg)")
        self._grants.add((writer, authority))
        self._emit({"event": "write_granted", "writer": writer, "authority": authority})

    def check(self, writer: str, authority: str) -> bool:
        if authority not in ALLOWED:
            raise UnknownAuthority(f"'{authority}' is not a representable write authority")
        ok = (writer, authority) in self._grants
        if not ok:
            self._emit({"event": "write_refused", "writer": writer, "authority": authority})
        return ok
