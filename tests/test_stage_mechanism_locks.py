"""Refuse-on-drift locks for the Stage-1..5 mechanism files (RR-0037 O4).

Same discipline as the PRED1 lock (boundary #23): if a locked mechanism file changes,
this test fails loudly; the fix is NEVER to delete the test — re-run the mechanism's
formal-model gates/battery to confirm verdicts still hold, then re-lock with a dated
justification in the lock JSON (see the PRED1 re-lock precedent, 2026-06-30/07-03).
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

LOCK = Path("experiments/stage_mechanism.lock.json")
FILES = (
    "src/aac/belief_ledger.py",
    "src/aac/failure_attributor.py",
    "src/aac/conflict_detector.py",
    "src/aac/evidence_assembly.py",
    "src/aac/goal_system.py",
    "src/aac/write_authority.py",
    "src/aac/planner.py",
)


def mechanism_hash() -> str:
    blob = "\n\n".join(f"--- {p} ---\n{Path(p).read_text(encoding='utf-8')}" for p in FILES)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class StageMechanismLock(unittest.TestCase):
    def test_lock_reproduces(self):
        lock = json.loads(LOCK.read_text())
        self.assertEqual(sorted(lock["files"]), sorted(FILES))
        self.assertEqual(
            mechanism_hash(), lock["mechanism_hash"],
            "Stage mechanism drift: a locked file changed; re-run that mechanism's "
            "formal-model gates/battery, then re-lock with justification (never tune to pass).")


if __name__ == "__main__":
    unittest.main()
