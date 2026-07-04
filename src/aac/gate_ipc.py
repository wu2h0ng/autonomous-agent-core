"""ISO-2 Gate: GovernedDecisionGate in a separate process (ADR-0009 / RR-0052 §4).

Closes the introspection gap that ISO-1 leaves open: an agent with gc.get_objects()
or __closure__ access can reach the in-process gate and mutate self_model or bypass
the shell check. ISO-2 moves the gate into a subprocess; the agent holds only a
GateProxy (a pipe endpoint). The gate's memory is in a different address space —
structurally unreachable by the agent process.

The GateProxy implements the same decide() signature as GovernedDecisionGate,
so GovernedLoop can use either transparently (duck-typed).
"""

from __future__ import annotations

import multiprocessing as mp
import sys
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any, Optional

from .governed_gate import GovernedDecisionGate, GateDecision, DENY
from .self_model import AgentSelfModel, ActionRequest


def _gate_server_loop(conn: Connection, gate: GovernedDecisionGate,
                      shell: Any, src_path: str) -> None:
    """Gate server: runs in subprocess. Accepts request dicts, returns decision dicts."""
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break

        if msg == "SHUTDOWN":
            break

        if msg == "READ_FORBIDDEN":
            forbidden = getattr(shell, "forbidden", frozenset())
            conn.send({"forbidden": list(forbidden)})
            continue

        if not isinstance(msg, dict) or "action" not in msg:
            conn.send({"verdict": DENY, "reason": "malformed request"})
            continue

        try:
            req = ActionRequest(
                action=msg["action"],
                risk_tier=msg.get("risk_tier", 1),
                confidence=msg.get("confidence", 0.0),
                verified=msg.get("verified", False),
                evidence_count=msg.get("evidence_count", 0),
                approved=msg.get("approved", False),
                action_index=msg.get("action_index"),
            )
            llm_reliability = msg.get("llm_reliability")
            decision = gate.decide(req, shell_view=shell, llm_reliability=llm_reliability)
            conn.send({"verdict": decision.verdict, "reason": decision.reason})
        except Exception as e:
            conn.send({"verdict": DENY, "reason": f"server error: {type(e).__name__}: {e}"})

    conn.close()


class GateProxy:
    """Agent-side proxy for an isolated gate (ISO-2).

    Implements the same decide() interface as GovernedDecisionGate but forwards
    requests over IPC. The agent process holds NO gate logic, NO self_model, and
    NO shell reference. __slots__ prevents attribute injection.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def decide(self, request: ActionRequest, shell_view: Any = None,
               llm_reliability: Optional[float] = None) -> GateDecision:
        msg = {
            "action": request.action,
            "risk_tier": request.risk_tier,
            "confidence": request.confidence,
            "verified": request.verified,
            "evidence_count": request.evidence_count,
            "approved": request.approved,
            "action_index": request.action_index,
            "llm_reliability": llm_reliability,
        }
        self._conn.send(msg)
        resp = self._conn.recv()
        return GateDecision(verdict=resp["verdict"], reason=resp["reason"])

    def read_forbidden(self) -> frozenset[int]:
        self._conn.send("READ_FORBIDDEN")
        resp = self._conn.recv()
        return frozenset(resp.get("forbidden", []))

    def shutdown(self) -> None:
        try:
            self._conn.send("SHUTDOWN")
        except (OSError, BrokenPipeError):
            pass


@dataclass
class IsolatedGate:
    """Handle returned by launch_isolated_gate(). Holds proxy + process for lifecycle."""
    proxy: GateProxy
    process: mp.Process

    def shutdown(self) -> None:
        self.proxy.shutdown()
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.terminate()


def launch_isolated_gate(
    self_model: AgentSelfModel,
    shell: Any,
    src_path: Optional[str] = None,
    timeout: float = 10.0,
) -> IsolatedGate:
    """Launch a GovernedDecisionGate in a subprocess and return an IsolatedGate handle.

    Args:
        self_model: The AgentSelfModel for the gate (lives in server process only).
        shell: The CorrigibilityShell (lives in server process only).
        src_path: Path to add to sys.path in the subprocess. Defaults to aac package location.
        timeout: Startup timeout.

    Returns:
        IsolatedGate with .proxy (duck-typed as GovernedDecisionGate) and .process.
    """
    if src_path is None:
        import aac
        src_path = str(__import__("pathlib").Path(aac.__file__).parent.parent)

    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()

    gate = GovernedDecisionGate(self_model=self_model)
    proc = ctx.Process(
        target=_gate_server_loop,
        args=(child_conn, gate, shell, src_path),
        daemon=True,
    )
    proc.start()

    proxy = GateProxy(parent_conn)
    return IsolatedGate(proxy=proxy, process=proc)
