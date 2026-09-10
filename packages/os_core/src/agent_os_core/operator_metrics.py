"""Operator-side HCW metrics event log (HCW-METRICS-0).

Append-only JSONL log of operator actions with a sha256 hash chain, consumed by
the external deterministic aggregator at ``tools/hcw/aggregate.py``. This is an
observability sidecar: it measures the *operator's* work, never the system's
reasoning, and it must never break the governed product path.

Schema contract: ``docs/HCW-METRICS-GOAL-CARD.md`` §3.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

OPERATOR_EVENT_TYPES = frozenset(
    {
        "prompt_sent",
        "correction",
        "approval_action",
        "help_response",
        "intervention",
        "session_switch",
        "review_window",
        "outcome_verdict",
    }
)

_GENESIS = "0" * 64


def _canonical(ev: dict) -> bytes:
    return json.dumps(ev, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _event_hash(ev: dict) -> str:
    """sha256 over the event payload including prev_hash (chain link)."""
    return hashlib.sha256(_canonical(ev)).hexdigest()


class OperatorEventLog:
    """Append-only operator event writer with hash-chain integrity.

    Fail-open by design: a logging failure warns on stderr but never aborts the
    operator's actual work. Integrity failures are detectable after the fact via
    :func:`verify_operator_event_log`.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = RLock()
        self._last_ts: datetime | None = None
        self._prev_hash = self._read_tail_hash()

    @property
    def path(self) -> Path:
        return self._path

    def _read_tail_hash(self) -> str:
        if not self._path.exists():
            return _GENESIS
        try:
            lines = [
                line
                for line in self._path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if not lines:
                return _GENESIS
            tail = json.loads(lines[-1])
            return str(tail.get("hash") or _GENESIS)
        except (OSError, ValueError):
            return _GENESIS

    def append(self, event_type: str, task_id: str | None = None, **fields: object) -> None:
        if event_type not in OPERATOR_EVENT_TYPES:
            raise ValueError(f"unknown operator event type: {event_type!r}")
        with self._lock:
            now = datetime.now(timezone.utc)
            if self._last_ts is not None and now < self._last_ts:
                now = self._last_ts  # monotonic guard
            self._last_ts = now
            ev: dict[str, object] = {
                "v": 1,
                "ts": now.isoformat(),
                "type": event_type,
                "actor": os.environ.get("AGENT_OS_OPERATOR", "user:local"),
                "prev_hash": self._prev_hash,
            }
            if task_id is not None:
                ev["task_id"] = task_id
            ev.update(fields)
            ev["hash"] = _event_hash(ev)
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(ev, sort_keys=True) + "\n")
            except OSError as exc:  # fail-open sidecar
                print(f"[operator-metrics] write failed: {exc}", file=sys.stderr)
                return
            self._prev_hash = str(ev["hash"])


def verify_operator_event_log(path: Path | str) -> bool:
    """Recompute the hash chain; False on any tampering or truncation."""
    path = Path(path)
    if not path.exists():
        return False
    prev = _GENESIS
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            recorded = ev.pop("hash", None)
            if ev.get("prev_hash") != prev or not recorded:
                return False
            if _event_hash(ev) != recorded:
                return False
            prev = recorded
    except (OSError, ValueError):
        return False
    return True
