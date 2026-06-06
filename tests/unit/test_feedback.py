from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import FeedbackEvent  # noqa: E402
from agent_os_core.feedback import FeedbackEventBuilder, FeedbackStore  # noqa: E402


class FeedbackEventBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = FeedbackEventBuilder()

    def test_build_produces_typed_feedback_event_reflecting_inputs(self) -> None:
        event = self.builder.build(
            trace_id="trace-42",
            outcome="adopted",
            reviewer="analyst@corp",
            metric_deltas={"gmv": 1200.5, "conversion": 0.03},
        )
        self.assertIsInstance(event, FeedbackEvent)
        self.assertEqual(event.trace_id, "trace-42")
        self.assertEqual(event.outcome, "adopted")
        self.assertEqual(event.reviewer, "analyst@corp")
        self.assertEqual(event.metrics, {"gmv": 1200.5, "conversion": 0.03})

    def test_feedback_id_is_deterministic_for_same_inputs(self) -> None:
        first = self.builder.build(trace_id="trace-1", outcome="useful")
        second = self.builder.build(trace_id="trace-1", outcome="useful")
        self.assertEqual(first.feedback_id, second.feedback_id)

    def test_feedback_id_derives_from_trace_and_content_not_constant(self) -> None:
        base = self.builder.build(trace_id="trace-1", outcome="useful")
        other_trace = self.builder.build(trace_id="trace-2", outcome="useful")
        other_outcome = self.builder.build(trace_id="trace-1", outcome="rejected")
        other_metrics = self.builder.build(
            trace_id="trace-1", outcome="useful", metric_deltas={"gmv": 1.0}
        )
        # All four ids must differ because the derivation reflects every input.
        ids = {
            base.feedback_id,
            other_trace.feedback_id,
            other_outcome.feedback_id,
            other_metrics.feedback_id,
        }
        self.assertEqual(len(ids), 4)

    def test_empty_trace_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.builder.build(trace_id="", outcome="useful")

    def test_empty_outcome_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.builder.build(trace_id="trace-1", outcome="")


class FeedbackStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = FeedbackEventBuilder()
        self.store = FeedbackStore()

    def test_record_and_retrieve_by_trace_id(self) -> None:
        event = self.builder.build(trace_id="trace-1", outcome="useful")
        self.store.record(event)
        retrieved = self.store.get_by_trace("trace-1")
        self.assertEqual(retrieved, (event,))

    def test_retrieve_unknown_trace_returns_empty(self) -> None:
        self.assertEqual(self.store.get_by_trace("missing"), ())

    def test_multiple_events_for_same_trace_are_kept_in_order(self) -> None:
        first = self.builder.build(trace_id="trace-1", outcome="useful")
        second = self.builder.build(trace_id="trace-1", outcome="rejected")
        self.store.record(first)
        self.store.record(second)
        self.assertEqual(self.store.get_by_trace("trace-1"), (first, second))

    def test_outcome_counts_aggregate_across_traces(self) -> None:
        self.store.record(self.builder.build(trace_id="t1", outcome="adopted"))
        self.store.record(self.builder.build(trace_id="t2", outcome="adopted"))
        self.store.record(self.builder.build(trace_id="t3", outcome="rejected"))
        counts = self.store.outcome_counts()
        self.assertEqual(counts, {"adopted": 2, "rejected": 1})

    def test_all_events_returns_everything_recorded(self) -> None:
        e1 = self.builder.build(trace_id="t1", outcome="adopted")
        e2 = self.builder.build(trace_id="t2", outcome="rejected")
        self.store.record(e1)
        self.store.record(e2)
        self.assertEqual(self.store.all_events(), (e1, e2))


if __name__ == "__main__":
    unittest.main()
