from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_gate" / "current_state_verification_check.py"
CURRENT_STATE = ROOT / "docs" / "CURRENT_STATE.yaml"


def _current_verification_source() -> str:
    current_state = yaml.safe_load(CURRENT_STATE.read_text(encoding="utf-8"))
    return current_state["last_verified_tests"]["source"]


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
                    _current_verification_source(),
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

    def test_absolute_verification_source_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            docs_dir = repo_root / "docs"
            docs_dir.mkdir(parents=True)
            shutil.copyfile(CURRENT_STATE, docs_dir / "CURRENT_STATE.yaml")
            state_path = docs_dir / "CURRENT_STATE.yaml"
            state_text = state_path.read_text(encoding="utf-8")
            state_path.write_text(
                state_text.replace(
                    _current_verification_source(),
                    "/tmp/outside-verification-record.md",
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
        self.assertIn("outside repository", result.stdout + result.stderr)

    def test_non_string_verification_source_fails_closed_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            docs_dir = repo_root / "docs"
            docs_dir.mkdir(parents=True)
            shutil.copyfile(CURRENT_STATE, docs_dir / "CURRENT_STATE.yaml")
            state_path = docs_dir / "CURRENT_STATE.yaml"
            current_state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            current_state["last_verified_tests"]["source"] = ["not", "a", "path"]
            current_state["last_verified_eval"]["source"] = ["not", "a", "path"]
            state_path.write_text(yaml.safe_dump(current_state), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(repo_root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verification source invalid", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_tests_and_eval_source_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            docs_dir = repo_root / "docs"
            decisions_dir = docs_dir / "decisions"
            decisions_dir.mkdir(parents=True)
            shutil.copyfile(CURRENT_STATE, docs_dir / "CURRENT_STATE.yaml")
            state_path = docs_dir / "CURRENT_STATE.yaml"
            current_state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
            current_state["last_verified_eval"]["source"] = (
                "docs/decisions/DIFFERENT-verification-record.md"
            )
            state_path.write_text(yaml.safe_dump(current_state), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(repo_root)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verification source mismatch", result.stdout + result.stderr)

    def test_verification_source_without_verified_head_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            docs_dir = repo_root / "docs"
            decisions_dir = docs_dir / "decisions"
            decisions_dir.mkdir(parents=True)
            shutil.copyfile(CURRENT_STATE, docs_dir / "CURRENT_STATE.yaml")
            source_path = decisions_dir / "NO-HEAD-verification-record.md"
            source_path.write_text(
                "# Verification Record\n\nThis record has no verified-head marker.\n",
                encoding="utf-8",
            )
            state_path = docs_dir / "CURRENT_STATE.yaml"
            state_text = state_path.read_text(encoding="utf-8")
            state_path.write_text(
                state_text.replace(
                    _current_verification_source(),
                    "docs/decisions/NO-HEAD-verification-record.md",
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
        self.assertIn("has no verified head", result.stdout + result.stderr)

    def test_makefile_exposes_current_state_verification_check_outside_ci(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^current-state-verification-check:")
        self.assertIn("current_state_verification_check.py", makefile)
        ci_line = next(line for line in makefile.splitlines() if line.startswith("ci:"))
        self.assertNotIn("current-state-verification-check", ci_line)


if __name__ == "__main__":
    unittest.main()
