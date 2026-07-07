"""Smoke test for the policy_approval_records Alembic migration (workstream E).

Follows the established ``test_001*_*.py`` pattern: assert the migration file
declares a correct revision chain and creates the durable policy-approval
ledger table with the columns the durable store depends on. The actual
SQLite/PostgreSQL round-trip is covered by ``test_sql_policy_approval_store``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT / "packages" / "persistence" / "alembic" / "versions" / "0013_policy_approval_records.py"
)


class PolicyApprovalRecordsMigrationTest(unittest.TestCase):
    def test_migration_declares_revision_chain(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('revision: str = "0013_policy_approval_records"', source)
        self.assertIn('down_revision: str | None = "0012_dashboards"', source)

    def test_migration_creates_policy_approval_records_table(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('op.create_table(\n        "policy_approval_records"', source)
        for column in ("tenant_id", "record_id", "proposal_id", "status", "payload"):
            self.assertIn(f'sa.Column("{column}"', source)

    def test_migration_has_composite_primary_key_and_proposal_index(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        # Composite PK on (tenant_id, record_id) keeps records tenant-scoped.
        self.assertEqual(source.count("primary_key=True"), 2)
        # proposal_id / policy_version / status are indexed for lifecycle lookups.
        self.assertIn("index=True", source)
        # Downgrade reverses the table so migrations stay reversible.
        self.assertIn("def downgrade()", source)
        self.assertIn('op.drop_table("policy_approval_records"', source)


if __name__ == "__main__":
    unittest.main()
