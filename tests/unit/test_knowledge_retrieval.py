from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import KnowledgeAsset, KnowledgeQuery, LifecycleState  # noqa: E402
from agent_os_core import HashingEmbedder, InMemoryKnowledgeRetriever  # noqa: E402


def _asset(
    aid: str,
    title: str,
    *,
    owner: str = "revenue_ops",
    state: LifecycleState = LifecycleState.DRAFT,
) -> KnowledgeAsset:
    return KnowledgeAsset(
        asset_id=aid,
        title=title,
        asset_type="decision_loop",
        source_trace_id=f"trace-{aid}",
        owner=owner,
        state=state,
    )


class HashingEmbedderTest(unittest.TestCase):
    def test_deterministic_and_normalized(self) -> None:
        emb = HashingEmbedder(dimensions=64)
        v1 = emb.embed("gmv gross merchandise value")
        v2 = emb.embed("gmv gross merchandise value")
        self.assertEqual(v1, v2)  # deterministic
        self.assertEqual(len(v1), 64)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v1)), 1.0, places=6)

    def test_different_text_differs_and_empty_is_zero(self) -> None:
        emb = HashingEmbedder(dimensions=64)
        self.assertNotEqual(emb.embed("ad spend"), emb.embed("conversion rate"))
        self.assertEqual(emb.embed(""), tuple([0.0] * 64))
        self.assertEqual(emb.model_id, "hashing-bow-64")


class InMemoryKnowledgeRetrieverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = InMemoryKnowledgeRetriever(HashingEmbedder(dimensions=128))

    def test_ranks_most_relevant_first(self) -> None:
        self.retriever.index(
            _asset("gmv", "gmv gross merchandise value daily", state=LifecycleState.ACTIVE)
        )
        self.retriever.index(
            _asset("spend", "ad spend marketing budget", state=LifecycleState.ACTIVE)
        )
        self.retriever.index(_asset("conv", "conversion rate funnel", state=LifecycleState.ACTIVE))

        res = self.retriever.search(KnowledgeQuery(text="ad spend marketing budget", k=3))
        self.assertEqual(res[0].asset.asset_id, "spend")
        self.assertEqual(len(res), 3)
        # explainability: every result carries the score breakdown.
        self.assertEqual(
            set(res[0].score_breakdown),
            {
                "vector",
                "lexical",
                "rrf",
                "rrf_normalized",
                "outcome_boost",
                "recency_boost",
                "total",
            },
        )

    def test_structured_filters(self) -> None:
        self.retriever.index(
            _asset("a", "same words", owner="alice", state=LifecycleState.ACTIVE),
            metric_name="gmv",
        )
        self.retriever.index(
            _asset("b", "same words", owner="bob", state=LifecycleState.ACTIVE),
            metric_name="roi",
        )
        self.retriever.index(
            _asset("c", "same words", owner="alice", state=LifecycleState.ACTIVE),
            metric_name="gmv",
        )

        by_metric = self.retriever.search(KnowledgeQuery(text="same words", metric_name="roi"))
        self.assertEqual({r.asset.asset_id for r in by_metric}, {"b"})

        by_owner = self.retriever.search(KnowledgeQuery(text="same words", owner="alice"))
        self.assertEqual({r.asset.asset_id for r in by_owner}, {"a", "c"})

        by_state = self.retriever.search(
            KnowledgeQuery(text="same words", lifecycle_state=LifecycleState.ACTIVE)
        )
        self.assertEqual({r.asset.asset_id for r in by_state}, {"a", "b", "c"})

    def test_default_search_consumes_only_reviewed_or_value_backed_assets(self) -> None:
        self.retriever.index(_asset("draft", "governed gmv lesson"))
        self.retriever.index(_asset("active", "governed gmv lesson", state=LifecycleState.ACTIVE))
        self.retriever.index(
            _asset("adopted", "governed gmv lesson"),
            outcome="adopted",
            outcome_score=1.0,
        )
        self.retriever.index(
            _asset("deprecated", "governed gmv lesson", state=LifecycleState.DEPRECATED)
        )

        default_hits = self.retriever.search(KnowledgeQuery(text="governed gmv lesson", k=10))
        self.assertEqual(
            {r.asset.asset_id for r in default_hits},
            {"active", "adopted"},
        )

        draft_hits = self.retriever.search(
            KnowledgeQuery(
                text="governed gmv lesson",
                lifecycle_state=LifecycleState.DRAFT,
                k=10,
            )
        )
        self.assertEqual({r.asset.asset_id for r in draft_hits}, {"draft", "adopted"})

    def test_outcome_boost_overcomes_recency(self) -> None:
        # Identical text -> equal relevance; indexed FIRST (older) but higher outcome.
        self.retriever.index(
            _asset("adopted", "same title", state=LifecycleState.ACTIVE), outcome_score=1.0
        )
        self.retriever.index(
            _asset("neutral", "same title", state=LifecycleState.ACTIVE), outcome_score=0.0
        )
        res = self.retriever.search(KnowledgeQuery(text="same title", k=2))
        self.assertEqual(res[0].asset.asset_id, "adopted")

    def test_recency_boost_breaks_ties(self) -> None:
        self.retriever.index(
            _asset("old", "same title", state=LifecycleState.ACTIVE), outcome_score=0.0
        )
        self.retriever.index(
            _asset("new", "same title", state=LifecycleState.ACTIVE), outcome_score=0.0
        )
        res = self.retriever.search(KnowledgeQuery(text="same title", k=2))
        self.assertEqual(res[0].asset.asset_id, "new")

    def test_k_limits_and_empty(self) -> None:
        self.assertEqual(self.retriever.search(KnowledgeQuery(text="anything")), ())
        for i in range(5):
            self.retriever.index(_asset(f"a{i}", f"title token{i}", state=LifecycleState.ACTIVE))
        self.assertEqual(len(self.retriever.search(KnowledgeQuery(text="title", k=2))), 2)

    def test_reindex_replaces_same_asset(self) -> None:
        self.retriever.index(_asset("x", "old title alpha", state=LifecycleState.ACTIVE))
        self.retriever.index(_asset("x", "new title beta", state=LifecycleState.ACTIVE))
        res = self.retriever.search(KnowledgeQuery(text="new title beta", k=5))
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].asset.title, "new title beta")


if __name__ == "__main__":
    unittest.main()
