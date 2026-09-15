from __future__ import annotations

from dataclasses import dataclass

_DURATION_UNIT_SECONDS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0, "w": 604800.0}
_DURATION_CADENCE_WORDS = {
    "hourly": 3600.0,
    "daily": 86400.0,
    "weekly": 604800.0,
    "monthly": 2592000.0,
}


def parse_freshness_to_seconds(text: str | None) -> float | None:
    """Parse a stated recency bound (tau) into seconds.

    Accepts ``<number><unit>`` (unit s/m/h/d/w), a bare number (seconds), or a cadence word
    (hourly/daily/weekly/monthly). Returns None when missing or unrecognized, so the caller
    records "tau unspecified" rather than guessing a bound.
    """
    if not text:
        return None
    token = text.strip().lower()
    if not token:
        return None
    if token in _DURATION_CADENCE_WORDS:
        return _DURATION_CADENCE_WORDS[token]
    try:
        value = float(token)
    except ValueError:
        value = None
    if value is not None:
        return value if value >= 0 else None
    unit = token[-1]
    if unit in _DURATION_UNIT_SECONDS:
        try:
            magnitude = float(token[:-1])
        except ValueError:
            return None
        if magnitude < 0:
            return None
        return magnitude * _DURATION_UNIT_SECONDS[unit]
    return None


@dataclass(frozen=True)
class DataConfidenceDerivation:
    score: float
    flags: tuple[str, ...]


def derive_data_confidence(
    *,
    row_count: int,
    source_age_seconds: float | None = None,
    freshness_tau_seconds: float | None = None,
    template_verified: bool = False,
) -> DataConfidenceDerivation:
    """Derive bounded confidence without treating missing evidence as positive."""
    flags: list[str] = []
    freshness_factor = 1.0
    cap = 0.97
    if source_age_seconds is None:
        freshness_factor = 0.60
        cap = min(cap, 0.60)
        flags.append("freshness_unknown")
    elif (
        freshness_tau_seconds is not None
        and source_age_seconds > freshness_tau_seconds * 1.10
    ):
        freshness_factor = max(
            0.30,
            freshness_tau_seconds / source_age_seconds,
        )
        cap = min(cap, 0.50)
        flags.extend(("stale", "tau_inconsistency"))

    template_factor = 1.0
    if not template_verified:
        template_factor = 0.60
        cap = min(cap, 0.55)
        flags.append("unverified_template")

    if row_count <= 0:
        row_factor = 0.0
        flags.append("no_rows")
    else:
        row_factor = 0.60 + 0.40 * (min(row_count, 10) / 10)
        if row_count < 10:
            flags.append("low_row_count")

    score = 0.95 * freshness_factor * row_factor * template_factor
    if row_count <= 0:
        score = max(score, 0.30)
    else:
        score = max(score, 0.05)
    return DataConfidenceDerivation(
        score=round(min(score, cap), 6),
        flags=tuple(flags),
    )


@dataclass(frozen=True)
class SemanticObject:
    """A domain semantic object that can be cited in evidence lineage."""

    object_id: str
    object_type: str
    name: str
    related_metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticLink:
    """A relationship between two semantic objects."""

    link_id: str
    link_type_id: str
    source_object_id: str
    target_object_id: str


@dataclass(frozen=True)
class SemanticObjectRef:
    object_id: str
    object_type: str
    name: str


@dataclass(frozen=True)
class SemanticLinkRef:
    link_id: str
    link_type_id: str
    source_object_id: str
    target_object_id: str


def semantic_lineage_for_metric(
    metric_name: str,
    *,
    objects: tuple[SemanticObject, ...],
    links: tuple[SemanticLink, ...],
) -> tuple[tuple[SemanticObjectRef, ...], tuple[SemanticLinkRef, ...]]:
    """Collect the semantic objects related to ``metric_name`` and the links between them.

    Only links whose BOTH endpoints are collected objects are kept, so the returned path
    never references an object outside the cited set — the lineage is self-contained and
    auditable. Objects that do not list the metric are excluded.
    """
    related = tuple(obj for obj in objects if metric_name in obj.related_metrics)
    related_ids = {obj.object_id for obj in related}
    object_refs = tuple(
        SemanticObjectRef(object_id=obj.object_id, object_type=obj.object_type, name=obj.name)
        for obj in related
    )
    link_refs = tuple(
        SemanticLinkRef(
            link_id=link.link_id,
            link_type_id=link.link_type_id,
            source_object_id=link.source_object_id,
            target_object_id=link.target_object_id,
        )
        for link in links
        if link.source_object_id in related_ids and link.target_object_id in related_ids
    )
    return object_refs, link_refs


@dataclass(frozen=True)
class EvidenceCompleteness:
    complete: bool
    missing: tuple[str, ...]

    def __post_init__(self) -> None:
        # Fail closed on an internally inconsistent value so the grounding guard cannot be fed a
        # fabricated "complete=True with missing requirements".
        if self.complete != (not self.missing):
            raise ValueError("complete must equal (missing is empty)")


def assess_evidence_completeness(
    *,
    claims: tuple[str, ...],
    metric_refs: tuple[str, ...],
    provider_refs: tuple[str, ...] = (),
) -> EvidenceCompleteness:
    """Typed-completeness gate for a Data Agent evidence chain.

    A metric-backed evidence chain is complete only with at least one claim and at least one
    metric contract reference. A provider reference is optional: a metric-only answer can still
    be a complete, governed result. Missing requirements are named, never silently accepted.
    """
    missing: list[str] = []
    if not claims:
        missing.append("claims")
    if not metric_refs:
        missing.append("metric_refs")
    return EvidenceCompleteness(complete=not missing, missing=tuple(missing))
