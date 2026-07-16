"""Observation contract for the interactive R-STATE-CREDIT-1 environment."""

from __future__ import annotations

import json
from dataclasses import dataclass, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


@dataclass(frozen=True, slots=True)
class Observation:
    """A single bounded observation released to the actor on one turn.

    All fields are frozen.  Byte budgets are measured on the canonical JSON
    serialization produced by :meth:`canonical_json`.
    """

    turn_index: int
    event_class: str
    payload: dict[str, Any]
    valid_time: datetime
    observed_at_turn: int

    def __post_init__(self) -> None:
        if not isinstance(self.turn_index, int) or isinstance(self.turn_index, bool):
            raise ValueError("turn_index must be an integer")
        if not isinstance(self.event_class, str) or not self.event_class:
            raise ValueError("event_class must be non-empty text")
        if not isinstance(self.payload, dict):
            raise ValueError("payload must be a mapping")
        if not isinstance(self.valid_time, datetime):
            raise ValueError("valid_time must be a datetime")
        if not isinstance(self.observed_at_turn, int) or isinstance(
            self.observed_at_turn, bool
        ):
            raise ValueError("observed_at_turn must be an integer")

    def canonical_json(self) -> str:
        """Return deterministic compact JSON for budget measurement.

        The actor-facing serialization deliberately excludes runner-internal
        sequencing fields ``turn_index`` and ``observed_at_turn``.
        """
        mapping = {
            field.name: getattr(self, field.name)
            for field in self.__dataclass_fields__.values()
            if field.name not in {"turn_index", "observed_at_turn"}
        }
        return _canonical_json(mapping)

    def serialized_bytes(self) -> int:
        """Return UTF-8 byte length of the canonical JSON serialization."""
        return len(self.canonical_json().encode("utf-8"))


def _canonical_value(value: Any) -> Any:
    """Recursively convert values to JSON-serializable canonical forms."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if is_dataclass(value):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in value.__dataclass_fields__.values()
        }
    return value


def _canonical_json(value: Any) -> str:
    """Compact, sorted, deterministic JSON."""
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
