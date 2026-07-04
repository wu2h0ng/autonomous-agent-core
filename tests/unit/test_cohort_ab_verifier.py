"""MetricCohortABVerifier — the REAL cohort A/B verifier (M4 remainder, RR-0033 §M4 DoD).

Tests-first (Hard Rule: no pseudo implementation): the verifier must compute a real
standardized-mean-difference over cohort rows from the OS query path, refuse on malformed/
thin data, and expose (is_effective, confidence, evidence_count) for verify_candidates().
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in ("packages/contracts/src", "packages/os_core/src"):
    sys.path.insert(0, str(ROOT / _p))

from agent_os_contracts import QueryResult  # noqa: E402
from agent_os_core.governance_decision_seam import MetricCohortABVerifier  # noqa: E402


def _rows(a_vals, b_vals):
    rows = [{"cohort": "A", "metric": v} for v in a_vals]
    rows += [{"cohort": "B", "metric": v} for v in b_vals]
    return QueryResult(rows=tuple(rows), row_count=len(rows))


class RealEffectComputation(unittest.TestCase):
    def test_strong_effect_is_effective_with_confidence_and_evidence(self):
        v = MetricCohortABVerifier(
            lambda action: _rows([10.0] * 8 + [11.0] * 4, [1.0] * 8 + [2.0] * 4)
        )
        eff, conf, ev = v.verify("lever:promo")
        self.assertTrue(eff)
        self.assertGreaterEqual(conf, 0.5)
        self.assertEqual(ev, 12)  # min(nA, nB) samples bound as evidence

    def test_null_effect_is_not_effective(self):
        vals = [5.0, 6.0, 5.5, 6.5, 5.2, 6.1, 5.8, 6.3]
        v = MetricCohortABVerifier(lambda action: _rows(vals, list(reversed(vals))))
        eff, conf, ev = v.verify("lever:noop")
        self.assertFalse(eff)
        self.assertEqual(conf, 0.0)

    def test_thin_samples_refuse_not_effective(self):
        v = MetricCohortABVerifier(lambda action: _rows([10.0], [1.0]))  # n<min_samples
        eff, conf, ev = v.verify("lever:thin")
        self.assertFalse(eff)  # never confident on 1-vs-1
        self.assertEqual(ev, 0)

    def test_malformed_rows_fail_closed(self):
        bad = QueryResult(rows=({"cohort": "A"}, {"metric": 3.0}), row_count=2)
        v = MetricCohortABVerifier(lambda action: bad)
        eff, conf, ev = v.verify("lever:bad")
        self.assertFalse(eff)
        self.assertEqual((conf, ev), (0.0, 0))

    def test_query_error_fails_closed(self):
        def boom(action):
            raise RuntimeError("provider down")

        eff, conf, ev = MetricCohortABVerifier(boom).verify("lever:x")
        self.assertFalse(eff)
        self.assertEqual((conf, ev), (0.0, 0))

    def test_deterministic(self):
        v = MetricCohortABVerifier(lambda action: _rows([10, 10, 10, 9], [1, 2, 1, 2]))
        self.assertEqual(v.verify("a"), v.verify("a"))


if __name__ == "__main__":
    unittest.main()
