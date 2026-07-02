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
EXTERNAL_API_KEY = "secret-external-key"
OPERATOR_KEY = "secret-operator-key"


class _FailingCheckpointStore:
    def save(self, snapshot: object) -> None:
        del snapshot
        raise RuntimeError("checkpoint backend unavailable")

    def get(self, run_id: str) -> None:
        del run_id
        return None


class _RaisingCheckpointReadStore:
    def save(self, snapshot: object) -> None:
        del snapshot

    def get(self, run_id: str) -> None:
        del run_id
        raise RuntimeError("dsn=postgres://secret-token@localhost/customer")


def _make_client(
    api_key: str | None,
    operator_api_key: str | None = OPERATOR_KEY,
    external_api_key: str | None = None,
    *,
    paused: bool = False,
):
    from starlette.testclient import TestClient

    from agent_os_api.http_app import create_app
    from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

    factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
    runtime = factory.build()
    if paused:
        factory.corrigibility_shell().op_pause()
    app = create_app(
        runtime,
        api_key=api_key,
        external_api_key=external_api_key,
        operator_api_key=operator_api_key,
        adoption_ingest=factory.adoption_ingest(),
        agent_checkpoint_store=factory.build_agent_checkpoint_store(),
    )
    return TestClient(app)


@unittest.skipUnless(_HTTP_AVAILABLE, "fastapi/httpx not installed")
class HttpAppSharedRuntimeTest(unittest.TestCase):
    def test_post_run_traverses_agent_runtime_envelope(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)

        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.policy_allowed", runtime_steps)
        self.assertIn("agent_runtime.tool_started", runtime_steps)
        self.assertIn("agent_runtime.tool_succeeded", runtime_steps)

    def test_internal_knowledge_review_queue_lists_draft_candidates(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}
        trace_ids = []
        for index in range(3):
            run_resp = client.post(
                "/runs",
                json={
                    "question": f"GMV review candidate {index}",
                    "parameters": {**RUN_BODY["parameters"], "limit": 10 + index},
                },
                headers=headers,
            )
            self.assertEqual(run_resp.status_code, 200, run_resp.text)
            trace_ids.append(run_resp.json()["trace_id"])

        queue_resp = client.get("/knowledge/review-queue", headers=headers)

        self.assertEqual(queue_resp.status_code, 200, queue_resp.text)
        payload = queue_resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["review_state"], "draft")
        self.assertEqual(payload["count"], 3)
        self.assertEqual(
            [item["source_trace_id"] for item in payload["items"]],
            trace_ids,
        )
        self.assertEqual({item["state"] for item in payload["items"]}, {"draft"})
        self.assertEqual({item["knowledge_version"] for item in payload["items"]}, {1})

        external_resp = client.get(
            "/knowledge/review-queue",
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 403, external_resp.text)

    def test_internal_knowledge_review_action_approves_candidate(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        queue_resp = client.get("/knowledge/review-queue", headers=headers)
        self.assertEqual(queue_resp.status_code, 200, queue_resp.text)
        asset_id = queue_resp.json()["items"][0]["asset_id"]

        approve_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={
                "action": "approve",
                "reviewer": "founder",
                "reason": "safe reusable lesson",
            },
            headers=headers,
        )

        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)
        payload = approve_resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["action"], "approve")
        self.assertEqual(payload["previous_state"], "draft")
        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["reviewer"], "founder")
        self.assertEqual(payload["knowledge_version"], 2)
        self.assertEqual(payload["result_weight"], 0.0)
        self.assertIsNone(payload["outcome"])
        self.assertEqual(client.get("/knowledge/review-queue", headers=headers).json()["count"], 0)

        external_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={
                "action": "reject",
                "reviewer": "external",
                "reason": "not allowed",
            },
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 403, external_resp.text)

        second_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={
                "action": "reject",
                "reviewer": "founder",
                "reason": "already reviewed",
            },
            headers=headers,
        )
        self.assertEqual(second_resp.status_code, 409, second_resp.text)

    def test_internal_knowledge_publish_requires_active_asset(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        asset_id = client.get("/knowledge/review-queue", headers=headers).json()["items"][0][
            "asset_id"
        ]

        draft_publish = client.post(
            f"/knowledge/assets/{asset_id}/publish",
            json={"reviewer": "founder", "reason": "skip review"},
            headers=headers,
        )
        self.assertEqual(draft_publish.status_code, 409, draft_publish.text)

        approve_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={
                "action": "approve",
                "reviewer": "founder",
                "reason": "safe reusable lesson",
            },
            headers=headers,
        )
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)

        publish_resp = client.post(
            f"/knowledge/assets/{asset_id}/publish",
            json={"reviewer": "founder", "reason": "ready for internal reuse"},
            headers=headers,
        )
        self.assertEqual(publish_resp.status_code, 200, publish_resp.text)
        payload = publish_resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["action"], "publish")
        self.assertEqual(payload["previous_state"], "active")
        self.assertEqual(payload["state"], "published")
        self.assertEqual(payload["knowledge_version"], 3)

        trace_resp = client.get(f"/traces/{run_resp.json()['trace_id']}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        publish_events = [
            event
            for event in trace_resp.json()["events"]
            if event["step"] == "knowledge_publish_decision"
        ]
        self.assertEqual(len(publish_events), 1)
        publish_payload = publish_events[0]["payload"]
        self.assertEqual(publish_payload["asset_id"], asset_id)
        self.assertEqual(publish_payload["previous_state"], "active")
        self.assertEqual(publish_payload["state"], "published")
        self.assertTrue(publish_payload["reason_present"])
        self.assertNotIn("ready for internal reuse", str(publish_payload))

        external_resp = client.post(
            f"/knowledge/assets/{asset_id}/publish",
            json={"reviewer": "external"},
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 403, external_resp.text)

    def test_internal_knowledge_asset_catalog_lists_reviewed_and_published_assets(
        self,
    ) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}
        draft_run = client.post(
            "/runs",
            json={"question": "GMV draft catalog item", "parameters": RUN_BODY["parameters"]},
            headers=headers,
        )
        active_run = client.post(
            "/runs",
            json={"question": "GMV active catalog item", "parameters": RUN_BODY["parameters"]},
            headers=headers,
        )
        published_run = client.post(
            "/runs",
            json={"question": "GMV published catalog item", "parameters": RUN_BODY["parameters"]},
            headers=headers,
        )
        self.assertEqual(draft_run.status_code, 200, draft_run.text)
        self.assertEqual(active_run.status_code, 200, active_run.text)
        self.assertEqual(published_run.status_code, 200, published_run.text)

        queue = client.get("/knowledge/review-queue", headers=headers).json()["items"]
        by_trace = {item["source_trace_id"]: item["asset_id"] for item in queue}
        active_asset_id = by_trace[active_run.json()["trace_id"]]
        published_asset_id = by_trace[published_run.json()["trace_id"]]

        active_approve = client.post(
            f"/knowledge/review-queue/{active_asset_id}/decision",
            json={"action": "approve", "reviewer": "founder"},
            headers=headers,
        )
        published_approve = client.post(
            f"/knowledge/review-queue/{published_asset_id}/decision",
            json={"action": "approve", "reviewer": "founder"},
            headers=headers,
        )
        self.assertEqual(active_approve.status_code, 200, active_approve.text)
        self.assertEqual(published_approve.status_code, 200, published_approve.text)
        publish_resp = client.post(
            f"/knowledge/assets/{published_asset_id}/publish",
            json={"reviewer": "founder"},
            headers=headers,
        )
        self.assertEqual(publish_resp.status_code, 200, publish_resp.text)

        catalog_resp = client.get("/knowledge/assets", headers=headers)

        self.assertEqual(catalog_resp.status_code, 200, catalog_resp.text)
        payload = catalog_resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["catalog_state"], "active,published")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            {item["asset_id"] for item in payload["items"]},
            {active_asset_id, published_asset_id},
        )
        self.assertEqual({item["state"] for item in payload["items"]}, {"active", "published"})
        self.assertEqual({item["knowledge_version"] for item in payload["items"]}, {2, 3})

        all_resp = client.get("/knowledge/assets", params={"state": "all"}, headers=headers)
        self.assertEqual(all_resp.status_code, 200, all_resp.text)
        self.assertEqual(all_resp.json()["count"], 3)
        self.assertIn(
            draft_run.json()["knowledge_asset_id"],
            [item["asset_id"] for item in all_resp.json()["items"]],
        )

        unknown_filter = client.get(
            "/knowledge/assets",
            params={"state": "external"},
            headers=headers,
        )
        self.assertEqual(unknown_filter.status_code, 400, unknown_filter.text)
        self.assertEqual(
            unknown_filter.json()["detail"]["code"],
            "KNOWLEDGE_CATALOG_INVALID_REQUEST",
        )

        external_resp = client.get(
            "/knowledge/assets",
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 403, external_resp.text)

    def test_internal_knowledge_asset_detail_is_read_only_and_guarded(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]
        asset_id = client.get("/knowledge/review-queue", headers=headers).json()["items"][0][
            "asset_id"
        ]
        approve_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={"action": "approve", "reviewer": "founder"},
            headers=headers,
        )
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)

        detail_resp = client.get(f"/knowledge/assets/{asset_id}", headers=headers)

        self.assertEqual(detail_resp.status_code, 200, detail_resp.text)
        payload = detail_resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["source_trace_id"], trace_id)
        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["knowledge_version"], 2)
        self.assertTrue(payload["has_source_trace"])
        self.assertNotIn("events", payload)

        repeat_resp = client.get(f"/knowledge/assets/{asset_id}", headers=headers)
        self.assertEqual(repeat_resp.status_code, 200, repeat_resp.text)
        self.assertEqual(repeat_resp.json()["knowledge_version"], 2)

        missing_resp = client.get("/knowledge/assets/knowledge-missing", headers=headers)
        self.assertEqual(missing_resp.status_code, 404, missing_resp.text)
        self.assertEqual(missing_resp.json()["detail"]["code"], "KNOWLEDGE_ASSET_NOT_FOUND")

        external_resp = client.get(
            f"/knowledge/assets/{asset_id}",
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 403, external_resp.text)

    def test_internal_knowledge_asset_lifecycle_events_are_safe_and_guarded(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]
        asset_id = client.get("/knowledge/review-queue", headers=headers).json()["items"][0][
            "asset_id"
        ]
        approve_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={
                "action": "approve",
                "reviewer": "founder",
                "reason": "sensitive review rationale",
            },
            headers=headers,
        )
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)
        publish_resp = client.post(
            f"/knowledge/assets/{asset_id}/publish",
            json={"reviewer": "founder", "reason": "sensitive publish rationale"},
            headers=headers,
        )
        self.assertEqual(publish_resp.status_code, 200, publish_resp.text)
        deprecate_resp = client.post(
            f"/knowledge/assets/{asset_id}/deprecate",
            json={"reviewer": "founder", "reason": "sensitive deprecate rationale"},
            headers=headers,
        )
        self.assertEqual(deprecate_resp.status_code, 200, deprecate_resp.text)

        events_resp = client.get(
            f"/knowledge/assets/{asset_id}/lifecycle-events",
            headers=headers,
        )

        self.assertEqual(events_resp.status_code, 200, events_resp.text)
        payload = events_resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["source_trace_id"], trace_id)
        self.assertTrue(payload["has_source_trace"])
        self.assertEqual(payload["count"], 3)
        self.assertEqual(
            [event["step"] for event in payload["events"]],
            [
                "knowledge_review_decision",
                "knowledge_publish_decision",
                "knowledge_deprecate_decision",
            ],
        )
        for event in payload["events"]:
            self.assertEqual(event["asset_id"], asset_id)
            self.assertEqual(event["trace_id"], trace_id)
            self.assertTrue(event["reason_present"])
            self.assertNotIn("reason", event)
            self.assertNotIn("sensitive", str(event))

        repeat_detail = client.get(f"/knowledge/assets/{asset_id}", headers=headers)
        self.assertEqual(repeat_detail.status_code, 200, repeat_detail.text)
        self.assertEqual(repeat_detail.json()["knowledge_version"], 4)

        missing_resp = client.get(
            "/knowledge/assets/knowledge-missing/lifecycle-events",
            headers=headers,
        )
        self.assertEqual(missing_resp.status_code, 404, missing_resp.text)
        self.assertEqual(missing_resp.json()["detail"]["code"], "KNOWLEDGE_ASSET_NOT_FOUND")

        external_resp = client.get(
            f"/knowledge/assets/{asset_id}/lifecycle-events",
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 403, external_resp.text)

    def test_internal_knowledge_deprecate_requires_reviewed_asset(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        asset_id = client.get("/knowledge/review-queue", headers=headers).json()["items"][0][
            "asset_id"
        ]

        draft_deprecate = client.post(
            f"/knowledge/assets/{asset_id}/deprecate",
            json={"reviewer": "founder", "reason": "skip review"},
            headers=headers,
        )
        self.assertEqual(draft_deprecate.status_code, 409, draft_deprecate.text)

        approve_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={
                "action": "approve",
                "reviewer": "founder",
                "reason": "safe reusable lesson",
            },
            headers=headers,
        )
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)

        deprecate_resp = client.post(
            f"/knowledge/assets/{asset_id}/deprecate",
            json={"reviewer": "founder", "reason": "superseded"},
            headers=headers,
        )
        self.assertEqual(deprecate_resp.status_code, 200, deprecate_resp.text)
        payload = deprecate_resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["action"], "deprecate")
        self.assertEqual(payload["previous_state"], "active")
        self.assertEqual(payload["state"], "deprecated")
        self.assertEqual(payload["knowledge_version"], 3)

        catalog_resp = client.get("/knowledge/assets", headers=headers)
        self.assertEqual(catalog_resp.status_code, 200, catalog_resp.text)
        self.assertEqual(catalog_resp.json()["count"], 0)
        all_resp = client.get("/knowledge/assets", params={"state": "all"}, headers=headers)
        self.assertEqual(all_resp.status_code, 200, all_resp.text)
        self.assertEqual(all_resp.json()["items"][0]["state"], "deprecated")

        trace_resp = client.get(f"/traces/{run_resp.json()['trace_id']}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        deprecate_events = [
            event
            for event in trace_resp.json()["events"]
            if event["step"] == "knowledge_deprecate_decision"
        ]
        self.assertEqual(len(deprecate_events), 1)
        deprecate_payload = deprecate_events[0]["payload"]
        self.assertEqual(deprecate_payload["asset_id"], asset_id)
        self.assertEqual(deprecate_payload["previous_state"], "active")
        self.assertEqual(deprecate_payload["state"], "deprecated")
        self.assertTrue(deprecate_payload["reason_present"])
        self.assertNotIn("superseded", str(deprecate_payload))

        external_resp = client.post(
            f"/knowledge/assets/{asset_id}/deprecate",
            json={"reviewer": "external"},
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 403, external_resp.text)

    def test_knowledge_review_action_is_visible_in_persisted_trace_without_raw_reason(
        self,
    ) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}
        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]
        asset_id = client.get("/knowledge/review-queue", headers=headers).json()["items"][0][
            "asset_id"
        ]

        decision_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={
                "action": "approve",
                "reviewer": "founder",
                "reason": "contains sensitive customer rationale",
            },
            headers=headers,
        )
        self.assertEqual(decision_resp.status_code, 200, decision_resp.text)

        trace_resp = client.get(f"/traces/{trace_id}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        audit_events = [
            event
            for event in trace_resp.json()["events"]
            if event["step"] == "knowledge_review_decision"
        ]
        self.assertEqual(len(audit_events), 1)
        payload = audit_events[0]["payload"]
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["action"], "approve")
        self.assertEqual(payload["previous_state"], "draft")
        self.assertEqual(payload["state"], "active")
        self.assertEqual(payload["reviewer"], "founder")
        self.assertTrue(payload["reason_present"])
        self.assertNotIn("reason", payload)
        self.assertNotIn("sensitive customer rationale", str(payload))

    def test_post_run_persists_agent_runtime_envelope_in_run_trace(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]

        trace_resp = client.get(f"/traces/{trace_id}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        trace_payload = trace_resp.json()
        runtime_events = [
            event for event in trace_payload["events"] if event["step"].startswith("agent_runtime.")
        ]
        runtime_steps = [event["step"] for event in runtime_events]

        self.assertIn("agent_runtime.policy_allowed", runtime_steps)
        self.assertIn("agent_runtime.tool_started", runtime_steps)
        self.assertIn("agent_runtime.tool_succeeded", runtime_steps)
        trace_steps = [event["step"] for event in trace_payload["events"]]
        self.assertLess(
            trace_steps.index("agent_runtime.tool_started"),
            trace_steps.index("intent"),
        )
        self.assertLess(
            trace_steps.index("knowledge_asset_candidate"),
            trace_steps.index("agent_runtime.tool_succeeded"),
        )
        encoded_runtime_payloads = str([event["payload"] for event in runtime_events])
        self.assertNotIn("2026-05-25", encoded_runtime_payloads)
        self.assertNotIn("start_date", encoded_runtime_payloads)
        self.assertNotIn("end_date", encoded_runtime_payloads)

    def test_post_run_runtime_diagnostics_are_request_scoped(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        first_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(first_resp.status_code, 200, first_resp.text)
        first_events = list(client.app.state.agent_runtime_trace_writer.events)
        first_run_id = next(
            event["payload"]["run_id"]
            for event in first_events
            if event["step"] == "agent_runtime.invocation_started"
        )

        second_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(second_resp.status_code, 200, second_resp.text)
        second_events = list(client.app.state.agent_runtime_trace_writer.events)
        second_run_ids = {
            event["payload"]["run_id"] for event in second_events if event["payload"].get("run_id")
        }

        self.assertLessEqual(len(second_events), len(first_events))
        self.assertNotIn(first_run_id, second_run_ids)

    def test_post_run_writes_agent_runtime_checkpoint_from_http_entrypoint(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        runtime_events = client.app.state.agent_runtime_trace_writer.events
        agent_run_id = next(
            event["payload"]["run_id"]
            for event in runtime_events
            if event["step"] == "agent_runtime.invocation_started"
        )

        snapshot = client.app.state.agent_checkpoint_store.get(agent_run_id)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.run_id, agent_run_id)
        self.assertEqual(snapshot.last_completed_boundary, "agent_runtime.invoke_tool")
        self.assertEqual(snapshot.last_result.status, "ok")
        self.assertEqual(snapshot.metadata["tool_name"], "trusted_loop.evaluate")

    def test_internal_run_response_carries_runtime_checkpoint_ref(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        payload = run_resp.json()
        checkpoint_ref = payload["runtime_checkpoint_ref"]

        self.assertTrue(checkpoint_ref["run_id"].startswith("http-run-"))
        self.assertTrue(checkpoint_ref["trace_id"].startswith("agent-trace-"))
        self.assertEqual(checkpoint_ref["tool_name"], "trusted_loop.evaluate")
        self.assertEqual(
            checkpoint_ref["call_id"],
            f"trusted_loop.evaluate:{checkpoint_ref['run_id']}",
        )

        external_resp = client.post(
            "/runs",
            json={**RUN_BODY, "audience": "internal"},
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 200, external_resp.text)
        self.assertIsNone(external_resp.json()["runtime_checkpoint_ref"])

    def test_run_response_omits_runtime_checkpoint_ref_without_checkpoint_store(self) -> None:
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        client = TestClient(
            create_app(
                factory.build(),
                api_key=API_KEY,
                adoption_ingest=factory.adoption_ingest(),
                agent_checkpoint_store=None,
            )
        )

        run_resp = client.post("/runs", json=RUN_BODY, headers={"X-API-Key": API_KEY})

        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        self.assertIsNone(run_resp.json()["runtime_checkpoint_ref"])

    def test_runtime_resume_replays_checkpoint_without_rerunning_trusted_loop(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        run_payload = run_resp.json()
        checkpoint_ref = run_payload["runtime_checkpoint_ref"]
        before_trace = client.get(f"/traces/{run_payload['trace_id']}", headers=headers).json()

        resume_resp = client.post(
            f"/agent-runtime/runs/{checkpoint_ref['run_id']}/resume",
            json={
                "runtime_trace_id": checkpoint_ref["trace_id"],
                "question": RUN_BODY["question"],
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )

        self.assertEqual(resume_resp.status_code, 200, resume_resp.text)
        payload = resume_resp.json()
        self.assertTrue(payload["resumed"])
        self.assertEqual(payload["status"], "ok")
        self.assertIsNone(payload["error_code"])
        self.assertEqual(payload["runtime_run_id"], checkpoint_ref["run_id"])
        self.assertEqual(payload["runtime_trace_id"], checkpoint_ref["trace_id"])
        self.assertEqual(payload["tool_name"], "trusted_loop.evaluate")
        self.assertEqual(payload["output_ref"]["kind"], "trusted_loop_outcome")
        self.assertEqual(payload["output_ref"]["business_trace_id"], run_payload["trace_id"])
        self.assertEqual(
            payload["output_ref"]["evidence_chain_id"],
            run_payload["evidence_chain_id"],
        )
        self.assertEqual(payload["output_ref"]["row_count"], run_payload["row_count"])
        encoded_payload = str(payload)
        self.assertNotIn("2026-05-25", encoded_payload)
        self.assertNotIn("start_date", encoded_payload)
        self.assertNotIn("end_date", encoded_payload)
        after_trace = client.get(f"/traces/{run_payload['trace_id']}", headers=headers).json()
        self.assertEqual(before_trace["status"], after_trace["status"])
        self.assertGreater(len(after_trace["events"]), len(before_trace["events"]))
        after_steps = [event["step"] for event in after_trace["events"]]
        self.assertIn("agent_runtime.checkpoint_resume_succeeded", after_steps)
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.checkpoint_resume_started", runtime_steps)
        self.assertIn("agent_runtime.checkpoint_resume_succeeded", runtime_steps)
        self.assertNotIn("agent_runtime.tool_started", runtime_steps)

    def test_runtime_resume_mismatch_fails_closed_without_raw_args(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        checkpoint_ref = run_resp.json()["runtime_checkpoint_ref"]

        resume_resp = client.post(
            f"/agent-runtime/runs/{checkpoint_ref['run_id']}/resume",
            json={
                "runtime_trace_id": checkpoint_ref["trace_id"],
                "question": RUN_BODY["question"],
                "parameters": {
                    **RUN_BODY["parameters"],
                    "start_date": "changed-secret-date",
                },
            },
            headers=headers,
        )

        self.assertEqual(resume_resp.status_code, 409, resume_resp.text)
        detail = resume_resp.json()["detail"]
        self.assertEqual(detail["code"], "CHECKPOINT_MISMATCH")
        self.assertEqual(detail["stage"], "agent_runtime")
        encoded_detail = str(detail)
        self.assertNotIn("changed-secret-date", encoded_detail)
        self.assertNotIn("start_date", encoded_detail)
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.checkpoint_resume_failed", runtime_steps)
        self.assertNotIn("agent_runtime.tool_started", runtime_steps)

    def test_runtime_resume_context_mismatch_does_not_echo_untrusted_trace_id(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        checkpoint_ref = run_resp.json()["runtime_checkpoint_ref"]

        resume_resp = client.post(
            f"/agent-runtime/runs/{checkpoint_ref['run_id']}/resume",
            json={
                "runtime_trace_id": "secret-runtime-trace-token",
                "question": RUN_BODY["question"],
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )

        self.assertEqual(resume_resp.status_code, 409, resume_resp.text)
        encoded = str(resume_resp.json()) + repr(client.app.state.agent_runtime_trace_writer.events)
        self.assertNotIn("secret-runtime-trace-token", encoded)

    def test_runtime_resume_without_checkpoint_store_is_service_unavailable(self) -> None:
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        client = TestClient(
            create_app(
                factory.build(),
                api_key=API_KEY,
                adoption_ingest=factory.adoption_ingest(),
                agent_checkpoint_store=None,
            )
        )

        resume_resp = client.post(
            "/agent-runtime/runs/http-run-missing-store/resume",
            json={
                "runtime_trace_id": "agent-trace-missing-store",
                "question": RUN_BODY["question"],
                "parameters": RUN_BODY["parameters"],
            },
            headers={"X-API-Key": API_KEY},
        )

        self.assertEqual(resume_resp.status_code, 503, resume_resp.text)
        self.assertEqual(resume_resp.json()["detail"]["code"], "CHECKPOINT_NOT_AVAILABLE")

    def test_runtime_resume_checkpoint_read_failure_is_typed_500(self) -> None:
        from starlette.testclient import TestClient

        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        checkpoint_ref = run_resp.json()["runtime_checkpoint_ref"]
        client.app.state.agent_checkpoint_store = _RaisingCheckpointReadStore()
        client = TestClient(client.app, raise_server_exceptions=False)

        resume_resp = client.post(
            f"/agent-runtime/runs/{checkpoint_ref['run_id']}/resume",
            json={
                "runtime_trace_id": checkpoint_ref["trace_id"],
                "question": RUN_BODY["question"],
                "parameters": RUN_BODY["parameters"],
            },
            headers=headers,
        )

        self.assertEqual(resume_resp.status_code, 500, resume_resp.text)
        self.assertIn("application/json", resume_resp.headers.get("content-type", ""))
        detail = resume_resp.json()["detail"]
        self.assertEqual(detail["code"], "CHECKPOINT_READ_FAILED")
        self.assertEqual(detail["stage"], "agent_runtime")
        encoded = str(detail)
        self.assertNotIn("secret-token", encoded)
        self.assertNotIn("postgres://", encoded)

    def test_post_run_pause_is_denied_by_agent_runtime_before_tool_start(self) -> None:
        client = _make_client(API_KEY, paused=True)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)

        self.assertEqual(run_resp.status_code, 422, run_resp.text)
        detail = run_resp.json()["detail"]
        self.assertEqual(detail["code"], "DENY_PAUSED")
        self.assertEqual(detail["stage"], "agent_runtime")
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.policy_denied", runtime_steps)
        self.assertNotIn("agent_runtime.tool_started", runtime_steps)
        trace_id = detail["trace_id"]
        trace_resp = client.get(f"/traces/{trace_id}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        trace_payload = trace_resp.json()
        self.assertEqual(trace_payload["status"], "blocked")
        trace_steps = [event["step"] for event in trace_payload["events"]]
        self.assertIn("agent_runtime.policy_denied", trace_steps)
        self.assertIn("blocked", trace_steps)
        self.assertNotIn("agent_runtime.tool_started", trace_steps)

    def test_post_run_tool_error_returns_500_without_exception_text_for_external(self) -> None:
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app
        from agent_os_core import InMemoryTraceStore

        class ExplodingRuntime:
            shell_view = None

            def __init__(self) -> None:
                self.trace_store = InMemoryTraceStore()

            def evaluate(self, question, parameters):  # noqa: ANN001, ANN201 - test double
                raise RuntimeError("dsn=postgres://secret-token@localhost/customer")

        client = TestClient(
            create_app(
                ExplodingRuntime(),
                api_key=API_KEY,
                external_api_key=EXTERNAL_API_KEY,
            )
        )

        run_resp = client.post(
            "/runs",
            json=RUN_BODY,
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )

        self.assertEqual(run_resp.status_code, 500, run_resp.text)
        detail = run_resp.json()["detail"]
        self.assertEqual(detail["code"], "AGENT_RUNTIME_TOOL_ERROR")
        encoded = str(detail).lower()
        self.assertNotIn("postgres://", encoded)
        self.assertNotIn("secret-token", encoded)

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

    def test_outcomes_traverse_agent_runtime_envelope_without_knowledge_promotion(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]
        run_writer = client.app.state.agent_runtime_trace_writer

        outcome_resp = client.post(
            "/outcomes",
            json={
                "trace_id": trace_id,
                "outcome": "adopted",
                "reviewer": "ops@example.com",
                "metric_deltas": {"gmv": 1000.0, "secret_token": "do-not-leak"},
            },
            headers=headers,
        )

        self.assertEqual(outcome_resp.status_code, 200, outcome_resp.text)
        self.assertIsNot(client.app.state.agent_runtime_trace_writer, run_writer)
        payload = outcome_resp.json()
        self.assertEqual(payload["knowledge_version"], 1)
        self.assertIsNotNone(payload["knowledge_asset_id"])
        outcome_events = [
            event
            for event in client.app.state.agent_runtime_trace_writer.events
            if event["payload"].get("tool_name") == "trusted_loop.record_outcome"
        ]
        outcome_steps = [event["step"] for event in outcome_events]
        self.assertIn("agent_runtime.policy_allowed", outcome_steps)
        self.assertIn("agent_runtime.tool_started", outcome_steps)
        self.assertIn("agent_runtime.tool_succeeded", outcome_steps)
        self.assertIn("agent_runtime.invocation_finished", outcome_steps)

        trace_resp = client.get(f"/traces/{trace_id}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        trace_events = trace_resp.json()["events"]
        persisted_record_events = [
            event
            for event in trace_events
            if event["payload"].get("tool_name") == "trusted_loop.record_outcome"
        ]
        self.assertTrue(persisted_record_events)
        knowledge_candidate_index = next(
            index
            for index, event in enumerate(trace_events)
            if event["step"] == "knowledge_asset_candidate"
        )
        record_tool_started_index = next(
            index
            for index, event in enumerate(trace_events)
            if event["step"] == "agent_runtime.tool_started"
            and event["payload"].get("tool_name") == "trusted_loop.record_outcome"
        )
        self.assertLess(knowledge_candidate_index, record_tool_started_index)
        encoded_runtime_payloads = str(
            [
                event["payload"]
                for event in trace_events
                if event["step"].startswith("agent_runtime.")
            ]
        )
        self.assertNotIn("1000.0", encoded_runtime_payloads)
        self.assertNotIn("metric_deltas", encoded_runtime_payloads)
        self.assertNotIn("secret_token", encoded_runtime_payloads)
        self.assertNotIn("do-not-leak", encoded_runtime_payloads)

    def test_outcomes_paused_shell_denies_before_feedback_write(self) -> None:
        client = _make_client(API_KEY, paused=True)
        headers = {"X-API-Key": API_KEY}

        outcome_resp = client.post(
            "/outcomes",
            json={
                "trace_id": "trace-paused-outcome",
                "outcome": "adopted",
                "reviewer": "ops@example.com",
            },
            headers=headers,
        )

        self.assertEqual(outcome_resp.status_code, 409, outcome_resp.text)
        detail = outcome_resp.json()["detail"]
        self.assertEqual(detail["code"], "DENY_PAUSED")
        self.assertEqual(detail["stage"], "agent_runtime")
        self.assertEqual(
            client.app.state.runtime.feedback_store.get_by_trace("trace-paused-outcome"),
            (),
        )
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.policy_denied", runtime_steps)
        self.assertNotIn("agent_runtime.tool_started", runtime_steps)

    def test_outcome_runtime_denial_preserves_existing_run_trace(self) -> None:
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        client = TestClient(
            create_app(
                runtime,
                api_key=API_KEY,
                operator_api_key=OPERATOR_KEY,
                adoption_ingest=factory.adoption_ingest(),
                agent_checkpoint_store=factory.build_agent_checkpoint_store(),
            )
        )
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]
        before_trace = client.get(f"/traces/{trace_id}", headers=headers).json()
        before_steps = [event["step"] for event in before_trace["events"]]
        self.assertIn("intent", before_steps)
        self.assertIn("knowledge_asset_candidate", before_steps)

        factory.corrigibility_shell().op_pause()
        outcome_resp = client.post(
            "/outcomes",
            json={
                "trace_id": trace_id,
                "outcome": "adopted",
                "reviewer": "ops@example.com",
            },
            headers=headers,
        )

        self.assertEqual(outcome_resp.status_code, 409, outcome_resp.text)
        after_trace = client.get(f"/traces/{trace_id}", headers=headers).json()
        after_steps = [event["step"] for event in after_trace["events"]]
        self.assertIn("intent", after_steps)
        self.assertIn("knowledge_asset_candidate", after_steps)
        self.assertIn("agent_runtime.policy_denied", after_steps)
        self.assertIn("blocked", after_steps)

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

    def test_adoptions_traverse_runtime_envelope_and_preserve_writer_authority(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]
        run_writer = client.app.state.agent_runtime_trace_writer

        adopt_resp = client.post(
            "/adoptions",
            json={
                "trace_id": trace_id,
                "outcome": "adopted",
                "reviewer": "ops@example.com",
                "metric_deltas": {"gmv": 1200.0, "api_key": "do-not-leak"},
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
        self.assertIsNot(client.app.state.agent_runtime_trace_writer, run_writer)
        payload = adopt_resp.json()
        self.assertEqual(payload["knowledge_version"], 2)
        self.assertEqual(payload["result_weight"], 0.8)
        self.assertEqual(len(client.app.state.runtime.adoption_for_trace(trace_id)), 1)
        self.assertFalse(hasattr(client.app.state.runtime, "adoption_ingest"))
        adoption_events = [
            event
            for event in client.app.state.agent_runtime_trace_writer.events
            if event["payload"].get("tool_name") == "trusted_loop.attest_adoption"
        ]
        adoption_steps = [event["step"] for event in adoption_events]
        self.assertIn("agent_runtime.policy_allowed", adoption_steps)
        self.assertIn("agent_runtime.tool_started", adoption_steps)
        self.assertIn("agent_runtime.tool_succeeded", adoption_steps)
        trace_resp = client.get(f"/traces/{trace_id}", headers=headers)
        self.assertEqual(trace_resp.status_code, 200, trace_resp.text)
        trace_events = trace_resp.json()["events"]
        knowledge_candidate_index = next(
            index
            for index, event in enumerate(trace_events)
            if event["step"] == "knowledge_asset_candidate"
        )
        adoption_tool_started_index = next(
            index
            for index, event in enumerate(trace_events)
            if event["step"] == "agent_runtime.tool_started"
            and event["payload"].get("tool_name") == "trusted_loop.attest_adoption"
        )
        self.assertLess(knowledge_candidate_index, adoption_tool_started_index)
        encoded_runtime_payloads = str(
            [event["payload"] for event in client.app.state.agent_runtime_trace_writer.events]
        )
        self.assertNotIn("holdout:campaign-42", encoded_runtime_payloads)
        self.assertNotIn("delta_absolute", encoded_runtime_payloads)
        self.assertNotIn("1200.0", encoded_runtime_payloads)
        self.assertNotIn("api_key", encoded_runtime_payloads)
        self.assertNotIn("do-not-leak", encoded_runtime_payloads)

    def test_adoptions_paused_shell_denies_before_adoption_write(self) -> None:
        client = _make_client(API_KEY, paused=True)
        headers = {"X-API-Key": API_KEY}

        adopt_resp = client.post(
            "/adoptions",
            json={
                "trace_id": "trace-paused-adoption",
                "outcome": "adopted",
                "reviewer": "ops@example.com",
            },
            headers=headers,
        )

        self.assertEqual(adopt_resp.status_code, 409, adopt_resp.text)
        detail = adopt_resp.json()["detail"]
        self.assertEqual(detail["code"], "DENY_PAUSED")
        self.assertEqual(detail["stage"], "agent_runtime")
        self.assertEqual(client.app.state.runtime.adoption_for_trace("trace-paused-adoption"), ())
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.policy_denied", runtime_steps)
        self.assertNotIn("agent_runtime.tool_started", runtime_steps)

    def test_adoptions_preserve_success_on_checkpoint_failure_after_value_write(self) -> None:
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        client = TestClient(
            create_app(
                runtime,
                api_key=API_KEY,
                operator_api_key=OPERATOR_KEY,
                adoption_ingest=factory.adoption_ingest(),
                agent_checkpoint_store=factory.build_agent_checkpoint_store(),
            )
        )
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]
        client.app.state.agent_checkpoint_store = _FailingCheckpointStore()
        adopt_resp = client.post(
            "/adoptions",
            json={
                "trace_id": trace_id,
                "outcome": "adopted",
                "reviewer": "ops@example.com",
            },
            headers=headers,
        )

        self.assertEqual(adopt_resp.status_code, 200, adopt_resp.text)
        self.assertEqual(len(client.app.state.runtime.adoption_for_trace(trace_id)), 1)
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.tool_succeeded", runtime_steps)
        self.assertIn("agent_runtime.checkpoint_failed", runtime_steps)

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

    def test_run_response_redacts_external_audience_result_details(self) -> None:
        client = _make_client(API_KEY)
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
                "audience": "external",
            },
            headers=headers,
        )

        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        artifact = run_resp.json()["user_result"]
        self.assertEqual(artifact["audience"], "external")
        self.assertTrue(artifact["redaction"]["applied"])
        cards = {card["card_id"]: card for card in artifact["report"]["evidence_cards"]}
        self.assertEqual(cards["sql_safety"]["checked_tables"], [])
        self.assertEqual(cards["sql_safety"]["bound_parameter_names"], [])
        self.assertIsNone(cards["sql_safety"]["limit_value"])
        self.assertIsNone(cards["sql_safety"]["sql_fingerprint"])
        self.assertEqual(cards["query_result"]["columns"], [])
        for widget in artifact["dashboard"]["widgets"]:
            self.assertEqual(widget["columns"], [])
            self.assertEqual(widget["preview_rows"], [])
            self.assertIsNone(widget["x_field"])
            self.assertIsNone(widget["y_field"])
        rendered = run_resp.text
        self.assertNotIn("sales.orders", rendered)
        self.assertNotIn("order_date", rendered)
        self.assertNotIn("sha256:", rendered)
        self.assertNotIn("start_date", rendered)
        self.assertNotIn("2026-05-31", rendered)

    def test_external_api_key_forces_external_user_result_projection(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)

        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
                "audience": "internal",
            },
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )

        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        artifact = run_resp.json()["user_result"]
        self.assertEqual(artifact["audience"], "external")
        self.assertTrue(artifact["redaction"]["applied"])
        self.assertIsNone(run_resp.json()["provider_id"])
        self.assertIsNone(run_resp.json()["knowledge_asset_id"])
        self.assertEqual(run_resp.json()["trace_steps"], [])
        self.assertEqual(run_resp.json()["related_knowledge"], [])
        rendered = run_resp.text
        self.assertNotIn("sales.orders", rendered)
        self.assertNotIn("order_date", rendered)
        self.assertNotIn("sha256:", rendered)

    def test_external_report_key_reads_existing_report_without_reexecuting_run(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        run_resp = client.post(
            "/runs",
            json={
                "question": "GMV 记录行动",
                "parameters": RUN_BODY["parameters"],
                "audience": "internal",
            },
            headers={"X-API-Key": API_KEY},
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]

        def fail_if_reexecuted(*_args, **_kwargs):
            raise AssertionError("report read must not call runtime.evaluate")

        client.app.state.runtime.evaluate = fail_if_reexecuted

        report_resp = client.get(
            f"/runs/{trace_id}/report",
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )

        self.assertEqual(report_resp.status_code, 200, report_resp.text)
        payload = report_resp.json()
        self.assertEqual(payload["trace_id"], trace_id)
        self.assertEqual(payload["audience"], "external")
        artifact = payload["user_result"]
        self.assertEqual(artifact["trace_id"], trace_id)
        self.assertEqual(artifact["audience"], "external")
        self.assertTrue(artifact["redaction"]["applied"])
        rendered = report_resp.text
        self.assertNotIn("sales.orders", rendered)
        self.assertNotIn("order_date", rendered)
        self.assertNotIn("sha256:", rendered)

    def test_report_read_respects_internal_access_and_external_ceiling(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        run_resp = client.post(
            "/runs",
            json={
                "question": RUN_BODY["question"],
                "parameters": RUN_BODY["parameters"],
                "audience": "internal",
            },
            headers={"X-API-Key": API_KEY},
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]

        internal_report = client.get(
            f"/runs/{trace_id}/report",
            headers={"X-API-Key": API_KEY},
        )
        external_forced_report = client.get(
            f"/runs/{trace_id}/report?audience=internal",
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )

        self.assertEqual(internal_report.status_code, 200, internal_report.text)
        self.assertEqual(external_forced_report.status_code, 200, external_forced_report.text)
        self.assertEqual(internal_report.json()["audience"], "internal")
        self.assertEqual(internal_report.json()["user_result"]["audience"], "internal")
        self.assertEqual(external_forced_report.json()["audience"], "external")
        self.assertEqual(external_forced_report.json()["user_result"]["audience"], "external")
        self.assertEqual(
            internal_report.json()["user_result"]["artifact_id"],
            f"artifact-{trace_id}-internal",
        )
        self.assertEqual(
            external_forced_report.json()["user_result"]["artifact_id"],
            f"artifact-{trace_id}-external",
        )
        self.assertNotEqual(
            internal_report.json()["user_result"]["artifact_id"],
            external_forced_report.json()["user_result"]["artifact_id"],
        )
        self.assertIn("sha256:", internal_report.text)
        self.assertNotIn("sha256:", external_forced_report.text)

    def test_report_read_unknown_snapshot_is_404_and_guarded(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)

        missing_key = client.get("/runs/trace-missing/report")
        missing_snapshot = client.get(
            "/runs/trace-missing/report",
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )

        self.assertEqual(missing_key.status_code, 401)
        self.assertEqual(missing_snapshot.status_code, 404)

    def test_external_api_key_blocked_run_omits_trace_details(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)

        resp = client.post(
            "/runs",
            json={"question": "revenue", "parameters": RUN_BODY["parameters"]},
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )

        self.assertEqual(resp.status_code, 422, resp.text)
        detail = resp.json()["detail"]
        self.assertEqual(detail["code"], "unknown_metric")
        self.assertEqual(detail["details"], [])
        self.assertIsNone(detail["trace_id"])

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
        self.assertEqual(payload["execution_audit"]["durability_scope"], "connector_local_ledger")
        self.assertEqual(payload["execution_audit"]["execution_outcome"], "executed")
        self.assertEqual(payload["execution_audit"]["replay_status"], "not_replayed")
        self.assertEqual(payload["execution_audit"]["external_ack_status"], "not_applicable")
        self.assertIn("connector_executed", [event["step"] for event in payload["events"]])

    def test_approval_execute_traverses_agent_runtime_envelope(self) -> None:
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
        approval_id = run_resp.json()["user_result"]["business_action"]["approval_id"]
        run_writer = client.app.state.agent_runtime_trace_writer

        execute_resp = client.post(
            f"/approvals/{approval_id}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )

        self.assertEqual(execute_resp.status_code, 200, execute_resp.text)
        execute_writer = client.app.state.agent_runtime_trace_writer
        self.assertIsNot(execute_writer, run_writer)
        approval_tool_events = [
            event
            for event in execute_writer.events
            if event["payload"].get("tool_name") == "trusted_loop.approval_execute"
        ]
        approval_tool_steps = [event["step"] for event in approval_tool_events]
        self.assertIn("agent_runtime.policy_allowed", approval_tool_steps)
        self.assertIn("agent_runtime.tool_started", approval_tool_steps)
        self.assertIn("agent_runtime.tool_succeeded", approval_tool_steps)
        self.assertIn("agent_runtime.invocation_finished", approval_tool_steps)

    def test_approval_execute_paused_shell_is_denied_before_connector_write(self) -> None:
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        runtime = factory.build()
        client = TestClient(
            create_app(
                runtime,
                api_key=API_KEY,
                operator_api_key=OPERATOR_KEY,
                adoption_ingest=factory.adoption_ingest(),
            )
        )
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
        approval_id = run_resp.json()["user_result"]["business_action"]["approval_id"]

        factory.corrigibility_shell().op_pause()
        execute_resp = client.post(
            f"/approvals/{approval_id}/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": OPERATOR_KEY},
        )

        self.assertEqual(execute_resp.status_code, 409, execute_resp.text)
        detail = execute_resp.json()["detail"]
        self.assertEqual(detail["code"], "DENY_PAUSED")
        self.assertEqual(detail["approval_id"], approval_id)
        runtime_steps = [
            event["step"] for event in client.app.state.agent_runtime_trace_writer.events
        ]
        self.assertIn("agent_runtime.policy_denied", runtime_steps)
        self.assertNotIn("agent_runtime.tool_started", runtime_steps)
        action_record_connector = client.app.state.runtime.connector_registry.get("action_record")
        self.assertEqual(len(action_record_connector.store.records()), 0)

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
    def test_api_principal_scope_contract_is_explicit(self) -> None:
        import agent_os_api.http_app as http_app

        required_names = [
            "API_PRINCIPAL_INTERNAL",
            "API_PRINCIPAL_EXTERNAL_REPORT",
            "API_PRINCIPAL_OPERATOR",
            "API_SCOPE_RUN_INTERNAL",
            "API_SCOPE_RUN_EXTERNAL",
            "API_SCOPE_OUTCOME_WRITE",
            "API_SCOPE_ADOPTION_WRITE",
            "API_SCOPE_KNOWLEDGE_SEARCH",
            "API_SCOPE_TRACE_READ",
            "API_SCOPE_REPORT_READ",
            "API_SCOPE_APPROVAL_EXECUTE",
            "API_SCOPE_RUNTIME_RESUME",
        ]
        for name in required_names:
            self.assertTrue(hasattr(http_app, name), f"{name} is missing")

        internal = http_app.API_PRINCIPAL_INTERNAL
        external = http_app.API_PRINCIPAL_EXTERNAL_REPORT
        operator = http_app.API_PRINCIPAL_OPERATOR

        self.assertEqual(internal.kind, "internal")
        self.assertEqual(external.kind, "external_report")
        self.assertEqual(operator.kind, "operator")
        self.assertEqual(internal.audience_ceiling, "internal")
        self.assertEqual(external.audience_ceiling, "external")
        self.assertIsNone(operator.audience_ceiling)

        self.assertTrue(internal.allows(http_app.API_SCOPE_RUN_INTERNAL))
        self.assertTrue(internal.allows(http_app.API_SCOPE_RUN_EXTERNAL))
        self.assertTrue(internal.allows(http_app.API_SCOPE_OUTCOME_WRITE))
        self.assertTrue(internal.allows(http_app.API_SCOPE_ADOPTION_WRITE))
        self.assertTrue(internal.allows(http_app.API_SCOPE_KNOWLEDGE_SEARCH))
        self.assertTrue(internal.allows(http_app.API_SCOPE_TRACE_READ))
        self.assertTrue(internal.allows(http_app.API_SCOPE_REPORT_READ))
        self.assertTrue(internal.allows(http_app.API_SCOPE_RUNTIME_RESUME))
        self.assertFalse(internal.allows(http_app.API_SCOPE_APPROVAL_EXECUTE))

        self.assertFalse(external.allows(http_app.API_SCOPE_RUN_INTERNAL))
        self.assertTrue(external.allows(http_app.API_SCOPE_RUN_EXTERNAL))
        self.assertFalse(external.allows(http_app.API_SCOPE_OUTCOME_WRITE))
        self.assertFalse(external.allows(http_app.API_SCOPE_ADOPTION_WRITE))
        self.assertFalse(external.allows(http_app.API_SCOPE_KNOWLEDGE_SEARCH))
        self.assertFalse(external.allows(http_app.API_SCOPE_TRACE_READ))
        self.assertTrue(external.allows(http_app.API_SCOPE_REPORT_READ))
        self.assertFalse(external.allows(http_app.API_SCOPE_RUNTIME_RESUME))
        self.assertFalse(external.allows(http_app.API_SCOPE_APPROVAL_EXECUTE))

        self.assertEqual(operator.scopes, frozenset({http_app.API_SCOPE_APPROVAL_EXECUTE}))

    def test_authorize_principal_scope_returns_403_for_recognized_wrong_role(self) -> None:
        import agent_os_api.http_app as http_app

        self.assertTrue(hasattr(http_app, "authorize_principal_scope"))

        with self.assertRaises(Exception) as captured:
            http_app.authorize_principal_scope(
                http_app.API_PRINCIPAL_EXTERNAL_REPORT,
                http_app.API_SCOPE_OUTCOME_WRITE,
            )
        self.assertEqual(captured.exception.status_code, 403)
        self.assertIn("external_report", captured.exception.detail)
        self.assertIn(http_app.API_SCOPE_OUTCOME_WRITE, captured.exception.detail)

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

    def test_external_report_key_cannot_use_outcomes_route(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        resp = client.post(
            "/outcomes",
            json={"trace_id": "trace-x", "outcome": "adopted"},
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(resp.status_code, 403)

    def test_external_report_key_cannot_use_management_surfaces(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        headers = {"X-API-Key": EXTERNAL_API_KEY}

        adoption_resp = client.post(
            "/adoptions",
            json={"trace_id": "trace-x", "outcome": "adopted"},
            headers=headers,
        )
        search_resp = client.get("/knowledge/search", params={"q": "GMV"}, headers=headers)
        trace_resp = client.get("/traces/trace-x", headers=headers)
        resume_resp = client.post(
            "/agent-runtime/runs/http-run-x/resume",
            json={
                "runtime_trace_id": "agent-trace-x",
                "question": "GMV",
                "parameters": {},
            },
            headers=headers,
        )

        self.assertEqual(adoption_resp.status_code, 403)
        self.assertEqual(search_resp.status_code, 403)
        self.assertEqual(trace_resp.status_code, 403)
        self.assertEqual(resume_resp.status_code, 403)

    def test_external_report_key_cannot_execute_approval_as_operator(self) -> None:
        client = _make_client(API_KEY, external_api_key=EXTERNAL_API_KEY)
        resp = client.post(
            "/approvals/approval-x/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(resp.status_code, 401)

    def test_auth_keys_must_be_distinct(self) -> None:
        with self.assertRaises(ValueError):
            _make_client(API_KEY, external_api_key=API_KEY)

        with self.assertRaises(ValueError):
            _make_client(API_KEY, operator_api_key=API_KEY)

        with self.assertRaises(ValueError):
            _make_client(
                API_KEY, operator_api_key=EXTERNAL_API_KEY, external_api_key=EXTERNAL_API_KEY
            )

    def test_approval_execute_route_also_guarded(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post(
            "/approvals/approval-x/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_unconfigured_operator_key_returns_503(self) -> None:
        client = _make_client(API_KEY, operator_api_key=None)
        resp = client.post(
            "/approvals/approval-x/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": "anything"},
        )
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Operator API key is not configured", resp.json()["detail"])

    def test_approval_execute_wrong_operator_key_is_rejected(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post(
            "/approvals/approval-x/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": "nope"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_operator_key_is_not_valid_on_run_api_key_channel(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post("/runs", json=RUN_BODY, headers={"X-API-Key": OPERATOR_KEY})
        self.assertEqual(resp.status_code, 401)

    def test_internal_key_is_not_valid_on_operator_key_channel(self) -> None:
        client = _make_client(API_KEY)
        resp = client.post(
            "/approvals/approval-x/execute",
            json={"reason": "approved by operator", "approved_by": "ops@example.com"},
            headers={"X-Operator-Key": API_KEY},
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

    @unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
    def test_report_snapshot_survives_fresh_app_on_postgres_backend(self) -> None:
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
        config = RuntimeFactoryConfig(
            domain_pack_path=DOMAIN_PACK,
            store_backend=STORE_POSTGRES,
            store_engine=engine,
        )
        factory1 = ContentCommerceRuntimeFactory(config)
        client1 = TestClient(
            create_app(
                factory1.build(),
                retriever=factory1.build_knowledge_retriever(),
                api_key=API_KEY,
                external_api_key=EXTERNAL_API_KEY,
                adoption_ingest=factory1.adoption_ingest(),
                report_store=factory1.build_report_snapshot_store(),
            )
        )
        run_resp = client1.post(
            "/runs", json={**RUN_BODY, "audience": "internal"}, headers={"X-API-Key": API_KEY}
        )
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        trace_id = run_resp.json()["trace_id"]

        factory2 = ContentCommerceRuntimeFactory(config)
        client2 = TestClient(
            create_app(
                factory2.build(),
                retriever=factory2.build_knowledge_retriever(),
                api_key=API_KEY,
                external_api_key=EXTERNAL_API_KEY,
                adoption_ingest=factory2.adoption_ingest(),
                report_store=factory2.build_report_snapshot_store(),
            )
        )
        internal_resp = client2.get(
            f"/runs/{trace_id}/report",
            params={"audience": "internal"},
            headers={"X-API-Key": API_KEY},
        )
        self.assertEqual(internal_resp.status_code, 200, internal_resp.text)
        external_resp = client2.get(
            f"/runs/{trace_id}/report",
            params={"audience": "internal"},
            headers={"X-API-Key": EXTERNAL_API_KEY},
        )
        self.assertEqual(external_resp.status_code, 200, external_resp.text)
        self.assertEqual(external_resp.json()["user_result"]["redaction"]["audience"], "external")
        self.assertNotEqual(
            internal_resp.json()["user_result"]["artifact_id"],
            external_resp.json()["user_result"]["artifact_id"],
        )

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
    """The DEFAULT app must close the reviewed/value-backed knowledge loop."""

    def _default_client(self):
        from starlette.testclient import TestClient

        from agent_os_api.http_app import create_app

        return TestClient(create_app(api_key=API_KEY))

    def test_default_app_search_consumes_reviewed_knowledge_not_raw_drafts(self) -> None:
        client = self._default_client()
        headers = {"X-API-Key": API_KEY}

        run_resp = client.post("/runs", json=RUN_BODY, headers=headers)
        self.assertEqual(run_resp.status_code, 200, run_resp.text)
        asset_id = run_resp.json()["knowledge_asset_id"]
        self.assertIsNotNone(asset_id)

        search_resp = client.get("/knowledge/search", params={"q": "GMV", "k": 10}, headers=headers)
        self.assertEqual(search_resp.status_code, 200, search_resp.text)
        self.assertEqual(search_resp.json()["results"], [])

        approve_resp = client.post(
            f"/knowledge/review-queue/{asset_id}/decision",
            json={"action": "approve", "reviewer": "founder"},
            headers=headers,
        )
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)

        search_resp = client.get("/knowledge/search", params={"q": "GMV", "k": 10}, headers=headers)
        self.assertEqual(search_resp.status_code, 200, search_resp.text)
        hits = [r["asset_id"] for r in search_resp.json()["results"]]
        self.assertIn(asset_id, hits, "default app search no longer sees reviewed knowledge")

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
        self.assertEqual(second.json()["related_knowledge"], [])

        approve_resp = client.post(
            f"/knowledge/review-queue/{first.json()['knowledge_asset_id']}/decision",
            json={"action": "approve", "reviewer": "founder"},
            headers=headers,
        )
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)

        third = client.post("/runs", json=RUN_BODY, headers=headers)
        related = third.json()["related_knowledge"]
        self.assertTrue(related, "run should recall reviewed prior knowledge")
        self.assertIn(first.json()["knowledge_asset_id"], [r["asset_id"] for r in related])
        self.assertIn("score", related[0])
        self.assertEqual(
            third.json()["user_result"]["decision"].get("knowledge_context_refs"),
            [first.json()["knowledge_asset_id"]],
        )

        external = client.post(
            "/runs",
            json={**RUN_BODY, "audience": "external"},
            headers=headers,
        )
        self.assertEqual(external.status_code, 200, external.text)
        self.assertEqual(
            external.json()["user_result"]["decision"].get("knowledge_context_refs"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
