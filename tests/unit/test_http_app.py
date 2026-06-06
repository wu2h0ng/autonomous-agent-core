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
        # 'ROI' resolves to a metric with no SQL template -> expected business block.
        resp = client.post(
            "/runs",
            json={"question": "ROI", "parameters": RUN_BODY["parameters"]},
            headers={"X-API-Key": API_KEY},
        )
        self.assertEqual(resp.status_code, 422, resp.text)
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], "no_template")
        self.assertEqual(detail["stage"], "template_selection")


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


if __name__ == "__main__":
    unittest.main()
