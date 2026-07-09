"""Tests for the queue real-data intervention adapter."""
from __future__ import annotations

import queue
import unittest

from adapters.queue_adapter import QueueInterventionAdapter


class QueueAdapterTest(unittest.TestCase):
    def _make(self) -> tuple[QueueInterventionAdapter, queue.Queue, queue.Queue, queue.Queue]:
        obs_q: queue.Queue = queue.Queue()
        req_q: queue.Queue = queue.Queue()
        rb_q: queue.Queue = queue.Queue()
        adapter = QueueInterventionAdapter(
            n_nodes=3,
            observed_variables=["x0", "x1", "x2"],
            allowed_handles={0},
            safe_value_ranges={0: (-2.0, 2.0)},
            observe_queue=obs_q,
            intervene_request_queue=req_q,
            readback_queue=rb_q,
            timeout=0.5,
        )
        return adapter, obs_q, req_q, rb_q

    def test_observe_drains_queue(self) -> None:
        adapter, obs_q, _req_q, _rb_q = self._make()
        for i in range(5):
            obs_q.put([float(i), float(i), float(i)])
        rows = adapter.observe(3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1], [2.0, 2.0, 2.0])

    def test_intervene_publishes_request_and_reads_back(self) -> None:
        adapter, _obs_q, req_q, rb_q = self._make()

        def consumer():
            req = req_q.get(timeout=1.0)
            rb_q.put([req["value"], 0.0, 0.0])

        import threading
        t = threading.Thread(target=consumer)
        t.start()
        sample = adapter.intervene(0, 0.75)
        t.join()
        self.assertEqual(sample, [0.75, 0.0, 0.0])

    def test_intervene_returns_none_on_timeout(self) -> None:
        adapter, _obs_q, _req_q, _rb_q = self._make()
        self.assertIsNone(adapter.intervene(0, 0.5))


if __name__ == "__main__":
    unittest.main()
