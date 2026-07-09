"""Queue adapter for the RealDataInterventionEnv protocol.

This adapter lives outside the core runtime.  It is intended for bounded tests and
local integration harnesses where an external producer feeds observations and a
consumer applies interventions.  The adapter never executes an action itself: it
puts a request on ``intervene_request_queue`` and waits for a response on
``readback_queue``.
"""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class QueueInterventionAdapter:
    """Read observations and stage interventions through Python queues.

    Args:
        n_nodes: number of observed variables.
        observed_variables: human-readable variable names.
        allowed_handles: node indices that may be intervened upon.
        safe_value_ranges: per-node ``(min, max)`` value bounds.
        observe_queue: queue of observation rows (each row is a list[float]).
        intervene_request_queue: queue where intervention requests are published.
        readback_queue: queue from which post-intervention samples are consumed.
        timeout: seconds to wait for a read-back sample.
        ground_truth_edges: optional ground-truth DAG for evaluation only.
    """

    n_nodes: int
    observed_variables: list[str]
    allowed_handles: set[int]
    safe_value_ranges: dict[int, tuple[float, float]]
    observe_queue: queue.Queue
    intervene_request_queue: queue.Queue
    readback_queue: queue.Queue
    timeout: float = 5.0
    ground_truth_edges: set[tuple[int, int]] | None = None

    def observe(self, n_samples: int) -> list[list[float]]:
        """Drain ``n_samples`` rows from the observation queue."""
        rows: list[list[float]] = []
        deadline = time.monotonic() + self.timeout
        while len(rows) < n_samples:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"observe queue timeout: got {len(rows)}/{n_samples} rows"
                )
            try:
                row = self.observe_queue.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(
                    f"observe queue timeout: got {len(rows)}/{n_samples} rows"
                )
            if not isinstance(row, list) or len(row) != self.n_nodes:
                continue
            try:
                rows.append([float(v) for v in row])
            except (TypeError, ValueError):
                continue
        return rows

    def intervene(self, do_node: int, do_value: float) -> list[float] | None:
        """Publish a request and wait for the external consumer's read-back."""
        self.intervene_request_queue.put(
            {"node": do_node, "value": do_value}
        )
        try:
            sample = self.readback_queue.get(timeout=self.timeout)
        except queue.Empty:
            return None
        if not isinstance(sample, list) or len(sample) != self.n_nodes:
            return None
        try:
            return [float(v) for v in sample]
        except (TypeError, ValueError):
            return None

    def structural_hamming_distance(
        self, predicted: set[tuple[int, int]]
    ) -> int | None:
        if self.ground_truth_edges is None:
            return None
        truth = self.ground_truth_edges
        return len((truth - predicted) | (predicted - truth))
