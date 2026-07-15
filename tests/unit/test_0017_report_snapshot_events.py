"""Migration contract for the append-only external report event feed."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT / "packages" / "persistence" / "alembic" / "versions" / "0017_report_snapshot_events.py"
)


class ReportSnapshotEventsMigrationTest(unittest.TestCase):
    def test_migration_extends_current_head_and_creates_feed_table(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")

        self.assertIn('revision: str = "0017_report_snapshot_events"', source)
        self.assertIn(
            'down_revision: str | None = "0016_legacy_table_tenant_scoping"',
            source,
        )
        self.assertIn('op.create_table(\n        "report_snapshot_events"', source)
        self.assertIn("uq_report_snapshot_events_tenant_trace_revision", source)

    def test_downgrade_removes_indexes_before_feed_table(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        downgrade = source.split("def downgrade() -> None:", maxsplit=1)[1]

        self.assertLess(
            downgrade.index('op.drop_index(\n        "ix_report_snapshot_events_trace_id"'),
            downgrade.index('op.drop_table("report_snapshot_events")'),
        )
        self.assertLess(
            downgrade.index('op.drop_index(\n        "ix_report_snapshot_events_tenant_id"'),
            downgrade.index('op.drop_table("report_snapshot_events")'),
        )


if __name__ == "__main__":
    unittest.main()
