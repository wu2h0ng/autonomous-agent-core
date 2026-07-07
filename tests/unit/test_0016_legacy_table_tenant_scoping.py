"""Migration smoke test for 0016 legacy table tenant scoping."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "packages"
    / "persistence"
    / "alembic"
    / "versions"
    / "0016_legacy_table_tenant_scoping.py"
)


class LegacyTableTenantScopingMigrationTest(unittest.TestCase):
    def test_migration_chain(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0016_legacy_table_tenant_scoping"', source)
        self.assertIn('down_revision: str | None = "0015_run_traces_tenant_id"', source)

    def test_migration_touches_legacy_tables(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        for table in (
            "approval_records",
            "knowledge_assets",
            "feedback_events",
            "report_snapshots",
        ):
            self.assertIn(f'"{table}"', source)


if __name__ == "__main__":
    unittest.main()
