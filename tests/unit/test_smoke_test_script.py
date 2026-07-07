from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SmokeTestScriptTest(unittest.TestCase):
    def test_smoke_test_script_exists_and_is_executable(self) -> None:
        script = ROOT / "scripts" / "smoke-test.sh"
        self.assertTrue(script.exists(), "smoke-test.sh must exist")
        self.assertTrue(script.stat().st_mode & 0o111, "smoke-test.sh must be executable")

    def test_smoke_test_script_parses(self) -> None:
        script = ROOT / "scripts" / "smoke-test.sh"
        result = subprocess.run(
            ["bash", "-n", str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_smoke_test_script_checks_staged_out_default_off(self) -> None:
        script = (ROOT / "scripts" / "smoke-test.sh").read_text(encoding="utf-8")
        self.assertIn("staged-out management plane", script)
        self.assertIn("/workflows correctly disabled", script)


if __name__ == "__main__":
    unittest.main()
