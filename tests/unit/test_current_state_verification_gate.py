from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_gate" / "current_state_verification_check.py"
CURRENT_STATE = ROOT / "docs" / "CURRENT_STATE.yaml"


class CurrentStateVerificationGateTest(unittest.TestCase):
    def test_current_repository_state_passes_verification_source_check(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CURRENT_STATE verification source check passed", result.stdout)

    def test_missing_verification_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            docs_dir = repo_root / "docs"
            decisions_dir = docs_dir / "decisions"
            decisions_dir.mkdir(parents=True)
            shutil.copyfile(CURRENT_STATE, docs_dir / "CURRENT_STATE.yaml")
            state_path = docs_dir / "CURRENT_STATE.yaml"
            state_text = state_path.read_text(encoding="utf-8")
            state_path.write_text(
                state_text.replace(
                    "docs/decisions/PR-13-deployment-current-docs-head-verification-refresh-20260704.md",
                    "docs/decisions/MISSING-verification-record.md",
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(repo_root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verification source missing", result.stdout + result.stderr)

    def test_makefile_exposes_current_state_verification_check_outside_ci(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^current-state-verification-check:")
        self.assertIn("current_state_verification_check.py", makefile)
        ci_line = next(line for line in makefile.splitlines() if line.startswith("ci:"))
        self.assertNotIn("current-state-verification-check", ci_line)


if __name__ == "__main__":
    unittest.main()
