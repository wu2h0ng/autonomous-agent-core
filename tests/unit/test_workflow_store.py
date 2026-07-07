"""WorkflowStorePort durable round-trip tests (workstream D)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_os_contracts import ApprovalWorkflow, WorkflowStep
from agent_os_core.workflow import WorkflowRuntime
from agent_os_core.workflow_store import InMemoryWorkflowStore, WorkflowInstanceRecord
from agent_os_contracts import RuntimeFeatureFlags

ROOT = Path(__file__).resolve().parents[2]


def _sample_workflow() -> ApprovalWorkflow:
    return ApprovalWorkflow(
        workflow_id="wf-gmv",
        name="GMV Approval",
        action_type="execute",
        risk_levels=("R3",),
        state="active",
        steps=(
            WorkflowStep(
                step_id="s1",
                step_type="approval",
                approver_role="manager",
                timeout_seconds=3600,
            ),
        ),
    )


class InMemoryWorkflowStoreTest(unittest.TestCase):
    def test_workflow_and_instance_round_trip(self) -> None:
        store = InMemoryWorkflowStore()
        wf = _sample_workflow()
        store.save_workflow("tenant-a", wf)
        loaded = store.get_workflow("tenant-a", "wf-gmv")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.workflow_id, "wf-gmv")

        from agent_os_contracts import WorkflowInstance

        inst = WorkflowInstance(
            instance_id="wi-1",
            workflow_id="wf-gmv",
            proposal_id="prop-1",
            current_step_id="s1",
            state="pending",
        )
        record = WorkflowInstanceRecord(
            tenant_id="tenant-a",
            instance=inst,
            assigned_role="manager",
            step_started_at="2026-07-07T00:00:00+00:00",
        )
        store.save_instance(record)
        got = store.get_instance("tenant-a", "wi-1")
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.instance.proposal_id, "prop-1")
        self.assertEqual(got.assigned_role, "manager")


class WorkflowRuntimeDurableStoreTest(unittest.TestCase):
    def test_runtime_persists_instance_via_store(self) -> None:
        store = InMemoryWorkflowStore()
        flags = RuntimeFeatureFlags(full_bpm_workflow=True)
        runtime = WorkflowRuntime(flags, workflow_store=store)
        runtime.register_workflow(_sample_workflow(), tenant_id="tenant-a")
        inst = runtime.start_instance("wf-gmv", "prop-99", tenant_id="tenant-a")
        reloaded = WorkflowRuntime(flags, workflow_store=store)
        reloaded.register_workflow(_sample_workflow(), tenant_id="tenant-a")
        got = reloaded._require_instance(inst.instance_id, tenant_id="tenant-a")
        self.assertEqual(got.proposal_id, "prop-99")


class SqlWorkflowStoreTest(unittest.TestCase):
    def test_sqlite_round_trip(self) -> None:
        sys_path = [
            str(ROOT / "packages" / "persistence" / "src"),
            str(ROOT / "packages" / "contracts" / "src"),
            str(ROOT / "packages" / "os_core" / "src"),
        ]
        import sys

        for p in sys_path:
            if p not in sys.path:
                sys.path.insert(0, p)
        from sqlalchemy import create_engine

        from agent_os_persistence import SqlWorkflowStore, create_all

        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine(f"sqlite:///{tmp}/wf.db")
            create_all(engine)
            store = SqlWorkflowStore(engine)
            store.save_workflow("default", _sample_workflow())
            items = store.list_workflows("default")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].workflow_id, "wf-gmv")


if __name__ == "__main__":
    unittest.main()
