from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import TelemetryDimension  # noqa: E402
from agent_os_core.trace import TraceRecorder  # noqa: E402


class ObservabilityTest(unittest.TestCase):
    def test_trace_recorder_keeps_trace_and_telemetry_separate(self) -> None:
        recorder = TraceRecorder("trace-test")

        recorder.record("intent", {"metric": "gmv"})
        recorder.metric(
            dimension=TelemetryDimension.BUSINESS,
            name="trusted_loop.run_started",
            value=1,
            unit="count",
        )

        self.assertEqual(len(recorder.events()), 1)
        self.assertEqual(len(recorder.telemetry_events()), 1)
        self.assertEqual(recorder.telemetry_events()[0].dimension, TelemetryDimension.BUSINESS)
        self.assertEqual(recorder.telemetry_events()[0].trace_id, "trace-test")


if __name__ == "__main__":
    unittest.main()
