"""E2E: a real run produces EvidenceChain with semantic lineage populated.

Proves the data->semantic->logic->action lineage is real in a live run path:
the TrustedLoopRuntime builds an EvidenceChain that carries the semantic
objects and relation links from the domain-pack graph (Palantir dynamic
lineage gap, now closed end-to-end).
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class E2ESemanticLineageInEvidenceTest(unittest.TestCase):
    def test_run_evidence_carries_semantic_refs(self) -> None:
        import sys

        for seg in (
            "packages/contracts/src",
            "packages/os_core/src",
            "packages/persistence/src",
            "packages/sdk/src",
            "action_connectors",
            "apps/api_server/src",
        ):
            sys.path.insert(0, str(ROOT / seg))
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        cfg = RuntimeFactoryConfig(domain_pack_path=ROOT / "domain_packs" / "content_commerce")
        factory = ContentCommerceRuntimeFactory(cfg)
        runtime = factory.build()
        result = runtime.run(
            "最近7天GMV是多少？",
            {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
        )
        ev = result.evidence_chain
        # the evidence now carries semantic object refs from the domain graph
        obj_ids = {ref.object_id for ref in ev.semantic_object_refs}
        # GMV-related objects (campaign tracks spend/roi; product+order track gmv)
        self.assertIn("obj-product", obj_ids)
        self.assertIn("obj-order", obj_ids)
        # and at least one relation link
        self.assertGreaterEqual(len(ev.semantic_lineage), 1)


if __name__ == "__main__":
    unittest.main()
