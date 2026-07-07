"""EvidenceChain references semantic-graph objects + lineage (Palantir dynamic lineage).

The EvidenceChain should carry the semantic objects and the relation path it
traversed, so the full lineage data→semantic→logic→action is auditable in a
single record. Default (no refs) is backward compatible.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    EvidenceChain,
    EvidenceObjectLinkRef,
    EvidenceSemanticObjectRef,
)


def _minimal_evidence(**kw) -> EvidenceChain:
    from agent_os_contracts import (
        BusinessIntent,
        MetricContract,
        QueryPlan,
        QueryResult,
        SQLSafetyResult,
    )

    base = dict(
        evidence_chain_id="ev-1",
        intent=BusinessIntent(intent_id="i", question="q", metric_name="gmv", tenant_id="t"),
        metric_contract=MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="d",
            owner="o",
            unit="CNY",
            allowed_schemas=("s",),
        ),
        query_plan=QueryPlan(
            metric_name="gmv", sql="select 1", parameters={}, source_template=None
        ),
        sql_safety=SQLSafetyResult(allowed=True, reasons=(), checked_schemas=()),
        query_result=QueryResult(rows=(), row_count=0),
        conclusion="GMV is 100",
        confidence=0.9,
        limitations=(),
        trace_id="trace-1",
    )
    base.update(kw)
    return EvidenceChain(**base)


class EvidenceSemanticLineageTest(unittest.TestCase):
    def test_evidence_carries_semantic_object_refs(self) -> None:
        ev = _minimal_evidence(
            semantic_object_refs=(
                EvidenceSemanticObjectRef(
                    object_id="obj-campaign", object_type="campaign", name="campaign"
                ),
                EvidenceSemanticObjectRef(
                    object_id="obj-product", object_type="product", name="product"
                ),
            )
        )
        self.assertEqual(len(ev.semantic_object_refs), 2)
        self.assertEqual(ev.semantic_object_refs[0].object_type, "campaign")

    def test_evidence_carries_semantic_lineage_path(self) -> None:
        ev = _minimal_evidence(
            semantic_lineage=(
                EvidenceObjectLinkRef(
                    link_id="l1",
                    link_type_id="lt-campaign-product",
                    source_object_id="obj-campaign",
                    target_object_id="obj-product",
                ),
                EvidenceObjectLinkRef(
                    link_id="l2",
                    link_type_id="lt-product-order",
                    source_object_id="obj-product",
                    target_object_id="obj-order",
                ),
            )
        )
        self.assertEqual(len(ev.semantic_lineage), 2)

    def test_evidence_without_refs_backward_compatible(self) -> None:
        ev = _minimal_evidence()
        self.assertEqual(ev.semantic_object_refs, ())
        self.assertEqual(ev.semantic_lineage, ())


if __name__ == "__main__":
    unittest.main()
