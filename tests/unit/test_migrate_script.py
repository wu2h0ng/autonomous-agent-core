from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class MigrateScriptTest(unittest.TestCase):
    def test_migrate_script_exists_and_is_executable(self) -> None:
        script = ROOT / "scripts" / "migrate.sh"
        self.assertTrue(script.exists(), "migrate.sh must exist")
        self.assertTrue(script.stat().st_mode & 0o111, "migrate.sh must be executable")

    def test_migrate_script_dry_run_prints_expected_command(self) -> None:
        script = ROOT / "scripts" / "migrate.sh"
        result = subprocess.run(
            [str(script), "--dry"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("alembic", result.stdout)
        self.assertIn("packages/persistence/alembic.ini", result.stdout)
        self.assertIn("upgrade head", result.stdout)


if __name__ == "__main__":
    unittest.main()
