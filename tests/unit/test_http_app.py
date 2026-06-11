from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_HTTP_AVAILABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)

DOMAIN_PACK = Path("domain_packs/content_commerce")
RUN_BODY = {
    "question": "GMV",
    "parameters": {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100},
}
API_KEY = "secret-test-key"


def _make_client(api_key: str | None):
    from starlette.testclient import TestClient

    from agent_os_api.http_app import create_app
    from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

    runtime = ContentCommerceRuntimeFactory(
        RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK)
    ).build()
    app = create_app(runtime, api_key=api_key)
    return TestClient(app)


@unittest.skipUnless(_HTTP_AVAILABLE, "fastapi/httpx not installed")
class HttpAppSharedRuntimeTest(unittest.TestCase):
    def test_run_then_outcome_shares_runtime_and_bumps_version(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        run_payload = run_resp.json()
        trace_id = run_payload["trace_id"]
        self.assertTrue(trace_id.startswith("trace-"))
        self.assertEqual(run_payload["knowledge_version"], 1)

        outcome_resp = client.post(
            "/outcomes",
            json={
                "trace_id": trace_id,
                "outcome": "adopted",
                "reviewer": "ops@example.com",
                "metric_deltas": {"gmv": 1000.0},
            },
            headers=headers,
        )
        self.assertEqual(outcome_resp.status_code, 200, outcome_resp.text)
        outcome_payload = outcome_resp.json()
        self.assertEqual(outcome_payload["trace_id"], trace_id)
        # The outcome endpoint sees the run's trace via the shared runtime.
        self.assertEqual(outcome_payload["knowledge_version"], 2)
        self.assertIsNotNone(outcome_payload["knowledge_asset_id"])


@unittest.skipUnless(_HTTP_AVAILABLE, "fastapi/httpx not installed")
class HttpAppBlockTest(unittest.TestCase):
    def test_run_blocked_returns_422_with_block_detail(self) -> None:
        client = _make_client(API_KEY)
        # 'revenue' parses to a metric the pack does not define -> expected business block.
        resp = client.post(
            "/runs",
            json={"question": "revenue", "parameters": RUN_BODY["parameters"]},
            headers={"X-API-Key": API_KEY},
        )
        self.assertEqual(resp.status_code, 422, resp.text)
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], "unknown_metric")
        self.assertEqual(detail["stage"], "metric_resolution")


@unittest.skipUnless(_HTTP_AVAILABLE, "fastapi/httpx not installed")
class HttpAppAuthBoundaryTest(unittest.TestCase):
    def test_missing_api_key_is_rejected(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post("/runs", json=RUN_BODY)
        self.assertEqual(resp.status_code, 401)

    def test_wrong_api_key_is_rejected(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post("/runs", json=RUN_BODY, headers={"X-API-Key": "nope"})
        self.assertEqual(resp.status_code, 401)

    def test_unconfigured_key_returns_503(self) -> None:
        client = _make_client(None)
        resp = client.post("/runs", json=RUN_BODY, headers={"X-API-Key": "anything"})
        self.assertEqual(resp.status_code, 503)

    def test_outcomes_route_also_guarded(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post(
            "/outcomes",
            json={"trace_id": "trace-x", "outcome": "adopted"},
        )
        self.assertEqual(resp.status_code, 401)


_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


@unittest.skipUnless(_HTTP_AVAILABLE, "fastapi/httpx not installed")
class HttpKnowledgeSearchTest(unittest.TestCase):
    def _make_pg_backed_client(self):
        """App over the postgres store backend (SQLite engine stand-in), so runtime
        writes land in knowledge_index and the retriever reads them back over HTTP."""
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app
        from agent_os_api.runtime_factory import (
            STORE_POSTGRES,
            ContentCommerceRuntimeFactory,
            RuntimeFactoryConfig,
        )

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        factory = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(
                domain_pack_path=DOMAIN_PACK,
                store_backend=STORE_POSTGRES,
                store_engine=engine,
            )
        )
        app = create_app(
            factory.build(), retriever=factory.build_knowledge_retriever(), api_key=API_KEY
        )
        return TestClient(app)

    @unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
    def test_run_outcome_search_end_to_end_over_http(self) -> None:
        client = self._make_pg_backed_client()
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]

        outcome_resp = client.post(
            "/outcomes", json={"trace_id": trace_id, "outcome": "adopted"}, headers=headers
        )
        self.assertEqual(outcome_resp.status_code, 200, outcome_resp.text)

        search_resp = client.get("/knowledge/search", params={"q": "GMV", "k": 10}, headers=headers)
        self.assertEqual(search_resp.status_code, 200, search_resp.text)
        results = search_resp.json()["results"]
        self.assertTrue(results, "run+outcome produced no retrievable knowledge")
        top = results[0]
        self.assertIn("score_breakdown", top)
        # The adopted outcome recorded over HTTP is reflected in the ranking signal.
        self.assertGreater(top["score_breakdown"]["outcome_boost"], 0.0)

    def test_search_requires_api_key(self) -> None:
        client = _make_client(API_KEY)
        resp = client.get("/knowledge/search", params={"q": "GMV"})
        self.assertEqual(resp.status_code, 401)

    def test_search_missing_query_is_422(self) -> None:
        client = _make_client(API_KEY)
        resp = client.get("/knowledge/search", headers={"X-API-Key": API_KEY})
        self.assertEqual(resp.status_code, 422)

    def test_injected_runtime_without_retriever_returns_503(self) -> None:
        # _make_client injects a runtime but no retriever -> search must refuse
        # loudly, not pretend an empty index.
        client = _make_client(API_KEY)
        resp = client.get("/knowledge/search", params={"q": "GMV"}, headers={"X-API-Key": API_KEY})
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
