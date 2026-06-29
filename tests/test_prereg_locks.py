"""Refuse-on-drift gate for frozen prereg locks (ADR-0031 PRED1).

Fails loudly if any file in a prereg lock-set is mutated such that the recorded
prereg_hash no longer reproduces -- closing the gate-integrity gap where prereg_hash()
was a print/record utility, not an enforced gate.
"""
import json
import unittest
from pathlib import Path

from experiments.prediction1_residual_calibrator import prereg_hash


class TestPreregLockNoDrift(unittest.TestCase):
    def test_pred1_prereg_lock_reproduces(self) -> None:
        lock = json.loads(Path("experiments/prediction1_residual_calibrator.lock.json").read_text())
        self.assertEqual(
            prereg_hash(),
            lock["prereg_hash"],
            "PRED1 prereg lock drift: a locked mechanism file changed; "
            "re-run the r-final to confirm the verdict still holds, then re-lock with justification.",
        )


if __name__ == "__main__":
    unittest.main()
