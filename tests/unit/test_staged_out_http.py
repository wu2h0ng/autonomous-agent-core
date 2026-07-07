"""HTTP staged-out management plane tests (ADR-0013)."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from agent_os_api.http_app import create_app
from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig
from agent_os_contracts import RuntimeFeatureFlags
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAIN_PACK = ROOT / "domain_packs" / "content_commerce"


class StagedOutHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AGENT_OS_API_KEY"] = "test-internal-key"
        os.environ["AGENT_OS_OPERATOR_API_KEY"] = "test-operator-key"
        os.environ.pop("AGENT_OS_R4_R5_AUTO_EXECUTION", None)
        os.environ.pop("AGENT_OS_FULL_BPM_WORKFLOW", None)
        os.environ.pop("AGENT_OS_MCP_GATEWAY", None)
        cfg = RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK)
        self.factory = ContentCommerceRuntimeFactory(cfg)
        self.client = TestClient(
            create_app(
                runtime=self.factory.build(),
                api_key="test-internal-key",
                operator_api_key="test-operator-key",
            )
        )
        self.client.app.state.factory = self.factory
        self.headers = {"X-API-Key": "test-internal-key", "X-Tenant-Id": "default"}

    def test_workflow_endpoint_disabled_when_flag_off(self) -> None:
        resp = self.client.get("/workflows", headers=self.headers)
        self.assertEqual(resp.status_code, 503)

    def test_workflow_register_when_flag_on(self) -> None:
        os.environ["AGENT_OS_FULL_BPM_WORKFLOW"] = "true"
        cfg = RuntimeFactoryConfig.from_env(
            {**os.environ, "AGENT_OS_DOMAIN_PACK": str(DOMAIN_PACK)}
        )
        cfg = RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK, full_bpm_workflow=True)
        factory = ContentCommerceRuntimeFactory(cfg)
        client = TestClient(
            create_app(
                runtime=factory.build(),
                api_key="test-internal-key",
                operator_api_key="test-operator-key",
            )
        )
        client.app.state.factory = factory
        resp = client.post(
            "/workflows",
            headers=self.headers,
            json={
                "workflow_id": "wf-test",
                "name": "Test",
                "action_type": "execute",
                "risk_levels": ["R3"],
                "state": "active",
                "steps": [
                    {
                        "step_id": "s1",
                        "step_type": "approval",
                        "approver_role": "manager",
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        listed = client.get("/workflows", headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["workflow_id"], "wf-test")

    def _workflow_client(self) -> TestClient:
        cfg = RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK, full_bpm_workflow=True)
        factory = ContentCommerceRuntimeFactory(cfg)
        client = TestClient(
            create_app(
                runtime=factory.build(),
                api_key="test-internal-key",
                operator_api_key="test-operator-key",
            )
        )
        client.app.state.factory = factory
        return client

    def _register_ops_workflow(self, client: TestClient) -> None:
        resp = client.post(
            "/workflows",
            headers=self.headers,
            json={
                "workflow_id": "wf-ops-http",
                "name": "Ops HTTP",
                "action_type": "execute",
                "risk_levels": ["R3"],
                "state": "active",
                "steps": [
                    {
                        "step_id": "s1",
                        "step_type": "approval",
                        "approver_role": "manager",
                        "timeout_seconds": 0,
                        "next_step_id": "s2",
                        "fallback_step_id": "s2",
                    },
                    {
                        "step_id": "s2",
                        "step_type": "approval",
                        "approver_role": "director",
                    },
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)

    def _start_instance(self, client: TestClient, proposal_id: str) -> str:
        resp = client.post(
            "/workflows/wf-ops-http/instances",
            headers=self.headers,
            json={"proposal_id": proposal_id, "started_by": "http-test"},
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["instance"]["instance_id"]

    def test_workflow_instance_management_endpoints(self) -> None:
        client = self._workflow_client()
        self._register_ops_workflow(client)

        approve_instance = self._start_instance(client, "proposal-approve")
        approved = client.post(
            f"/workflow-instances/{approve_instance}/approve",
            headers=self.headers,
            json={"actor": "manager", "reason": "approved"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["instance"]["current_step_id"], "s2")
        self.assertEqual(approved.json()["instance"]["assigned_role"], "director")

        delegate_instance = self._start_instance(client, "proposal-delegate")
        delegated = client.post(
            f"/workflow-instances/{delegate_instance}/delegate",
            headers=self.headers,
            json={"actor": "manager", "to_role": "backup_manager"},
        )
        self.assertEqual(delegated.status_code, 200)
        self.assertEqual(delegated.json()["instance"]["assigned_role"], "backup_manager")

        reject_instance = self._start_instance(client, "proposal-reject")
        rejected = client.post(
            f"/workflow-instances/{reject_instance}/reject",
            headers=self.headers,
            json={"actor": "manager", "reason": "unsafe"},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["instance"]["state"], "rejected")

        timeout_instance = self._start_instance(client, "proposal-timeout")
        timed_out = client.post(
            f"/workflow-instances/{timeout_instance}/timeout-check",
            headers=self.headers,
            json={"now": "2100-01-01T00:00:00+00:00"},
        )
        self.assertEqual(timed_out.status_code, 200)
        self.assertEqual(timed_out.json()["instance"]["state"], "escalated")
        self.assertEqual(timed_out.json()["instance"]["current_step_id"], "s2")

    def test_workflow_instance_unknown_returns_404(self) -> None:
        client = self._workflow_client()
        resp = client.post(
            "/workflow-instances/missing/approve",
            headers=self.headers,
            json={"actor": "manager"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"]["code"], "WORKFLOW_INSTANCE_NOT_FOUND")

    def test_workflow_endpoint_returns_safe_error_when_factory_missing(self) -> None:
        cfg = RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK, full_bpm_workflow=True)
        factory = ContentCommerceRuntimeFactory(cfg)
        client = TestClient(
            create_app(
                runtime=factory.build(),
                api_key="test-internal-key",
                operator_api_key="test-operator-key",
            )
        )
        resp = client.post(
            "/workflow-instances/missing/approve",
            headers=self.headers,
            json={"actor": "manager"},
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["detail"], "factory not configured")

    def test_workflow_endpoint_returns_safe_error_when_store_missing(self) -> None:
        class StorelessFactory:
            def _runtime_feature_flags(self) -> RuntimeFeatureFlags:
                return RuntimeFeatureFlags(full_bpm_workflow=True)

            def build_workflow_store(self) -> None:
                return None

        client = TestClient(
            create_app(
                runtime=self.factory.build(),
                api_key="test-internal-key",
                operator_api_key="test-operator-key",
            )
        )
        client.app.state.factory = StorelessFactory()
        resp = client.get("/workflows", headers=self.headers)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["detail"]["code"], "STORE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
