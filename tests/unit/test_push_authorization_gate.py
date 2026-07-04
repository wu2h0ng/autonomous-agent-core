from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_gate" / "push_authorization_check.py"
HOLD_DECISION = ROOT / "docs" / "decisions" / "PR-10-deployment-push-hold-decision-20260704.md"


class PushAuthorizationGateTest(unittest.TestCase):
    def test_current_hold_decision_blocks_push_authorization(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--decision-file", str(HOLD_DECISION)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEPLOYMENT_PUSH: HOLD", result.stdout + result.stderr)
        self.assertIn("not authorized", result.stdout + result.stderr)

    def test_explicit_authorization_record_allows_push_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            decision_file = Path(tmpdir) / "push-authorized.md"
            decision_file.write_text(
                textwrap.dedent(
                    """
                    # Deployment Push Decision

                    ```text
                    DEPLOYMENT_PUSH: AUTHORIZED
                    ```
                    """
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--decision-file", str(decision_file)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DEPLOYMENT_PUSH: AUTHORIZED", result.stdout)

    def test_conflicting_push_decision_tokens_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            decision_file = Path(tmpdir) / "push-ambiguous.md"
            decision_file.write_text(
                textwrap.dedent(
                    """
                    # Deployment Push Decision

                    ```text
                    DEPLOYMENT_PUSH: HOLD
                    DEPLOYMENT_PUSH: AUTHORIZED
                    ```
                    """
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--decision-file", str(decision_file)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stdout + result.stderr)

    def test_authorization_can_be_bound_to_expected_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            decision_file = Path(tmpdir) / "push-authorized.md"
            decision_file.write_text(
                textwrap.dedent(
                    """
                    # Deployment Push Decision

                    ```text
                    DEPLOYMENT_PUSH: AUTHORIZED
                    candidate_head: abc1234
                    ```
                    """
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--decision-file",
                    str(decision_file),
                    "--expected-head",
                    "abc1234",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("candidate_head: abc1234", result.stdout)

    def test_authorization_head_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            decision_file = Path(tmpdir) / "push-authorized.md"
            decision_file.write_text(
                textwrap.dedent(
                    """
                    # Deployment Push Decision

                    ```text
                    DEPLOYMENT_PUSH: AUTHORIZED
                    candidate_head: abc1234
                    ```
                    """
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--decision-file",
                    str(decision_file),
                    "--expected-head",
                    "def5678",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate head mismatch", result.stdout + result.stderr)

    def test_makefile_exposes_push_authorization_check_outside_ci(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^push-authorization-check:")
        self.assertIn("push_authorization_check.py", makefile)
        self.assertIn("PUSH_EXPECTED_HEAD", makefile)
        ci_line = next(line for line in makefile.splitlines() if line.startswith("ci:"))
        self.assertNotIn("push-authorization-check", ci_line)


if __name__ == "__main__":
    unittest.main()
