from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    index: int
    prev_hash: str
    payload: dict[str, Any]
    entry_hash: str


class AuditLog:
    """Append-only, hash-chained audit log (the 'observe' pillar of the shell).

    The agent is given only :meth:`append`; there is no edit or delete. Any
    tampering with a past entry breaks the chain, which :meth:`verify` detects.
    """

    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @staticmethod
    def _hash(index: int, prev_hash: str, payload: dict[str, Any]) -> str:
        blob = json.dumps(
            {"index": index, "prev_hash": prev_hash, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def append(self, payload: dict[str, Any]) -> AuditEntry:
        index = len(self._entries)
        prev_hash = self._entries[-1].entry_hash if self._entries else self.GENESIS
        entry_hash = self._hash(index, prev_hash, payload)
        entry = AuditEntry(
            index=index, prev_hash=prev_hash, payload=payload, entry_hash=entry_hash
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def verify(self) -> bool:
        prev = self.GENESIS
        for i, e in enumerate(self._entries):
            if e.index != i or e.prev_hash != prev:
                return False
            if self._hash(e.index, e.prev_hash, e.payload) != e.entry_hash:
                return False
            prev = e.entry_hash
        return True
