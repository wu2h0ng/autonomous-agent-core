from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_gate" / "controlled_pilot_readiness_check.py"
CURRENT_STATE = ROOT / "docs" / "CURRENT_STATE.yaml"
CURRENT_VERIFICATION_RECORD = (
    ROOT / "docs" / "decisions" / "PR-23-controlled-pilot-readiness-full-ci-refresh-20260704.md"
)
HOLD_DECISION = ROOT / "docs" / "decisions" / "PR-10-deployment-push-hold-decision-20260704.md"
RC_RECORD = ROOT / "docs" / "decisions" / "PR-15-controlled-pilot-rc-branch-20260704.md"


class ControlledPilotReadinessGateTest(unittest.TestCase):
    def test_current_repository_passes_controlled_pilot_readiness_check(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("controlled pilot readiness passed", result.stdout + result.stderr)
        self.assertIn("DEPLOYMENT_PUSH: HOLD", result.stdout + result.stderr)

    def test_authorized_push_decision_fails_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            decision_file = Path(tmpdir) / "push-authorized.md"
            decision_file.write_text(
                textwrap.dedent(
                    """
                    # Deployment Push Decision

                    ```text
                    DEPLOYMENT_PUSH: AUTHORIZED
                    candidate_head: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
                    ```
                    """
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(ROOT),
                    "--decision-file",
                    str(decision_file),
                    "--expected-head",
                    "a" * 40,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("push must remain HOLD", result.stdout + result.stderr)

    def test_missing_r4_r5_hold_boundary_fails_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            decisions_dir = repo_root / "docs" / "decisions"
            decisions_dir.mkdir(parents=True)
            shutil.copyfile(CURRENT_STATE, repo_root / "docs" / "CURRENT_STATE.yaml")
            shutil.copyfile(
                CURRENT_VERIFICATION_RECORD, decisions_dir / CURRENT_VERIFICATION_RECORD.name
            )

            current_state_path = repo_root / "docs" / "CURRENT_STATE.yaml"
            state_text = current_state_path.read_text(encoding="utf-8")
            current_state_path.write_text(
                state_text.replace(
                    "or expand product/autonomous-core/G10/R4-R5 claims",
                    "or expand product/autonomous-core/G10 claims",
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(repo_root),
                    "--decision-file",
                    str(HOLD_DECISION),
                    "--rc-record-file",
                    str(RC_RECORD),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("R4/R5", result.stdout + result.stderr)

    def test_makefile_exposes_controlled_pilot_readiness_outside_ci(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^controlled-pilot-readiness-check:")
        self.assertIn("controlled_pilot_readiness_check.py", makefile)
        ci_line = next(line for line in makefile.splitlines() if line.startswith("ci:"))
        self.assertNotIn("controlled-pilot-readiness-check", ci_line)

    def test_readme_documents_controlled_pilot_gate_boundaries(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("make controlled-pilot-readiness-check", readme)
        self.assertIn("DEPLOYMENT_PUSH: HOLD", readme)
        self.assertIn("does not authorize origin/main push", readme)
        self.assertIn("does not authorize release", readme)
        self.assertIn("does not authorize automatic R4/R5 execution", readme)


if __name__ == "__main__":
    unittest.main()
