"""Migration smoke test for 0014 staged-out durable stores."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "packages" / "persistence" / "alembic" / "versions" / "0014_staged_out_stores.py"


class StagedOutStoresMigrationTest(unittest.TestCase):
    def test_migration_chain(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0014_staged_out_stores"', source)
        self.assertIn('down_revision: str | None = "0013_policy_approval_records"', source)

    def test_migration_creates_three_tables(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        for table in ("approval_workflows", "workflow_instances", "auto_execution_policies"):
            self.assertIn(f'"{table}"', source)


if __name__ == "__main__":
    unittest.main()
