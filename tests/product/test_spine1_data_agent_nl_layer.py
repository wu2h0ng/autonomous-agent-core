"""SPINE-1: Data Agent semantic / NL layer (semantic_runtime, intent_parser, nl_query).

Ported from the donor modules; imports rewritten to pack-native contracts/aliases.
"""

from __future__ import annotations

import datetime

from domain_packs.data_agent.domain_contracts import (
    LifecycleState,
    LinkType,
    MetricContract,
    ObjectLink,
    SemanticObject,
)
from domain_packs.data_agent.intent_parser import IntentParser
from domain_packs.data_agent.nl_query import NLIntentParser, NLQueryEngine
from domain_packs.data_agent.semantic_runtime import SemanticGraph, SemanticRegistry


def _metric(name: str, display: str) -> MetricContract:
    return MetricContract(
        metric_name=name,
        display_name=display,
        definition=f"{display} definition",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )


def _object(object_id: str, name: str, object_type: str) -> SemanticObject:
    return SemanticObject(
        object_id=object_id,
        name=name,
        object_type=object_type,
        description=name,
        owner="revenue_ops",
        related_metrics=("gmv",),
        state=LifecycleState.ACTIVE,
    )


# --- SemanticGraph / SemanticRegistry ------------------------------------------------


def test_graph_registers_links_and_traverses_paths() -> None:
    graph = SemanticGraph()
    graph.register_object(_object("o:metric", "GMV", "metric"))
    graph.register_object(_object("o:dim", "channel", "dimension"))
    graph.register_link_type(
        LinkType(
            link_type_id="lt:uses",
            name="uses",
            source_object_type="metric",
            target_object_type="dimension",
        )
    )
    graph.register_link(
        ObjectLink(
            link_id="l:1", link_type_id="lt:uses", source_object_id="o:metric", target_object_id="o:dim"
        )
    )

    assert graph.resolve_object("GMV").object_id == "o:metric"
    assert len(graph.neighbors("o:metric", direction="outgoing")) == 1
    assert graph.neighbors("o:dim", direction="incoming")[0].link_id == "l:1"
    assert len(graph.paths("o:metric", "o:dim")) == 1


def test_graph_rejects_link_with_mismatched_object_types() -> None:
    graph = SemanticGraph()
    graph.register_object(_object("o:a", "A", "metric"))
    graph.register_object(_object("o:b", "B", "metric"))
    graph.register_link_type(
        LinkType(
            link_type_id="lt:uses",
            name="uses",
            source_object_type="metric",
            target_object_type="dimension",
        )
    )

    try:
        graph.register_link(
            ObjectLink(
                link_id="l:1", link_type_id="lt:uses", source_object_id="o:a", target_object_id="o:b"
            )
        )
    except ValueError as exc:
        assert "does not match link type" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a type-mismatch rejection")


def test_registry_resolves_and_searches_metrics_by_alias() -> None:
    registry = SemanticRegistry(
        semantic_objects=(_object("o:1", "GMV", "metric"),),
        metric_contracts=(_metric("gmv", "GMV"), _metric("roi", "ROI")),
    )

    assert registry.resolve_metric("gmv").display_name == "GMV"
    assert registry.try_resolve_metric("nope") is None
    assert {m.metric_name for m in registry.search_metrics("gmv")} == {"gmv"}
    assert {m.metric_name for m in registry.search_metrics(None)} == {"gmv", "roi"}
    assert registry.resolve_object("GMV").object_id == "o:1"


# --- IntentParser --------------------------------------------------------------------


def test_intent_parser_fallback_matches_metric_keywords() -> None:
    parser = IntentParser()

    assert parser.parse("GMV是多少").metric_name == "gmv"
    assert parser.parse("conversion rate please").metric_name == "conversion_rate"
    assert parser.parse("something else").metric_name == "unknown"


def test_intent_parser_llm_path_uses_injected_provider() -> None:
    class _Fake:
        def complete_structured(self, messages, output_schema):
            return {"metric_name": "roi", "question": messages[-1]["content"]}

    intent = IntentParser(_Fake()).parse("anything")

    assert intent.metric_name == "roi"


# --- NLQueryEngine -------------------------------------------------------------------


def test_nl_query_engine_parses_dimensions_time_and_metric() -> None:
    registry = SemanticRegistry(metric_contracts=(_metric("gmv", "GMV"),))
    engine = NLQueryEngine(registry)

    result = engine.query("按渠道看最近7天GMV")

    assert result.matched_metric is not None
    assert result.matched_metric.metric_name == "gmv"
    assert "channel" in result.dimensions
    assert result.chart_type in {"line", "bar"}
    assert set(result.parameters) == {"start_date", "end_date"}


def test_nl_query_engine_unknown_metric_has_zero_confidence() -> None:
    registry = SemanticRegistry(metric_contracts=(_metric("gmv", "GMV"),))
    engine = NLQueryEngine(registry)

    result = engine.query("something unrelated")

    assert result.matched_metric is None
    assert result.confidence == 0.0


def test_nl_intent_parser_returns_chart_and_time() -> None:
    intent = NLIntentParser().parse("last week revenue")

    assert intent.metric_keyword == "revenue"
    assert intent.time_range is not None
    assert isinstance(intent.time_range[0], datetime.date)
    assert intent.chart_type == "line"
