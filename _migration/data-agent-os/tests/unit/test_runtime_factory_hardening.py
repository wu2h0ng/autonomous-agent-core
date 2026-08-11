"""Runtime factory hardening: trace sink, SDK manifest convergence, flag defaults."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api_server" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "sdk" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "persistence" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_api.runtime_factory import (  # noqa: E402
    ContentCommerceRuntimeFactory,
    RuntimeFactoryConfig,
)
from agent_os_contracts import ApprovalWorkflow, RunTrace, WorkflowStep  # noqa: E402

DOMAIN_PACK = ROOT / "domain_packs" / "content_commerce"


def _two_step_workflow() -> ApprovalWorkflow:
    return ApprovalWorkflow(
        workflow_id="wf-hardening",
        name="Hardening",
        action_type="execute",
        risk_levels=("R3",),
        state="active",
        steps=(
            WorkflowStep(
                step_id="s1",
                step_type="approval",
                approver_role="manager",
                next_step_id="s2",
            ),
            WorkflowStep(
                step_id="s2",
                step_type="approval",
                approver_role="director",
            ),
        ),
    )


class RuntimeFactoryHardeningTest(unittest.TestCase):
    def test_from_env_staged_out_flags_default_off(self) -> None:
        env = {
            "AGENT_OS_DOMAIN_PACK": str(DOMAIN_PACK),
            "AGENT_OS_EXECUTOR": "static",
            "AGENT_OS_STORE_BACKEND": "memory",
        }
        cfg = RuntimeFactoryConfig.from_env(env)
        self.assertFalse(cfg.r4_r5_auto_execution)
        self.assertFalse(cfg.full_bpm_workflow)
        self.assertFalse(cfg.mcp_gateway)

    def test_shared_trace_store_is_singleton_per_factory(self) -> None:
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        self.assertIs(factory.build_trace_store(), factory.build_trace_store())
        runtime = factory.build()
        self.assertIs(runtime.trace_store, factory.build_trace_store())

    def test_load_domain_pack_manifest_via_sdk(self) -> None:
        factory = ContentCommerceRuntimeFactory(RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK))
        manifest = factory.load_domain_pack_manifest()
        self.assertEqual(manifest.pack_id, "content_commerce")
        self.assertIn("gmv", manifest.metric_contracts)

    def test_workflow_trace_sink_appends_to_run_trace(self) -> None:
        factory = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=DOMAIN_PACK, full_bpm_workflow=True)
        )
        trace_store = factory.build_trace_store()
        trace_store.save(RunTrace(trace_id="prop-trace-1", status="ok", events=()))
        wf = factory.build_workflow_runtime()
        assert wf is not None
        wf.register_workflow(_two_step_workflow())
        inst = wf.start_instance("wf-hardening", "prop-trace-1")
        wf.approve_step(inst.instance_id, "manager-1")
        stored = trace_store.get("prop-trace-1")
        assert stored is not None
        steps = [e.step for e in stored.events]
        self.assertIn("workflow.started", steps)
        self.assertIn("workflow.approved", steps)

    def test_postgres_workflow_store_survives_factory_rebuild(self) -> None:
        import tempfile

        from sqlalchemy import create_engine

        from agent_os_persistence import create_all

        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{tmp}/wf.db")
            create_all(engine)
            cfg = RuntimeFactoryConfig(
                domain_pack_path=DOMAIN_PACK,
                full_bpm_workflow=True,
                store_backend="postgres",
                store_engine=engine,
            )
            factory_a = ContentCommerceRuntimeFactory(cfg)
            wf_a = factory_a.build_workflow_runtime()
            assert wf_a is not None
            wf_a.register_workflow(_two_step_workflow(), tenant_id="tenant-a")
            inst = wf_a.start_instance(
                "wf-hardening", "prop-sqlite", tenant_id="tenant-a", started_by="test"
            )

            factory_b = ContentCommerceRuntimeFactory(cfg)
            wf_b = factory_b.build_workflow_runtime()
            assert wf_b is not None
            wf_b.register_workflow(_two_step_workflow(), tenant_id="tenant-a")
            reloaded = wf_b._require_instance(inst.instance_id, tenant_id="tenant-a")
            self.assertEqual(reloaded.proposal_id, "prop-sqlite")


if __name__ == "__main__":
    unittest.main()
