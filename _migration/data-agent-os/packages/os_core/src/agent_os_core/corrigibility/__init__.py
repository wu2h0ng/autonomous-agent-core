"""Corrigibility shell — operator sovereignty + tamper-evident audit (P5.2, ADR-0001).

Pattern transfer (not code copy) of the prototype's CorrigibilityShell / ShellView /
AuditLog (``autonomous-agent-core``). The operator holds the :class:`CorrigibilityShell`
(the only ``op_*`` surface); the runtime is handed a read-only :class:`ShellView`, so it
can observe and read ``paused`` but can never pause/resume itself or edit the audit.

In a real deployment ``op_*`` sit behind infrastructure/account-level auth the runtime
process cannot reach; here the separation is enforced by the capability view + guard tests
(mirrors the P5.1a adoption-channel discipline).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = ["AuditEntry", "AuditLog", "CorrigibilityShell", "ShellView"]

_GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str


class AuditLog:
    """Append-only, hash-chained audit.

    Each entry's hash covers ``(seq, payload, prev_hash)``, so any in-place edit or
    reorder breaks :meth:`verify`. Tamper-EVIDENT, not tamper-proof: an attacker who
    rewrites the whole list can re-chain it; the chain makes silent point edits
    detectable, which is the operator-observability guarantee (C7 observe pillar).
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @staticmethod
    def _hash(seq: int, payload: dict[str, Any], prev_hash: str) -> str:
        blob = json.dumps(
            {"seq": seq, "payload": payload, "prev_hash": prev_hash},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def append(self, payload: dict[str, Any]) -> AuditEntry:
        seq = len(self._entries)
        prev_hash = self._entries[-1].entry_hash if self._entries else _GENESIS
        snapshot = dict(payload)
        entry = AuditEntry(seq, snapshot, prev_hash, self._hash(seq, snapshot, prev_hash))
        self._entries.append(entry)
        return entry

    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def verify(self) -> bool:
        """Recompute the chain; True iff every link is intact and in order."""
        prev = _GENESIS
        for i, entry in enumerate(self._entries):
            if entry.seq != i or entry.prev_hash != prev:
                return False
            if entry.entry_hash != self._hash(entry.seq, entry.payload, entry.prev_hash):
                return False
            prev = entry.entry_hash
        return True


class ShellView:
    """Runtime-held capability view: read-only ``paused`` + ``observe``, NO ``op_*``.

    ``__slots__`` blocks the runtime from even setting a stray ``_paused``; it holds no
    writable reference to the shell's pause state or audit. The operator keeps the
    :class:`CorrigibilityShell`; the runtime receives only this view.
    """

    __slots__ = ("_paused_getter", "_observe")

    def __init__(
        self,
        *,
        paused_getter: Callable[[], bool],
        observe: Callable[[dict[str, Any]], Any],
    ) -> None:
        self._paused_getter = paused_getter
        self._observe = observe

    @property
    def paused(self) -> bool:
        return bool(self._paused_getter())

    def observe(self, payload: dict[str, Any]) -> None:
        self._observe(payload)


class CorrigibilityShell:
    """Operator sovereignty face: ``op_pause`` / ``op_resume`` + ``observe``.

    Owns the hash-chained :class:`AuditLog`. Hands the runtime only a read-only
    :class:`ShellView` via :meth:`view`, so the runtime cannot reach any ``op_*``.
    """

    def __init__(self) -> None:
        self.audit = AuditLog()
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    def observe(self, payload: dict[str, Any]) -> None:
        self.audit.append(payload)

    # --- operator-facing sovereignty (P5.2a: pause pillar) ---
    def op_pause(self) -> None:
        self._paused = True
        self.audit.append({"event": "pause"})

    def op_resume(self) -> None:
        self._paused = False
        self.audit.append({"event": "resume"})

    def view(self) -> ShellView:
        """The runtime-facing capability view (no ``op_*``)."""
        return ShellView(paused_getter=lambda: self._paused, observe=self.observe)
