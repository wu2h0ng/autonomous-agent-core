from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_api.outcome_service import TrustedLoopCorrectionRuntimeAdapter  # noqa: E402
from agent_os_api.runtime_factory import (  # noqa: E402
    ContentCommerceRuntimeFactory,
    RuntimeFactoryConfig,
)
from agent_os_contracts import FeedbackSource  # noqa: E402
from agent_os_core.agent_runtime import (  # noqa: E402
    AgentRunContext,
    AgentToolCall,
    AgentTraceWriter,
    InMemoryCheckpointStore,
)

DOMAIN_PACK = Path("domain_packs/content_commerce")


def _context(**overrides: object) -> AgentRunContext:
    values = {
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "principal_id": "internal",
        "principal_role": "internal",
        "run_id": "run-correction",
        "trace_id": "agent-trace-correction",
        "policy_scope": frozenset({"trusted_loop:record_outcome"}),
        "risk_ceiling": "R1",
        "metadata": {"surface": "test"},
    }
    values.update(overrides)
    return AgentRunContext(**values)


def _factory() -> ContentCommerceRuntimeFactory:
    return ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))


class AgentRuntimeCorrectionChannelTest(unittest.TestCase):
    def test_record_outcome_missing_permission_denies_before_feedback_write(self) -> None:
        factory = _factory()
        runtime = factory.build()
        trace_writer = AgentTraceWriter()
        adapter = TrustedLoopCorrectionRuntimeAdapter(
            runtime,
            adoption_ingest=factory.adoption_ingest(),
            trace_writer=trace_writer,
        )

        result = adapter.record_outcome(
            context=_context(policy_scope=frozenset()),
            trace_id="trace-missing-record",
            outcome="adopted",
            reviewer="ops@example.com",
            metric_deltas={"gmv": 1000.0},
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_MISSING_PERMISSION")
        self.assertEqual(runtime.feedback_store.get_by_trace("trace-missing-record"), ())
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.policy_denied", steps)
        self.assertNotIn("agent_runtime.tool_started", steps)

    def test_attest_adoption_missing_permission_denies_before_value_write(self) -> None:
        factory = _factory()
        runtime = factory.build()
        trace_writer = AgentTraceWriter()
        adapter = TrustedLoopCorrectionRuntimeAdapter(
            runtime,
            adoption_ingest=factory.adoption_ingest(),
            trace_writer=trace_writer,
        )

        result = adapter.attest_adoption(
            context=_context(policy_scope=frozenset(), risk_ceiling="R2"),
            trace_id="trace-missing-adoption",
            outcome="adopted",
            reviewer="ops@example.com",
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error_code, "DENY_MISSING_PERMISSION")
        self.assertEqual(runtime.adoption_for_trace("trace-missing-adoption"), ())
        steps = [event["step"] for event in trace_writer.events]
        self.assertIn("agent_runtime.policy_denied", steps)
        self.assertNotIn("agent_runtime.tool_started", steps)

    def test_correction_channel_side_effects_run_without_generic_approval_when_scoped(self) -> None:
        factory = _factory()
        runtime = factory.build()
        adapter = TrustedLoopCorrectionRuntimeAdapter(
            runtime,
            adoption_ingest=factory.adoption_ingest(),
            trace_writer=AgentTraceWriter(),
        )

        outcome_result = adapter.record_outcome(
            context=_context(),
            trace_id="trace-correction-self-report",
            outcome="adopted",
            reviewer="ops@example.com",
        )
        adoption_result = adapter.attest_adoption(
            context=_context(
                policy_scope=frozenset({"trusted_loop:attest_adoption"}),
                risk_ceiling="R2",
            ),
            trace_id="trace-correction-adoption",
            outcome="adopted",
            reviewer="ops@example.com",
        )

        self.assertEqual(outcome_result.status, "ok")
        self.assertEqual(adoption_result.status, "ok")
        self.assertEqual(outcome_result.output["knowledge_version"], 0)
        self.assertEqual(adoption_result.output["knowledge_version"], 0)
        self.assertEqual(
            len(runtime.feedback_store.get_by_trace("trace-correction-self-report")), 1
        )
        self.assertEqual(len(runtime.adoption_for_trace("trace-correction-adoption")), 1)

    def test_self_report_checkpoint_cannot_replay_as_external_adoption(self) -> None:
        factory = _factory()
        runtime = factory.build()
        checkpoints = InMemoryCheckpointStore()
        adapter = TrustedLoopCorrectionRuntimeAdapter(
            runtime,
            adoption_ingest=factory.adoption_ingest(),
            checkpoint_store=checkpoints,
            trace_writer=AgentTraceWriter(),
        )
        record_context = _context(
            run_id="run-replay-correction",
            policy_scope=frozenset({"trusted_loop:record_outcome"}),
            risk_ceiling="R1",
        )

        first = adapter.record_outcome(
            context=record_context,
            trace_id="trace-replay-correction",
            outcome="adopted",
            reviewer="ops@example.com",
        )
        resumed = adapter.runtime.resume_from_checkpoint(
            AgentToolCall(
                call_id="trusted_loop.attest_adoption:run-replay-correction",
                tool_name=TrustedLoopCorrectionRuntimeAdapter.ATTEST_ADOPTION_TOOL_NAME,
                args={
                    "trace_id": "trace-replay-correction",
                    "outcome": "adopted",
                    "reviewer": "ops@example.com",
                    "metric_deltas": None,
                    "causal_attribution": None,
                },
            ),
            _context(
                run_id="run-replay-correction",
                policy_scope=frozenset({"trusted_loop:attest_adoption"}),
                risk_ceiling="R2",
            ),
        )

        self.assertEqual(first.status, "ok")
        self.assertEqual(resumed.status, "validation_error")
        self.assertEqual(resumed.error_code, "CHECKPOINT_MISMATCH")
        self.assertEqual(len(runtime.feedback_store.get_by_trace("trace-replay-correction")), 1)
        self.assertEqual(runtime.adoption_for_trace("trace-replay-correction"), ())

    def test_record_outcome_cannot_write_external_adoption_channel(self) -> None:
        factory = _factory()
        runtime = factory.build()
        adapter = TrustedLoopCorrectionRuntimeAdapter(
            runtime,
            adoption_ingest=factory.adoption_ingest(),
            trace_writer=AgentTraceWriter(),
        )

        result = adapter.record_outcome(
            context=_context(),
            trace_id="trace-record-is-not-adoption",
            outcome="adopted",
            reviewer="ops@example.com",
            metric_deltas={"gmv": 1200.0},
        )

        self.assertEqual(result.status, "ok")
        feedback_events = runtime.feedback_store.get_by_trace("trace-record-is-not-adoption")
        self.assertEqual(len(feedback_events), 1)
        self.assertEqual(feedback_events[0].source, FeedbackSource.RUNTIME_SELF_REPORT)
        self.assertEqual(runtime.adoption_for_trace("trace-record-is-not-adoption"), ())

    def test_unknown_trace_correction_records_without_fabricating_knowledge_asset(self) -> None:
        factory = _factory()
        runtime = factory.build()
        adapter = TrustedLoopCorrectionRuntimeAdapter(
            runtime,
            adoption_ingest=factory.adoption_ingest(),
            trace_writer=AgentTraceWriter(),
        )

        outcome_result = adapter.record_outcome(
            context=_context(),
            trace_id="trace-unknown-correction",
            outcome="rejected",
            reviewer="ops@example.com",
        )
        adoption_result = adapter.attest_adoption(
            context=_context(
                policy_scope=frozenset({"trusted_loop:attest_adoption"}),
                risk_ceiling="R2",
            ),
            trace_id="trace-unknown-adoption",
            outcome="adopted",
            reviewer="ops@example.com",
        )

        self.assertEqual(outcome_result.status, "ok")
        self.assertEqual(outcome_result.output["knowledge_asset_id"], None)
        self.assertEqual(outcome_result.output["knowledge_version"], 0)
        self.assertEqual(len(runtime.feedback_store.get_by_trace("trace-unknown-correction")), 1)
        self.assertIsNone(runtime.knowledge_store.get_by_trace("trace-unknown-correction"))

        self.assertEqual(adoption_result.status, "ok")
        self.assertEqual(adoption_result.output["knowledge_asset_id"], None)
        self.assertEqual(adoption_result.output["knowledge_version"], 0)
        self.assertEqual(runtime.knowledge_store.version_of("trace-unknown-adoption"), 0)
        self.assertEqual(len(runtime.adoption_for_trace("trace-unknown-adoption")), 1)
        self.assertIsNone(runtime.knowledge_store.get_by_trace("trace-unknown-adoption"))


if __name__ == "__main__":
    unittest.main()
