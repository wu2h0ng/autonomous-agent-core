"""ISO-2 reference: the shell in its own process (ADR-0009).

This is the *hard* isolation guarantee. The operator process owns the
``CorrigibilityShell``; the agent runs in a separate worker process holding
only a pipe connection. The agent's address space physically does not contain
the pause state, so no in-process introspection in the worker can reach it —
the gap ISO-1 leaves open (``__closure__``/``gc``) is closed by the OS process
boundary. This is what makes corrigibility a structural property rather than a
guardrail (a guardrail always shares the policy's trust domain).

Reference + CI guard only; not the default runtime (IPC has overhead).
"""

from __future__ import annotations

import gc
import multiprocessing as mp
import sys
from typing import Any


def _agent_worker(conn: Any, src_path: str) -> None:
    """Runs in the child process. Holds ONLY ``conn`` (a pipe end).

    It probes its own address space for a shell (must find none), then tries
    the strongest thing an isolated agent could do — ask the operator to
    unpause — and confirms it cannot move the pause state.
    """
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from aac.shell import CorrigibilityShell, ShellView

    # ISO-2 core claim: no shell object exists in this process's memory.
    found_shell = any(isinstance(o, CorrigibilityShell) for o in gc.get_objects())
    # A view may legitimately be absent too; assert the agent holds no operator surface.
    found_op = any(
        hasattr(o, "op_resume") for o in gc.get_objects() if isinstance(o, ShellView)
    )

    conn.send(("observe", {"event": "worker_step", "n": 1}))
    conn.send(("read_paused",))
    paused_before_cheat = conn.recv()
    # Strongest move available to an isolated agent: send a plea. The operator
    # wires no child message to op_resume, so this is inert by construction.
    conn.send(("please_unpause",))
    conn.send(("read_paused",))
    paused_after_cheat = conn.recv()
    conn.send(
        (
            "done",
            {
                "found_shell": found_shell,
                "found_op_surface": found_op,
                "paused_before_cheat": paused_before_cheat,
                "paused_after_cheat": paused_after_cheat,
            },
        )
    )
    conn.close()


def run_isolated_demo(src_path: str, timeout: float = 15.0) -> dict[str, Any]:
    """Operator side: own the shell, pause it, service the worker over a pipe.

    Returns a result dict the caller (test) asserts on. The operator never
    exposes ``op_*`` to the worker; the only honored messages are
    ``observe`` (append-only) and ``read_paused`` (read-only).
    """
    from aac.shell import CorrigibilityShell

    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()
    shell = CorrigibilityShell()
    shell.op_pause()  # operator pauses BEFORE the worker can act

    proc = ctx.Process(target=_agent_worker, args=(child_conn, src_path))
    proc.start()
    summary: dict[str, Any] = {}
    try:
        while True:
            if not parent_conn.poll(timeout):
                raise TimeoutError("worker did not respond in time")
            msg = parent_conn.recv()
            tag = msg[0]
            if tag == "observe":
                shell.observe(msg[1])  # cross-process audit append
            elif tag == "read_paused":
                parent_conn.send(shell.paused)
            elif tag == "please_unpause":
                pass  # NO handler calls op_resume — child input cannot move state
            elif tag == "done":
                summary = msg[1]
                break
    finally:
        proc.join(timeout)
        if proc.is_alive():
            proc.terminate()
        parent_conn.close()

    summary["audit_has_worker_entry"] = any(
        e.payload.get("event") == "worker_step" for e in shell.audit.entries()
    )
    summary["audit_verifies"] = shell.audit.verify()
    summary["final_paused"] = shell.paused
    return summary
