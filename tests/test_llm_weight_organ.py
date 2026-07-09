"""Contract tests for LLMWeightOrgan — weight proposal parsing and safety."""

from __future__ import annotations

import unittest

from aac.llm_weight_organ import (
    LLMWeightOrgan,
    _parse_weight_vector,
    _parse_confidence,
    SimpleLLMBackend,
)


class WeightParsing(unittest.TestCase):
    def test_parses_valid_vector(self):
        result = _parse_weight_vector([0.5, 0.3, 0.2], 3)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(sum(result), 1.0, places=6)

    def test_normalizes_non_unity_sum(self):
        result = _parse_weight_vector([1.0, 1.0, 1.0], 3)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(sum(result), 1.0, places=6)
        self.assertAlmostEqual(result[0], 1/3, places=4)

    def test_rejects_negative(self):
        self.assertIsNone(_parse_weight_vector([-0.1, 0.5, 0.6], 3))

    def test_rejects_wrong_length(self):
        self.assertIsNone(_parse_weight_vector([0.5, 0.5], 3))

    def test_rejects_non_numeric(self):
        self.assertIsNone(_parse_weight_vector(["a", "b", "c"], 3))

    def test_rejects_none(self):
        self.assertIsNone(_parse_weight_vector(None, 3))

    def test_rejects_zero_sum(self):
        self.assertIsNone(_parse_weight_vector([0.0, 0.0, 0.0], 3))


class ConfidenceParsing(unittest.TestCase):
    def test_valid_confidence(self):
        self.assertAlmostEqual(_parse_confidence(0.7), 0.7)

    def test_clamps_to_range(self):
        self.assertEqual(_parse_confidence(1.5), 1.0)
        self.assertEqual(_parse_confidence(-0.5), 0.0)

    def test_invalid_returns_default(self):
        self.assertEqual(_parse_confidence("high"), 0.5)
        self.assertEqual(_parse_confidence(None), 0.5)


class OrganInterface(unittest.TestCase):
    def test_propose_returns_tuple(self):
        class Stub:
            def propose(self, _p):
                return {"weights": [0.6, 0.2, 0.2], "confidence": 0.8}
        organ = LLMWeightOrgan(backend=Stub(), n_metrics=3, call_interval=1)
        w, c, fresh = organ.propose({"step": 0, "metric_signals": {}, "recent_history": [], "just_shifted": False})
        self.assertIsNotNone(w)
        self.assertAlmostEqual(sum(w), 1.0, places=6)
        self.assertGreater(c, 0.0)
        self.assertTrue(fresh)

    def test_none_weights_on_parse_failure(self):
        class Stub:
            def propose(self, _p):
                return {"weights": [0.5, 0.5], "confidence": 0.5}  # wrong length
        organ = LLMWeightOrgan(backend=Stub(), n_metrics=3, call_interval=1)
        w, c, fresh = organ.propose({"step": 0, "metric_signals": {}, "recent_history": [], "just_shifted": False})
        self.assertIsNone(w)

    def test_caches_proposal(self):
        calls = []
        class Stub:
            def propose(self, _p):
                calls.append(1)
                return {"weights": [0.5, 0.3, 0.2], "confidence": 0.7}
        organ = LLMWeightOrgan(backend=Stub(), n_metrics=3, call_interval=10)
        w1, _, fresh1 = organ.propose({"step": 0, "metric_signals": {}, "recent_history": [], "just_shifted": False})
        w2, _, fresh2 = organ.propose({"step": 1, "metric_signals": {}, "recent_history": [], "just_shifted": False})
        self.assertEqual(calls, [1])  # only one real call, second uses cache
        self.assertTrue(fresh1)
        self.assertFalse(fresh2)
        self.assertIsNotNone(w1)
        self.assertIsNotNone(w2)


if __name__ == "__main__":
    unittest.main()
