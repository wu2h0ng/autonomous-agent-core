"""Workstream G heavy infrastructure adapter tests (ADR-0013)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_api.heavy_infra_adapters import build_heavy_infrastructure_adapters  # noqa: E402
from agent_os_contracts import (  # noqa: E402
    OpPolicyEvaluationRequest,
    RuntimeFeatureFlags,
    TemporalScheduleRequest,
    TrinoExplainRequest,
)


class HeavyInfrastructureAdapterTest(unittest.TestCase):
    def test_all_disabled_when_flags_off(self) -> None:
        adapters = build_heavy_infrastructure_adapters(RuntimeFeatureFlags())
        temporal = adapters.temporal.schedule(
            TemporalScheduleRequest(
                workflow_type="approval",
                task_queue="default",
                workflow_id="wf-1",
                input_payload={},
            )
        )
        self.assertEqual(temporal.status, "disabled")
        opa = adapters.opa.evaluate(
            OpPolicyEvaluationRequest(policy_path="agentos/r4", input_document={})
        )
        self.assertEqual(opa.status, "disabled")
        trino = adapters.trino.explain(
            TrinoExplainRequest(sql="select 1", catalog="hive", schema="default")
        )
        self.assertEqual(trino.status, "disabled")

    def test_flag_on_returns_not_configured_error(self) -> None:
        flags = RuntimeFeatureFlags(
            temporal_orchestration=True,
            opa_external_policy=True,
            trino_federation=True,
        )
        adapters = build_heavy_infrastructure_adapters(flags)
        self.assertEqual(
            adapters.temporal.schedule(
                TemporalScheduleRequest(
                    workflow_type="a",
                    task_queue="q",
                    workflow_id="id",
                    input_payload={},
                )
            ).status,
            "error",
        )
        self.assertEqual(
            adapters.opa.evaluate(
                OpPolicyEvaluationRequest(policy_path="p", input_document={})
            ).status,
            "error",
        )
        self.assertEqual(
            adapters.trino.explain(
                TrinoExplainRequest(sql="select 1", catalog="c", schema="s")
            ).status,
            "error",
        )


if __name__ == "__main__":
    unittest.main()
