from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "packages" / "persistence" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import KnowledgeAsset, LifecycleState  # noqa: E402
from agent_os_core import HashingEmbedder, InMemoryKnowledgeRetriever  # noqa: E402

from agent_os_api.cli import run_cli  # noqa: E402
from agent_os_api.outcome_service import search_service  # noqa: E402


def _asset(aid: str, title: str):
    return KnowledgeAsset(
        asset_id=aid,
        title=title,
        asset_type="decision_loop",
        source_trace_id=f"trace-{aid}",
        owner="revenue_ops",
        state=LifecycleState.ACTIVE,
    )


class SearchServiceTest(unittest.TestCase):
    def test_search_service_returns_ranked_explainable_results(self) -> None:
        retriever = InMemoryKnowledgeRetriever(HashingEmbedder(64))
        retriever.index(_asset("gmv", "[gmv] gross merchandise value daily"))
        retriever.index(_asset("spend", "[spend] ad spend marketing budget"))

        payload = search_service(retriever, text="ad spend marketing budget", k=5)
        self.assertEqual(payload["results"][0]["asset_id"], "spend")
        self.assertIn("score_breakdown", payload["results"][0])
        self.assertIn("total", payload["results"][0]["score_breakdown"])


class CliSearchEntryPointTest(unittest.TestCase):
    def test_cli_search_is_wired_and_returns_structured_output(self) -> None:
        out = io.StringIO()
        # memory backend is per-process/empty, but the entry point must be wired end to end.
        rc = run_cli(["search", "--question", "anything"], stdout=out)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), {"results": []})


if __name__ == "__main__":
    unittest.main()
