"""S1a guard — LLM organ wall-clock cap + typed refusal (RR-0037 S1a; ADR-0047 hang lesson).

Failing-first: LLMPriorOrgan must never hang the loop. A slow/raising backend degrades to
a REFUSAL advice (empty delta, uncertainty 1.0, reason recorded) within the cap; the
governed loop then proceeds on its own belief — organ absence, never organ blockage.
"""
from __future__ import annotations

import time
import unittest

from aac.prior_organ import BeliefSnapshot
from aac.prior_organ_llm import LLMPriorOrgan


def _snap(n=4):
    return BeliefSnapshot(mu=(0.0,) * n, uncertainty=(1.0,) * n, last_surprise=0.0)


class HangBackend:
    def propose(self, prompt):
        time.sleep(5.0)
        return {"belief_delta": {0: 0.2}, "uncertainty": 0.1}


class RaiseBackend:
    def propose(self, prompt):
        raise RuntimeError("provider exploded")


class GoodBackend:
    def propose(self, prompt):
        return {"belief_delta": {1: 0.2}, "uncertainty": 0.3}


class WallClockCapAndRefusal(unittest.TestCase):
    def test_hang_degrades_to_refusal_within_cap(self):
        organ = LLMPriorOrgan(backend=HangBackend(), wall_clock_cap_s=0.3)
        t0 = time.monotonic()
        advice = organ.advise({"regime": 0}, _snap())
        self.assertLess(time.monotonic() - t0, 2.0)          # returned, not hung
        self.assertEqual(advice.belief_delta, {})            # refusal = no information
        self.assertEqual(advice.uncertainty, 1.0)
        self.assertEqual(organ.last_refusal_reason, "wall-clock cap exceeded")

    def test_raise_degrades_to_refusal(self):
        organ = LLMPriorOrgan(backend=RaiseBackend(), wall_clock_cap_s=1.0)
        advice = organ.advise({"regime": 0}, _snap())
        self.assertEqual(advice.belief_delta, {})
        self.assertEqual(advice.uncertainty, 1.0)
        self.assertIn("RuntimeError", organ.last_refusal_reason)

    def test_healthy_backend_unaffected(self):
        organ = LLMPriorOrgan(backend=GoodBackend(), wall_clock_cap_s=1.0)
        advice = organ.advise({"regime": 0}, _snap())
        self.assertEqual(set(advice.belief_delta), {1})
        self.assertIsNone(organ.last_refusal_reason)


if __name__ == "__main__":
    unittest.main()
