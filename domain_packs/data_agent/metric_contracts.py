"""Stable import surface for the Data Agent metric/query contracts.

The contract dataclasses now live in :mod:`domain_contracts` (the full domain port). This module
re-exports the metric/query subset so the loader and query runtime keep a stable import path.
"""

from __future__ import annotations

from .domain_contracts import (
    ActionCandidate,
    DataClassification,
    MetricContract,
    QualityContract,
    QueryPlan,
    QueryResult,
    RiskLevel,
    SQLTemplate,
)

__all__ = [
    "ActionCandidate",
    "DataClassification",
    "MetricContract",
    "QualityContract",
    "QueryPlan",
    "QueryResult",
    "RiskLevel",
    "SQLTemplate",
]
