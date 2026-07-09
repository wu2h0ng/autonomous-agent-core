"""Tests for the CSV real-data intervention adapter."""
from __future__ import annotations

import os
import tempfile
import unittest

from adapters.csv_adapter import CSVInterventionAdapter


class CSVAdapterTest(unittest.TestCase):
    def _write_csv(self, path: str, rows: list[list[float]], header: list[str] | None = None) -> None:
        with open(path, "w", newline="") as f:
            if header is None:
                header = ["x0", "x1", "x2"]
            f.write(",".join(header) + "\n")
            for row in rows:
                f.write(",".join(str(v) for v in row) + "\n")

    def test_observe_returns_last_n_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "obs.csv")
            self._write_csv(path, [[i, i + 1, i + 2] for i in range(10)])
            adapter = CSVInterventionAdapter(
                n_nodes=3,
                observed_variables=["x0", "x1", "x2"],
                allowed_handles={0, 1},
                safe_value_ranges={0: (-2.0, 2.0), 1: (-1.0, 1.0)},
                observation_path=path,
            )
            obs = adapter.observe(3)
            self.assertEqual(obs, [[7.0, 8.0, 9.0], [8.0, 9.0, 10.0], [9.0, 10.0, 11.0]])

    def test_intervene_logs_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = os.path.join(tmp, "obs.csv")
            log_path = os.path.join(tmp, "interventions.csv")
            self._write_csv(obs_path, [[0.0, 0.0, 0.0]])
            adapter = CSVInterventionAdapter(
                n_nodes=3,
                observed_variables=["x0", "x1", "x2"],
                allowed_handles={0},
                safe_value_ranges={0: (-2.0, 2.0)},
                observation_path=obs_path,
                intervention_log_path=log_path,
            )
            sample = adapter.intervene(0, 1.5)
            self.assertIsNone(sample)
            with open(log_path) as f:
                lines = f.read().strip().split("\n")
            self.assertEqual(lines[0], "sequence,node,value")
            self.assertEqual(lines[1], "1,0,1.5")

    def test_intervene_returns_matching_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = os.path.join(tmp, "obs.csv")
            rb_path = os.path.join(tmp, "readback.csv")
            self._write_csv(obs_path, [[0.0, 0.0, 0.0]])
            self._write_csv(rb_path, [[0, 1.5, 1.5, 0.0, 0.0]], header=["node", "value", "x0", "x1", "x2"])
            adapter = CSVInterventionAdapter(
                n_nodes=3,
                observed_variables=["x0", "x1", "x2"],
                allowed_handles={0},
                safe_value_ranges={0: (-2.0, 2.0)},
                observation_path=obs_path,
                readback_path=rb_path,
            )
            sample = adapter.intervene(0, 1.5)
            self.assertEqual(sample, [1.5, 0.0, 0.0])

    def test_shd_with_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "obs.csv")
            self._write_csv(path, [[0.0, 0.0, 0.0]])
            adapter = CSVInterventionAdapter(
                n_nodes=3,
                observed_variables=["x0", "x1", "x2"],
                allowed_handles=set(),
                safe_value_ranges={},
                observation_path=path,
                ground_truth_edges={(0, 1), (1, 2)},
            )
            self.assertEqual(adapter.structural_hamming_distance({(0, 2)}), 3)


if __name__ == "__main__":
    unittest.main()
