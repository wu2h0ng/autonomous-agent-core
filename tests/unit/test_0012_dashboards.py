"""Smoke test for the dashboards Alembic migration."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "packages" / "persistence" / "alembic" / "versions" / "0012_dashboards.py"


class DashboardsMigrationTest(unittest.TestCase):
    def test_migration_declares_revision_chain(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0012_dashboards"', source)
        self.assertIn('down_revision: str | None = "0011_tenants"', source)

    def test_migration_creates_dashboards_table(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('op.create_table(\n        "dashboards"', source)
        for column in ("tenant_id", "dashboard_id", "title", "created_at", "payload"):
            self.assertIn(f'sa.Column("{column}"', source)


if __name__ == "__main__":
    unittest.main()
