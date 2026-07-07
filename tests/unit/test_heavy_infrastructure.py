"""Heavy infrastructure contract tests (ADR-0013 workstream G)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import (  # noqa: E402
    TemporalScheduleRequest,
    TemporalScheduleResult,
)


class HeavyInfrastructureContractsTest(unittest.TestCase):
    def test_temporal_schedule_result_dataclass(self) -> None:
        req = TemporalScheduleRequest(
            workflow_type="approval",
            task_queue="default",
            workflow_id="wf-1",
            input_payload={"k": "v"},
        )
        self.assertEqual(req.workflow_id, "wf-1")
        res = TemporalScheduleResult(workflow_id="wf-1", status="disabled")
        self.assertEqual(res.status, "disabled")


if __name__ == "__main__":
    unittest.main()
