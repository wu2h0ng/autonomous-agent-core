"""Typed FAILURE logging for LLM-driven causal discovery arms.

Separates plumbing failures from reasoning failures so that a zero score
from a truncated / timed-out / unparseable response is never pooled with a
clean wrong answer. All events are immutable and serializable.

Pure stdlib.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Optional, TextIO


class FailureKind(str, Enum):
    """Categories of failure that must be logged separately."""

    CLEAN_WRONG = "clean_wrong"
    TRUNCATED = "truncated"
    TIMEOUT = "timeout"
    UNPARSEABLE = "unparseable"


@dataclass(frozen=True)
class PlumbingEvent:
    """A single typed plumbing event."""

    run_id: str
    arm: str
    kind: str
    step: str
    message: str
    timestamp_ns: int
    context: dict[str, Any]


class PlumbingInstrument:
    """Collector for typed failure events during an experimental run.

    Guarantees:
      - Each failure kind is counted independently.
      - A plumbing-zero (truncated/timeout/unparseable) is never added to a
        reasoning-zero (clean-wrong) bucket.
      - Events can be flushed to JSON lines for downstream adjudication.
    """

    def __init__(self, run_id: Optional[str] = None, arm: str = "unknown") -> None:
        self.run_id = run_id or uuid.uuid4().hex
        self.arm = arm
        self._events: list[PlumbingEvent] = []

    def _emit(
        self,
        kind: FailureKind,
        step: str,
        message: str,
        context: Optional[dict[str, Any]] = None,
    ) -> PlumbingEvent:
        event = PlumbingEvent(
            run_id=self.run_id,
            arm=self.arm,
            kind=kind.value,
            step=step,
            message=message,
            timestamp_ns=time.time_ns(),
            context=context or {},
        )
        self._events.append(event)
        return event

    def log_clean_wrong(
        self, step: str, message: str, context: Optional[dict[str, Any]] = None
    ) -> PlumbingEvent:
        """Model produced a parseable, complete answer that is incorrect."""
        return self._emit(FailureKind.CLEAN_WRONG, step, message, context)

    def log_truncated(
        self, step: str, message: str, context: Optional[dict[str, Any]] = None
    ) -> PlumbingEvent:
        """Model output was cut off before a usable structure could be parsed."""
        return self._emit(FailureKind.TRUNCATED, step, message, context)

    def log_timeout(
        self, step: str, message: str, context: Optional[dict[str, Any]] = None
    ) -> PlumbingEvent:
        """Model call exceeded its time budget."""
        return self._emit(FailureKind.TIMEOUT, step, message, context)

    def log_unparseable(
        self, step: str, message: str, context: Optional[dict[str, Any]] = None
    ) -> PlumbingEvent:
        """Model output could not be parsed into the required schema."""
        return self._emit(FailureKind.UNPARSEABLE, step, message, context)

    @property
    def events(self) -> list[PlumbingEvent]:
        """All recorded events, in order."""
        return list(self._events)

    def counts(self) -> dict[str, int]:
        """Independent counts per failure kind."""
        counts: dict[str, int] = {kind.value: 0 for kind in FailureKind}
        for event in self._events:
            counts[event.kind] = counts.get(event.kind, 0) + 1
        return counts

    def has_plumbing_failure(self) -> bool:
        """True if any event is a plumbing failure (not clean-wrong)."""
        plumbing_kinds = {
            FailureKind.TRUNCATED.value,
            FailureKind.TIMEOUT.value,
            FailureKind.UNPARSEABLE.value,
        }
        return any(event.kind in plumbing_kinds for event in self._events)

    def reasoning_wrong_count(self) -> int:
        """Number of clean-wrong events only."""
        return sum(
            1 for event in self._events if event.kind == FailureKind.CLEAN_WRONG.value
        )

    def to_jsonl(self, stream: TextIO = sys.stdout) -> None:
        """Flush all events as JSON lines."""
        for event in self._events:
            stream.write(json.dumps(asdict(event), sort_keys=True) + "\n")

    def dump(self, path: str) -> None:
        """Append all events to a JSON lines file."""
        with open(path, "a", encoding="utf-8") as fh:
            self.to_jsonl(fh)


def split_score(
    reasoning_score: float, instrument: PlumbingInstrument
) -> dict[str, float]:
    """Return separated reasoning and plumbing scores.

    If any plumbing failure occurred, the plumbing score is reported
    independently and must not be averaged into the reasoning score.
    """
    if instrument.has_plumbing_failure():
        return {"reasoning": reasoning_score, "plumbing": 0.0, "pooled": float("nan")}
    return {"reasoning": reasoning_score, "plumbing": 0.0, "pooled": reasoning_score}


if __name__ == "__main__":
    instr = PlumbingInstrument(run_id="smoke", arm="organ_tools")
    instr.log_clean_wrong(
        "propose_edge", "selected edge absent from held-out truth", {"edge": (0, 1)}
    )
    instr.log_truncated("propose_edge", "response ended mid-JSON")
    instr.log_timeout("propose_edge", "exceeded 30s budget", {"budget_seconds": 30})
    instr.log_unparseable("propose_edge", "JSON decode error at line 1")

    print("counts:", instr.counts())
    print("has_plumbing_failure:", instr.has_plumbing_failure())
    print("reasoning_wrong_count:", instr.reasoning_wrong_count())
    print("split_score:", split_score(0.25, instr))
    instr.to_jsonl()
