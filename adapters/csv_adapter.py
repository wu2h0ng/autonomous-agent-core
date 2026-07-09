"""CSV adapter for the RealDataInterventionEnv protocol.

This adapter lives outside the core runtime.  It reads observational data from a
CSV file and writes intervention requests to a log file.  Read-back samples can
be supplied through a separate read-back CSV.  In production the log file would
be consumed by an external actuator; the adapter itself never executes an action.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CSVInterventionAdapter:
    """Read observations and stage interventions through CSV files.

    Args:
        n_nodes: number of observed variables.
        observed_variables: human-readable variable names.
        allowed_handles: node indices that may be intervened upon.
        safe_value_ranges: per-node ``(min, max)`` value bounds.
        observation_path: CSV file with one header row and numeric columns.
        intervention_log_path: optional CSV file to append intervention requests.
        readback_path: optional CSV file containing post-intervention samples.
            Expected columns: ``node``, ``value``, plus one column per variable.
        ground_truth_edges: optional ground-truth DAG for evaluation only.
    """

    n_nodes: int
    observed_variables: list[str]
    allowed_handles: set[int]
    safe_value_ranges: dict[int, tuple[float, float]]
    observation_path: str
    intervention_log_path: str | None = None
    readback_path: str | None = None
    ground_truth_edges: set[tuple[int, int]] | None = None
    _sequence: int = field(default=0, init=False)

    def _read_rows(self, path: str, n_samples: int | None = None) -> list[list[float]]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"CSV adapter cannot read {path}")
        rows: list[list[float]] = []
        with open(path, newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return []
            for row in reader:
                if len(row) < self.n_nodes:
                    continue
                try:
                    rows.append([float(v) for v in row[: self.n_nodes]])
                except ValueError:
                    continue
                if n_samples is not None and len(rows) >= n_samples:
                    break
        return rows

    def observe(self, n_samples: int) -> list[list[float]]:
        """Return the most recent ``n_samples`` observational rows."""
        rows = self._read_rows(self.observation_path)
        if len(rows) < n_samples:
            raise ValueError(
                f"observation file has {len(rows)} rows, requested {n_samples}"
            )
        return rows[-n_samples:]

    def intervene(self, do_node: int, do_value: float) -> list[float] | None:
        """Log the intervention request and optionally return a read-back sample.

        The read-back CSV is keyed by ``(node, value)`` rounded to one decimal
        place.  If no matching read-back row exists, the adapter returns ``None``,
        signalling that the external actuator has not yet supplied a result.
        """
        self._sequence += 1
        if self.intervention_log_path is not None:
            _ensure_file(self.intervention_log_path)
            with open(self.intervention_log_path, "a", newline="") as f:
                writer = csv.writer(f)
                if os.path.getsize(self.intervention_log_path) == 0:
                    writer.writerow(["sequence", "node", "value"])
                writer.writerow([self._sequence, do_node, round(do_value, 4)])

        if self.readback_path is None or not os.path.exists(self.readback_path):
            return None
        return self._lookup_readback(do_node, do_value)

    def _lookup_readback(self, do_node: int, do_value: float) -> list[float] | None:
        target_node = str(do_node)
        target_value = round(do_value, 1)
        best: list[float] | None = None
        with open(self.readback_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    node = int(row["node"])
                    value = round(float(row["value"]), 1)
                except (KeyError, ValueError):
                    continue
                if node == do_node and abs(value - target_value) < 0.001:
                    try:
                        sample = [float(row[name]) for name in self.observed_variables]
                    except (KeyError, ValueError):
                        sample = [
                            float(row[str(i)]) for i in range(self.n_nodes)
                        ]
                    best = sample
        return best

    def structural_hamming_distance(
        self, predicted: set[tuple[int, int]]
    ) -> int | None:
        if self.ground_truth_edges is None:
            return None
        truth = self.ground_truth_edges
        return len((truth - predicted) | (predicted - truth))


def _ensure_file(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            pass
