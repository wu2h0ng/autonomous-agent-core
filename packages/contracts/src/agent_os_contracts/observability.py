from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TelemetryDimension(StrEnum):
    BUSINESS = "business"
    QUALITY = "quality"
    COST = "cost"
    SYSTEM = "system"


@dataclass(frozen=True)
class TelemetryEvent:
    trace_id: str
    dimension: TelemetryDimension
    name: str
    value: float
    unit: str
    attributes: dict[str, Any] = field(default_factory=dict)
