"""Data-domain metric contracts (extracted from the donor `trusted_loop` contracts).

These are Data Agent domain semantics (metric definitions, SQL templates, quality expectations,
business-action candidates) and therefore live in the domain pack, never in Agent Core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class QualityContract:
    """Quality expectations for a MetricContract."""

    freshness: str | None = None
    null_rate: str | None = None
    owner: str | None = None


@dataclass(frozen=True)
class ActionCandidate:
    """A business action that may be proposed when a metric pattern is observed."""

    action_id: str
    trigger: str | None = None
    risk_level: RiskLevel = RiskLevel.R2
    description: str = ""


@dataclass(frozen=True)
class SQLTemplate:
    template_id: str
    metric_name: str
    sql: str
    required_parameters: tuple[str, ...] = field(default_factory=tuple)
    required_time_parameters: tuple[str, ...] = ("start_date", "end_date")
    default_limit: int = 100
    max_limit: int = 1000
    allow_select_star: bool = False


@dataclass(frozen=True)
class MetricContract:
    metric_name: str
    display_name: str
    definition: str
    owner: str
    unit: str
    allowed_schemas: tuple[str, ...]
    version: str = "v1"
    dimensions: tuple[str, ...] = field(default_factory=tuple)
    data_classification: DataClassification = DataClassification.INTERNAL
    verified_queries: tuple[SQLTemplate, ...] = field(default_factory=tuple)
    quality_contract: QualityContract | None = None
    action_candidates: tuple[ActionCandidate, ...] = field(default_factory=tuple)
    feedback_metric: str | None = None


@dataclass(frozen=True)
class QueryPlan:
    metric_name: str
    sql: str
    parameters: dict[str, Any]
    source_template: SQLTemplate | None = None


@dataclass(frozen=True)
class QueryResult:
    rows: tuple[dict[str, Any], ...]
    row_count: int
    # Actual recency of the underlying data at query time (seconds). ``None`` = the provider did
    # not report freshness, so the evidence chain caps and flags confidence rather than assuming it.
    source_age_seconds: float | None = None
