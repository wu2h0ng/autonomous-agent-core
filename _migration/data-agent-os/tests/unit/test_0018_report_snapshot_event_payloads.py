"""Migration contract for immutable report payloads and revision serialization."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "packages"
    / "persistence"
    / "alembic"
    / "versions"
    / "0018_report_snapshot_event_payloads.py"
)


class ReportSnapshotEventPayloadsMigrationTest(unittest.TestCase):
    def test_applied_0017_database_upgrades_without_rewriting_legacy_event(self) -> None:
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, inspect, text

        from agent_os_persistence import SqlReportSnapshotStore

        with TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "legacy-0017.sqlite3"
            engine = create_engine(f"sqlite:///{database}")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE alembic_version (
                            version_num VARCHAR(32) NOT NULL PRIMARY KEY
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO alembic_version (version_num) "
                        "VALUES ('0017_report_snapshot_events')"
                    )
                )
                connection.execute(
                    text(
                        """
                        CREATE TABLE report_snapshot_events (
                            sequence INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                            tenant_id VARCHAR NOT NULL,
                            event_id VARCHAR NOT NULL UNIQUE,
                            trace_id VARCHAR NOT NULL,
                            revision INTEGER NOT NULL,
                            report_digest VARCHAR(64) NOT NULL,
                            recorded_at DATETIME NOT NULL,
                            CONSTRAINT uq_report_snapshot_events_tenant_trace_revision
                                UNIQUE (tenant_id, trace_id, revision)
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO report_snapshot_events
                            (tenant_id, event_id, trace_id, revision, report_digest, recorded_at)
                        VALUES
                            ('tenant-a', 'legacy-event', 'trace-a', 3,
                             'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                             '2026-07-16 00:00:00')
                        """
                    )
                )

            # No config file: env.py must not reconfigure/disable application
            # loggers as a side effect of this in-process migration test.
            config = Config()
            config.set_main_option(
                "script_location",
                str(ROOT / "packages" / "persistence" / "alembic"),
            )
            config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
            command.upgrade(config, "0018_report_snapshot_event_payloads")

            columns = {
                column["name"]: column
                for column in inspect(engine).get_columns("report_snapshot_events")
            }
            self.assertIn("report_payload", columns)
            self.assertTrue(columns["report_payload"]["nullable"])
            with engine.connect() as connection:
                legacy = connection.execute(
                    text(
                        "SELECT event_id, report_payload FROM report_snapshot_events "
                        "WHERE event_id = 'legacy-event'"
                    )
                ).one()
                revision_state = connection.execute(
                    text(
                        "SELECT last_revision FROM report_snapshot_event_revisions "
                        "WHERE tenant_id = 'tenant-a' AND trace_id = 'trace-a'"
                    )
                ).scalar_one()
            self.assertEqual(legacy.event_id, "legacy-event")
            self.assertIsNone(legacy.report_payload)
            self.assertEqual(revision_state, 3)
            store = SqlReportSnapshotStore(engine)
            with self.assertRaises(RuntimeError) as raised:
                store.list_events(
                    after_sequence=0,
                    limit=10,
                    tenant_id="tenant-a",
                )
            self.assertEqual(
                str(raised.exception),
                "legacy report event lacks an immutable payload; replay is required",
            )

    def test_migration_extends_0017_without_rewriting_it(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")

        self.assertIn('revision: str = "0018_report_snapshot_event_payloads"', source)
        self.assertIn('down_revision: str | None = "0017_report_snapshot_events"', source)
        self.assertIn('op.add_column(\n        "report_snapshot_events"', source)
        self.assertIn('sa.Column("report_payload", sa.JSON(), nullable=True)', source)
        self.assertIn('op.create_table(\n        "report_snapshot_event_revisions"', source)
        self.assertIn("SELECT tenant_id, trace_id, MAX(revision)", source)

    def test_downgrade_drops_revision_state_then_payload_column(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        downgrade = source.split("def downgrade() -> None:", maxsplit=1)[1]

        self.assertLess(
            downgrade.index('op.drop_table("report_snapshot_event_revisions")'),
            downgrade.index('op.drop_column("report_snapshot_events", "report_payload")'),
        )


if __name__ == "__main__":
    unittest.main()
