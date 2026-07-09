"""Tests for the LLM advisor in stub mode."""

from __future__ import annotations

import unittest

from experiments.strong_locus_intervention_advisor import (
    _deterministic_advice,
    _parse_advice,
    advise,
)


class TestInterventionAdvisor(unittest.TestCase):
    def test_stub_proceed(self) -> None:
        gap = {
            "recommendation": {"action": "PROCEED"},
            "missing_intervention_for_observable": [],
        }
        advice = advise(gap, provider="stub")
        self.assertEqual(advice["advised_action"], "PROCEED")
        self.assertEqual(advice["backend"], "deterministic_stub")

    def test_stub_request_interventions(self) -> None:
        gap = {
            "recommendation": {"action": "REQUEST_INTERVENTIONS"},
            "missing_intervention_for_observable": ["ATM", "ATR"],
        }
        advice = advise(gap, provider="stub")
        self.assertEqual(advice["advised_action"], "REQUEST_INTERVENTIONS")
        self.assertIn("ATM", advice["proposed_guides"])
        self.assertEqual(advice["proposed_guides"]["ATM"][:1], ["p_sgATM_1"])
        self.assertEqual(advice["suggested_datasets"], ["GSE190604"])

    def test_stub_pivot_dataset(self) -> None:
        gap = {
            "recommendation": {"action": "PIVOT_DATASET"},
            "missing_intervention_for_observable": [],
        }
        advice = advise(gap, provider="stub")
        self.assertEqual(advice["advised_action"], "PIVOT_DATASET")
        self.assertEqual(advice["suggested_datasets"], ["GSE190604"])

    def test_parse_advice_handles_plumbing_failure(self) -> None:
        parsed = _parse_advice({"_plumbing_failure": "timeout"})
        self.assertEqual(parsed["advised_action"], "HONEST_NEGATIVE")
        self.assertEqual(parsed["backend"], "failed")
        self.assertIn("timeout", parsed["reasoning"])

    def test_parse_advice_handles_valid_json(self) -> None:
        parsed = _parse_advice(
            {
                "advised_action": "REQUEST_INTERVENTIONS",
                "proposed_guides": {"BAX": ["p_sgBAX_1"]},
                "suggested_datasets": ["GSE190604"],
                "reasoning": "Need more interventions.",
            }
        )
        self.assertEqual(parsed["advised_action"], "REQUEST_INTERVENTIONS")
        self.assertEqual(parsed["proposed_guides"]["BAX"], ["p_sgBAX_1"])
        self.assertEqual(parsed["backend"], "llm")


if __name__ == "__main__":
    unittest.main()
