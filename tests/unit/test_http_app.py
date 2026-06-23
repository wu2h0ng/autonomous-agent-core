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
OPERATOR_KEY = "secret-operator-key"


def _make_client(api_key: str | None, operator_api_key: str | None = OPERATOR_KEY):
    from starlette.testclient import TestClient

    from agent_os_api.http_app import create_app
    from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

    factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
    runtime = factory.build()
    app = create_app(
        runtime,
        api_key=api_key,
        operator_api_key=operator_api_key,
        adoption_ingest=factory.adoption_ingest(),
    )
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
        # P5.1b: a self-report does NOT promote knowledge (wirehead closed)...
        self.assertEqual(outcome_payload["knowledge_version"], 1)

        # ...only operator-attested realized value promotes it, over the shared ledger.
        adopt_resp = client.post(
            "/adoptions",
            json={"trace_id": trace_id, "outcome": "adopted", "reviewer": "ops@example.com"},
            headers=headers,
        )
        self.assertEqual(adopt_resp.status_code, 200, adopt_resp.text)
        adopt_payload = adopt_resp.json()
        self.assertEqual(adopt_payload["knowledge_version"], 2)
        self.assertIsNotNone(adopt_payload["knowledge_asset_id"])

    def test_adoptions_accepts_causal_attribution_and_surfaces_result_weight(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]

        adopt_resp = client.post(
            "/adoptions",
            json={
                "trace_id": trace_id,
                "outcome": "adopted",
                "reviewer": "ops@example.com",
                "causal_attribution": {
                    "metric_name": "gmv",
                    "observed_value": 11200.0,
                    "counterfactual_value": 10000.0,
                    "delta_absolute": 1200.0,
                    "delta_percent": 0.12,
                    "method": "holdout",
                    "comparison_ref": "holdout:campaign-42",
                    "window_start": "2026-06-01",
                    "window_end": "2026-06-07",
                    "confidence": 0.8,
                },
            },
            headers=headers,
        )
        self.assertEqual(adopt_resp.status_code, 200, adopt_resp.text)
        payload = adopt_resp.json()
        self.assertEqual(payload["knowledge_version"], 2)
        self.assertEqual(payload["result_weight"], 0.8)

    def test_run_response_carries_user_facing_result_artifact(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        payload = run_resp.json()

        artifact = payload["user_result"]
        self.assertEqual(artifact["kind"], "data_agent_result")
        self.assertEqual(artifact["trace_id"], payload["trace_id"])
        self.assertEqual(artifact["evidence_chain_id"], payload["evidence_chain_id"])
        self.assertEqual(artifact["decision"]["action_proposal_id"], payload["action_proposal_id"])
        report = artifact["report"]
        self.assertIn("evidence_cards", report)
        cards = {card["card_id"]: card for card in report["evidence_cards"]}
        self.assertEqual(cards["metric_contract"]["metric_name"], "gmv")
        self.assertEqual(
            cards["metric_contract"]["derived_from"], ["EvidenceChain.metric_contract"]
        )
        self.assertEqual(cards["sql_safety"]["checked_tables"], ["sales.orders"])
        self.assertEqual(
            cards["sql_safety"]["bound_parameter_names"],
            ["end_date", "limit", "start_date"],
        )
        self.assertTrue(cards["sql_safety"]["sql_fingerprint"].startswith("sha256:"))
        self.assertEqual(cards["query_result"]["columns"], ["order_date", "value"])
        self.assertEqual(cards["query_result"]["preview_row_count"], 1)
        self.assertIn(
            "table",
            {widget["type"] for widget in artifact["dashboard"]["widgets"]},
        )
        chart = next(
            (
                widget
                for widget in artifact["dashboard"]["widgets"]
                if widget["type"] == "line_chart"
            ),
            None,
        )
        self.assertIsNotNone(chart)
        self.assertEqual(chart["x_field"], "order_date")
        self.assertEqual(chart["y_field"], "value")
        self.assertEqual(chart["preview_rows"], [{"order_date": "2026-05-31", "value": 128800.0}])
        self.assertEqual(artifact["business_action"]["connector_name"], "action_record")
        self.assertEqual(artifact["business_action"]["status"], "awaiting_approval")
        self.assertNotIn("action_parameters", artifact["business_action"])

    def test_approval_execute_endpoint_runs_approval_bound_action(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        run_payload = run_resp.json()
        approval_id = run_payload["user_result"]["business_action"]["approval_id"]

        execute_resp = client.post(
            f"/approvals/{approval_id}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )

        self.assertEqual(execute_resp.status_code, 200, execute_resp.text)
        payload = execute_resp.json()
        self.assertEqual(payload["approval_id"], approval_id)
        self.assertEqual(payload["approval_status"], "approved")
        self.assertEqual(payload["approved_by"], "ops@example.com")
        self.assertEqual(payload["state"], "executed")
        self.assertEqual(
            payload["operation_id"],
            run_payload["user_result"]["business_action"]["operation_id"],
        )
        self.assertIn("connector_executed", [event["step"] for event in payload["events"]])

    def test_approval_execute_uses_approval_bound_context_without_cross_pollution(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        first_run = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动 first",
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        ).json()
        second_run = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动 second",
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        ).json()
        first_action = first_run["user_result"]["business_action"]
        second_action = second_run["user_result"]["business_action"]

        execute_resp = client.post(
            f"/approvals/{first_action['approval_id']}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )

        self.assertEqual(execute_resp.status_code, 200, execute_resp.text)
        payload = execute_resp.json()
        self.assertEqual(payload["operation_id"], first_action["operation_id"])
        self.assertNotEqual(payload["operation_id"], second_action["operation_id"])
        self.assertEqual(payload["evidence_chain_id"], first_action["evidence_chain_id"])
        self.assertNotEqual(payload["evidence_chain_id"], second_action["evidence_chain_id"])
        action_record_connector = client.app.state.runtime.connector_registry.get("action_record")
        records = action_record_connector.store.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["parameters"]["evidence_chain_id"],
            first_action["evidence_chain_id"],
        )
        self.assertNotEqual(
            records[0]["parameters"]["evidence_chain_id"],
            second_action["evidence_chain_id"],
        )

    def test_approval_execute_requires_operator_key_not_run_api_key(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )
        approval_id = run_resp.json()["user_result"]["business_action"]["approval_id"]

        execute_resp = client.post(
            f"/approvals/{approval_id}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers=headers,
        )

        self.assertEqual(execute_resp.status_code, 401)

    def test_approval_execute_second_call_is_rejected(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )
        approval_id = run_resp.json()["user_result"]["business_action"]["approval_id"]

        first = client.post(
            f"/approvals/{approval_id}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )
        second = client.post(
            f"/approvals/{approval_id}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 404, second.text)
        self.assertEqual(second.json()["detail"]["code"], "approval_context_not_found")

    def test_approval_execute_rejected_approval_is_409(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )
        approval_id = run_resp.json()["user_result"]["business_action"]["approval_id"]
        client.app.state.runtime.approval_runtime.reject(approval_id, reason="not acceptable")

        resp = client.post(
            f"/approvals/{approval_id}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )

        self.assertEqual(resp.status_code, 409, resp.text)
        self.assertEqual(resp.json()["detail"]["code"], "approval_execution_conflict")

    def test_approval_execute_unknown_approval_is_404(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post(
            "/approvals/approval-does-not-exist/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"]["code"], "approval_context_not_found")


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

    def test_approval_execute_route_also_guarded(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post(
            "/approvals/approval-x/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_approval_execute_wrong_operator_key_is_rejected(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post(
            "/approvals/approval-x/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": "nope"},
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
            factory.build(),
            retriever=factory.build_knowledge_retriever(),
            api_key=API_KEY,
            adoption_ingest=factory.adoption_ingest(),
        )
        return TestClient(app)

    @unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
    def test_run_outcome_search_end_to_end_over_http(self) -> None:
        client = self._make_pg_backed_client()
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]

        # P5.1b: promotion (and its index re-embed) is driven by realized adoption.
        adopt_resp = client.post(
            "/adoptions", json={"trace_id": trace_id, "outcome": "adopted"}, headers=headers
        )
        self.assertEqual(adopt_resp.status_code, 200, adopt_resp.text)

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


@unittest.skipUnless(_HTTP_AVAILABLE, "fastapi/httpx not installed")
class HttpDefaultAppRecallTest(unittest.TestCase):
    """The DEFAULT app (no injection) must close the knowledge loop (AR-20260611):
    a run indexes knowledge that the search endpoint and later runs can see."""

    def _default_client(self):
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app

        return TestClient(create_app(api_key=API_KEY))

    def test_default_app_search_reflects_runtime_writes(self) -> None:
        client = self._default_client()
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        asset_id = run_resp.json()["knowledge_asset_id"]
        self.assertIsNotNone(asset_id)

        search_resp = client.get("/knowledge/search", params={"q": "GMV", "k": 10}, headers=headers)
        self.assertEqual(search_resp.status_code, 200, search_resp.text)
        hits = [r["asset_id"] for r in search_resp.json()["results"]]
        self.assertIn(asset_id, hits, "default app search no longer sees runtime writes")

    def test_trace_endpoint_returns_persisted_run_trace(self) -> None:
        client = self._default_client()
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        trace_id = run_resp.json()["trace_id"]

        trace_resp = client.get(f"/traces/{trace_id}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        payload = trace_resp.json()
        self.assertEqual(payload["status"], "ok")
        steps = [e["step"] for e in payload["events"]]
        self.assertIn("evidence_chain", steps)
        self.assertTrue(payload["telemetry"])

    def test_blocked_run_is_auditable_via_trace_endpoint(self) -> None:
        client = self._default_client()
        headers = {"X-API-Key": API_KEY}

        resp = client.post(
            "/runs",
            json={"question": "revenue", "parameters": RUN_BODY["parameters"]},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 422)
        trace_id = resp.json()["detail"]["trace_id"]
        self.assertIsNotNone(trace_id, "422 must reference the persisted refusal trace")

        trace_resp = client.get(f"/traces/{trace_id}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        payload = trace_resp.json()
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["events"][-1]["step"], "blocked")

    def test_unknown_trace_is_404_and_endpoint_is_guarded(self) -> None:
        client = self._default_client()
        resp = client.get("/traces/trace-nope", headers={"X-API-Key": API_KEY})
        self.assertEqual(resp.status_code, 404)
        resp = client.get("/traces/trace-nope")
        self.assertEqual(resp.status_code, 401)

    def test_runs_response_carries_related_knowledge(self) -> None:
        client = self._default_client()
        headers = {"X-API-Key": API_KEY}

        first = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["related_knowledge"], [])  # nothing prior

        second = client.post("/runs", json=RUN_BODY, headers=headers)
        related = second.json()["related_knowledge"]
        self.assertTrue(related, "second run should recall the first run's knowledge")
        self.assertIn(first.json()["knowledge_asset_id"], [r["asset_id"] for r in related])
        self.assertIn("score", related[0])


if __name__ == "__main__":
    unittest.main()
