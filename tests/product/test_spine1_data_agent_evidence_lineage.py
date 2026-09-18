"""SPINE-1: Data Agent evidence lineage — typed completeness, recency-tau parsing, and
semantic lineage (monorepo-native re-implementation of the donor EvidenceChain semantics).

De-duplicated against tests/product/test_spine1_data_agent_evidence.py (which covers the
confidence-derivation rule). This file covers what that one does not: recency-bound parsing,
typed evidence completeness, and self-contained semantic lineage collection.

Each test would FAIL if the corresponding logic were constant/ignored.
"""

from __future__ import annotations

from domain_packs.data_agent.evidence import (
    SemanticLink,
    SemanticObject,
    assess_evidence_completeness,
    derive_data_confidence,
    parse_freshness_to_seconds,
    semantic_lineage_for_metric,
)


# --- recency bound (tau) parsing -----------------------------------------------------


def test_parses_common_duration_forms() -> None:
    assert parse_freshness_to_seconds("24h") == 86400.0
    assert parse_freshness_to_seconds("7d") == 7 * 86400.0
    assert parse_freshness_to_seconds("30m") == 1800.0
    assert parse_freshness_to_seconds("45s") == 45.0
    assert parse_freshness_to_seconds("2w") == 2 * 604800.0
    assert parse_freshness_to_seconds("120") == 120.0


def test_parses_cadence_words() -> None:
    assert parse_freshness_to_seconds("daily") == 86400.0
    assert parse_freshness_to_seconds("Hourly") == 3600.0
    assert parse_freshness_to_seconds("monthly") == 2592000.0


def test_unknown_or_missing_returns_none() -> None:
    assert parse_freshness_to_seconds(None) is None
    assert parse_freshness_to_seconds("") is None
    assert parse_freshness_to_seconds("   ") is None
    assert parse_freshness_to_seconds("occasionally") is None
    assert parse_freshness_to_seconds("-5h") is None


def test_parsed_tau_drives_the_confidence_cap() -> None:
    tau = parse_freshness_to_seconds("24h")
    fresh = derive_data_confidence(
        row_count=10,
        source_age_seconds=60.0,
        freshness_tau_seconds=tau,
        template_verified=True,
    )
    stale = derive_data_confidence(
        row_count=10,
        source_age_seconds=tau * 4,
        freshness_tau_seconds=tau,
        template_verified=True,
    )

    assert "tau_inconsistency" in stale.flags
    assert stale.score < fresh.score


# --- typed evidence completeness -----------------------------------------------------


def test_missing_claims_is_named_incomplete() -> None:
    result = assess_evidence_completeness(claims=(), metric_refs=("gmv:v1",))
    assert result.complete is False
    assert "claims" in result.missing


def test_missing_metric_ref_is_named_incomplete() -> None:
    result = assess_evidence_completeness(claims=("GMV returned 5 rows",), metric_refs=())
    assert result.complete is False
    assert "metric_refs" in result.missing


def test_complete_metric_evidence_needs_no_provider() -> None:
    result = assess_evidence_completeness(
        claims=("GMV returned 5 rows",), metric_refs=("gmv:v1",)
    )
    assert result.complete is True
    assert result.missing == ()


def test_provider_ref_is_recorded_not_required() -> None:
    with_provider = assess_evidence_completeness(
        claims=("GMV returned 5 rows",),
        metric_refs=("gmv:v1",),
        provider_refs=("pg",),
    )
    without_provider = assess_evidence_completeness(
        claims=("GMV returned 5 rows",), metric_refs=("gmv:v1",)
    )
    assert with_provider.complete is True
    assert without_provider.complete is True


# --- semantic lineage ----------------------------------------------------------------


_OBJECTS = (
    SemanticObject(object_id="obj:gmv", object_type="metric", name="GMV", related_metrics=("gmv",)),
    SemanticObject(object_id="obj:channel", object_type="dimension", name="channel", related_metrics=("gmv", "roi")),
    SemanticObject(object_id="obj:roi", object_type="metric", name="ROI", related_metrics=("roi",)),
)


def test_lineage_collects_only_objects_related_to_the_metric() -> None:
    objects, links = semantic_lineage_for_metric("gmv", objects=_OBJECTS, links=())

    assert {ref.object_id for ref in objects} == {"obj:gmv", "obj:channel"}
    assert "obj:roi" not in {ref.object_id for ref in objects}
    assert links == ()


def test_lineage_keeps_only_links_between_collected_objects() -> None:
    links = (
        SemanticLink(link_id="link:in", link_type_id="uses", source_object_id="obj:gmv", target_object_id="obj:channel"),
        SemanticLink(link_id="link:out", link_type_id="uses", source_object_id="obj:roi", target_object_id="obj:channel"),
    )

    objects, kept = semantic_lineage_for_metric("gmv", objects=_OBJECTS, links=links)

    assert {ref.link_id for ref in kept} == {"link:in"}
    collected = {ref.object_id for ref in objects}
    for ref in kept:
        assert ref.source_object_id in collected
        assert ref.target_object_id in collected


def test_lineage_is_empty_for_an_unrelated_metric() -> None:
    objects, links = semantic_lineage_for_metric("never_seen", objects=_OBJECTS, links=())

    assert objects == ()
    assert links == ()
