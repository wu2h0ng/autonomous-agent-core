"""Typed contracts for proposal-only domain pack synthesis.

These types carry a read-only schema inventory and the candidate metrics
proposed from it.  A proposal is data for a human decision: nothing here
grants schema access or activates anything in the runtime.  Secrets are
never part of a proposal; only environment-variable references are.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnInventory:
    """One column observed through read-only introspection."""

    name: str
    data_type: str


@dataclass(frozen=True)
class TableInventory:
    schema: str
    table: str
    columns: tuple[ColumnInventory, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SchemaInventory:
    """The observed, non-secret projection of a warehouse's structure."""

    tables: tuple[TableInventory, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PackCandidateMetric:
    """A deterministic candidate for a MetricContract + SQLTemplate pair.

    ``sql`` is generated from a fixed SELECT-only shape and must have passed
    the SQLSafetyChecker self-check with the proposed schemas before a
    candidate of this type is ever handed to a reviewer.
    """

    metric_name: str
    template_id: str
    display_name: str
    definition: str
    unit: str
    source_schema: str
    source_table: str
    aggregation_column: str
    time_column: str
    dimensions: tuple[str, ...]
    sql_dialect: str
    sql: str
    rationale: str


@dataclass(frozen=True)
class PackProposal:
    """A reviewable, secret-free proposal file payload.

    ``status`` is PROPOSED at write time; approval happens only when an
    operator explicitly names metrics in the materialization step.
    """

    proposal_id: str
    status: str
    dialect: str
    provider_id: str
    provider_name: str
    owner: str
    allowed_schemas: tuple[str, ...]
    inventory_sha256: str
    candidates: tuple[PackCandidateMetric, ...]
