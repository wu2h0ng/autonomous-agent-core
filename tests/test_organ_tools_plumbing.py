"""Tests that organ_tools arms record plumbing counts correctly."""

from __future__ import annotations

import sys
import unittest
from typing import Any, Mapping

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

from aac.organ_tools import run_organ_tools
from aac.organ_tools_externalized import run_organ_tools_externalized
from aac.plumbing_instrument import PlumbingInstrument
from scm_generator import generate_scm, SCMConfig


class _TruncatedBackend:
    """Forces a truncated plumbing event but returns a usable tool call."""

    instrument: PlumbingInstrument | None = None

    def call(
        self, prompt: str, tools: list[dict[str, Any]] | None = None
    ) -> Mapping[str, Any]:
        if self.instrument is not None:
            self.instrument.log_truncated("truncated_backend", "forced truncated")
        return {"tool_call": {"name": "info_gain", "arguments": {}}}


class _UnparseableBackend:
    """Returns a response that organ_tools cannot parse."""

    instrument: PlumbingInstrument | None = None

    def call(
        self, prompt: str, tools: list[dict[str, Any]] | None = None
    ) -> Mapping[str, Any]:
        if self.instrument is not None:
            self.instrument.log_unparseable("unparseable_backend", "forced unparseable")
        return {"not_tool_call": "garbage"}


class _FinalAnswerBackend:
    """Returns final_answer.edges immediately."""

    instrument: PlumbingInstrument | None = None

    def call(
        self, prompt: str, tools: list[dict[str, Any]] | None = None
    ) -> Mapping[str, Any]:
        return {"final_answer": {"edges": [[0, 1, 0.9], [1, 2, 0.7]]}}


class _ExternalizedFinalBackend:
    """Externalized backend returning final edges."""

    instrument: PlumbingInstrument | None = None

    def decide(
        self,
        ledger_summary: Mapping[str, Any],
        candidate_interventions: Mapping[int, list[float]],
    ) -> Mapping[str, Any]:
        return {"final_answer": {"edges": [[0, 1, 0.85]]}}


class TestOrganToolsPlumbing(unittest.TestCase):
    def setUp(self) -> None:
        self.world = generate_scm(SCMConfig(n_nodes=5, n_obs=100, seed=42))
        self.all_keys = list(self.world.interventions.keys())

    def _consultable(self) -> dict[tuple[int, float], list[list[float]]]:
        return {k: self.world.interventions[k] for k in self.all_keys[: len(self.all_keys) // 2]}

    def test_truncated_response_records_count(self) -> None:
        instr = PlumbingInstrument(run_id="trunc", arm="organ_tools")
        backend = _TruncatedBackend()
        result = run_organ_tools(
            self.world.observational,
            self._consultable(),
            budget=3,
            backend=backend,
            instrument=instr,
            n_particles=10,
            seed=42,
        )
        self.assertGreaterEqual(result.plumbing_counts.get("truncated", 0), 1)
        self.assertTrue(instr.has_plumbing_failure())

    def test_unparseable_response_records_count(self) -> None:
        instr = PlumbingInstrument(run_id="unparse", arm="organ_tools")
        backend = _UnparseableBackend()
        result = run_organ_tools(
            self.world.observational,
            self._consultable(),
            budget=3,
            backend=backend,
            instrument=instr,
            n_particles=10,
            seed=42,
        )
        self.assertGreaterEqual(result.plumbing_counts.get("unparseable", 0), 1)
        self.assertTrue(instr.has_plumbing_failure())

    def test_final_answer_edges_parsed(self) -> None:
        instr = PlumbingInstrument(run_id="final", arm="organ_tools")
        backend = _FinalAnswerBackend()
        result = run_organ_tools(
            self.world.observational,
            self._consultable(),
            budget=3,
            backend=backend,
            instrument=instr,
            n_particles=10,
            seed=42,
        )
        self.assertFalse(instr.has_plumbing_failure())
        self.assertIn((0, 1), result.edge_scores)
        self.assertIn((1, 2), result.edge_scores)
        self.assertGreater(result.edge_scores[(0, 1)], 0.0)


class TestOrganToolsExternalizedPlumbing(unittest.TestCase):
    def setUp(self) -> None:
        self.world = generate_scm(SCMConfig(n_nodes=5, n_obs=100, seed=42))
        self.all_keys = list(self.world.interventions.keys())

    def _consultable(self) -> dict[tuple[int, float], list[list[float]]]:
        return {k: self.world.interventions[k] for k in self.all_keys[: len(self.all_keys) // 2]}

    def test_externalized_final_answer_edges(self) -> None:
        instr = PlumbingInstrument(run_id="ext_final", arm="organ_tools_externalized")
        backend = _ExternalizedFinalBackend()
        result = run_organ_tools_externalized(
            self.world.observational,
            self._consultable(),
            budget=3,
            backend=backend,
            instrument=instr,
            n_particles=10,
            seed=42,
        )
        self.assertFalse(instr.has_plumbing_failure())
        self.assertIn((0, 1), result.edge_scores)
        self.assertGreater(result.edge_scores[(0, 1)], 0.0)
        self.assertIn("plumbing_counts", result.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
