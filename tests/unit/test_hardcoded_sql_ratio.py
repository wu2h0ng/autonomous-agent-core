"""Gate: the data-product path must keep hard-coded SQL at or below 30%.

A high ratio means the runtime is drifting away from reviewable domain-pack
contracts (``metrics.json`` / ``sql_templates.json``) toward embedded string
literals. This test fails closed if that drift crosses the threshold.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "hardcoded_sql_ratio.py"


class HardcodedSqlRatioTest(unittest.TestCase):
    def test_hardcoded_sql_ratio_is_at_or_below_threshold(self) -> None:
        env = {"PYTHONPATH": str(ROOT)}
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--json"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        import json

        payload = json.loads(result.stdout)
        self.assertTrue(payload["passed"])
        self.assertLessEqual(payload["ratio"], payload["threshold"])
        self.assertGreater(payload["verified_sql_count"], 0)


if __name__ == "__main__":
    unittest.main()
