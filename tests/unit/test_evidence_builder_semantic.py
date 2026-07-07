"""EvidenceChainBuilder populates semantic lineage from the registry graph.

When a SemanticRegistry with a graph is available, the EvidenceChain carries
the graph's objects and relation paths so lineage data→semantic→logic→action
is auditable. Default (no registry) leaves refs empty (backward compatible).
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    BusinessIntent,
    LinkType,
    MetricContract,
    ObjectLink,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    QueryResult,
    SemanticObject,
    SQLSafetyResult,
)
from agent_os_core.evidence_chain import EvidenceChainBuilder
from agent_os_core.semantic_runtime import SemanticGraph, SemanticRegistry


def _build_inputs():
    return dict(
        evidence_chain_id="ev-1",
        intent=BusinessIntent(intent_id="i", question="q", metric_name="gmv"),
        metric_contract=MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="d",
            owner="o",
            unit="CNY",
            allowed_schemas=("s",),
        ),
        query_plan=QueryPlan(metric_name="gmv", sql="select 1", parameters={}),
        sql_safety=SQLSafetyResult(allowed=True, reasons=(), checked_schemas=()),
        query_result=QueryResult(rows=({"gmv": 100.0},), row_count=1),
        trace_id="trace-1",
        provider_contract=ProviderContract(
            provider_id="p",
            kind=ProviderKind.WAREHOUSE,
            name="s",
            owner="o",
            allowed_schemas=("s",),
        ),
    )


def _registry_with_graph() -> SemanticRegistry:
    g = SemanticGraph()
    g.register_object(
        SemanticObject(
            object_id="obj-campaign",
            name="campaign",
            object_type="campaign",
            description="c",
            owner="o",
            related_metrics=("gmv",),
        )
    )
    g.register_object(
        SemanticObject(
            object_id="obj-product",
            name="product",
            object_type="product",
            description="p",
            owner="o",
            related_metrics=("gmv",),
        )
    )
    g.register_link_type(
        LinkType(
            link_type_id="lt-cp",
            name="promotes",
            source_object_type="campaign",
            target_object_type="product",
            description="",
        )
    )
    g.register_link(
        ObjectLink(
            link_id="l1",
            link_type_id="lt-cp",
            source_object_id="obj-campaign",
            target_object_id="obj-product",
        )
    )
    return SemanticRegistry(semantic_graph=g)


class EvidenceBuilderSemanticTest(unittest.TestCase):
    def test_no_registry_leaves_refs_empty(self) -> None:
        ev = EvidenceChainBuilder().build(**_build_inputs())
        self.assertEqual(ev.semantic_object_refs, ())
        self.assertEqual(ev.semantic_lineage, ())

    def test_registry_populates_object_refs(self) -> None:
        reg = _registry_with_graph()
        ev = EvidenceChainBuilder(semantic_registry=reg).build(**_build_inputs())
        ids = {ref.object_id for ref in ev.semantic_object_refs}
        self.assertIn("obj-campaign", ids)
        self.assertIn("obj-product", ids)

    def test_registry_populates_lineage_links(self) -> None:
        reg = _registry_with_graph()
        ev = EvidenceChainBuilder(semantic_registry=reg).build(**_build_inputs())
        link_ids = {ref.link_id for ref in ev.semantic_lineage}
        self.assertIn("l1", link_ids)


if __name__ == "__main__":
    unittest.main()
