from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_gate" / "rc_branch_verification_check.py"


class RcBranchVerificationGateTest(unittest.TestCase):
    def test_record_matches_remote_heads_and_absent_release_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            record_file = tmp / "PR-15.md"
            heads_file = tmp / "heads.txt"
            tags_file = tmp / "tags.txt"
            record_file.write_text(
                textwrap.dedent(
                    """
                    # RC Record

                    - Verified local head: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
                    - RC branch: `rc/phase-1-controlled-pilot-20260704`
                    - RC branch head: `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`
                    - Remote main head: `cccccccccccccccccccccccccccccccccccccccc`
                    """
                ),
                encoding="utf-8",
            )
            heads_file.write_text(
                textwrap.dedent(
                    """
                    bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/heads/rc/phase-1-controlled-pilot-20260704
                    cccccccccccccccccccccccccccccccccccccccc\trefs/heads/main
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            tags_file.write_text("", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--record-file",
                    str(record_file),
                    "--heads-file",
                    str(heads_file),
                    "--tags-file",
                    str(tags_file),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RC branch verification passed", result.stdout)

    def test_rc_branch_head_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            record_file = tmp / "PR-15.md"
            heads_file = tmp / "heads.txt"
            record_file.write_text(
                textwrap.dedent(
                    """
                    # RC Record

                    - Verified local head: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
                    - RC branch: `rc/phase-1-controlled-pilot-20260704`
                    - RC branch head: `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`
                    - Remote main head: `cccccccccccccccccccccccccccccccccccccccc`
                    """
                ),
                encoding="utf-8",
            )
            heads_file.write_text(
                textwrap.dedent(
                    """
                    dddddddddddddddddddddddddddddddddddddddd\trefs/heads/rc/phase-1-controlled-pilot-20260704
                    cccccccccccccccccccccccccccccccccccccccc\trefs/heads/main
                    """
                ).lstrip(),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--record-file",
                    str(record_file),
                    "--heads-file",
                    str(heads_file),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RC branch head mismatch", result.stdout + result.stderr)

    def test_release_tag_on_candidate_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            record_file = tmp / "PR-15.md"
            heads_file = tmp / "heads.txt"
            tags_file = tmp / "tags.txt"
            record_file.write_text(
                textwrap.dedent(
                    """
                    # RC Record

                    - Verified local head: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
                    - RC branch: `rc/phase-1-controlled-pilot-20260704`
                    - RC branch head: `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`
                    - Remote main head: `cccccccccccccccccccccccccccccccccccccccc`
                    """
                ),
                encoding="utf-8",
            )
            heads_file.write_text(
                textwrap.dedent(
                    """
                    bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/heads/rc/phase-1-controlled-pilot-20260704
                    cccccccccccccccccccccccccccccccccccccccc\trefs/heads/main
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            tags_file.write_text(
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/tags/release-20260704\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--record-file",
                    str(record_file),
                    "--heads-file",
                    str(heads_file),
                    "--tags-file",
                    str(tags_file),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release tag exists", result.stdout + result.stderr)

    def test_makefile_exposes_rc_branch_verification_outside_ci(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^rc-branch-verification-check:")
        self.assertIn("rc_branch_verification_check.py", makefile)
        ci_line = next(line for line in makefile.splitlines() if line.startswith("ci:"))
        self.assertNotIn("rc-branch-verification-check", ci_line)


if __name__ == "__main__":
    unittest.main()
