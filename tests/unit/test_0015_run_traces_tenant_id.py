"""Unit test for the 0015_run_traces_tenant_id Alembic migration."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, JSON, MetaData, PrimaryKeyConstraint, String, Table, create_engine, inspect

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    ROOT
    / "packages"
    / "persistence"
    / "alembic"
    / "versions"
    / "0015_run_traces_tenant_id.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0015", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunTracesTenantIdMigrationTest(unittest.TestCase):
    def test_migration_module_has_revision_metadata(self) -> None:
        module = _load_migration()
        self.assertEqual(module.revision, "0015_run_traces_tenant_id")
        self.assertEqual(module.down_revision, "0014_staged_out_stores")
        self.assertTrue(callable(module.upgrade))
        self.assertTrue(callable(module.downgrade))

    def _run_migration(self, conn, direction: str) -> None:
        module = _load_migration()
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        import alembic.op as alembic_op

        original_op = getattr(alembic_op, "_proxy", None)
        alembic_op._proxy = op
        try:
            if direction == "upgrade":
                module.upgrade()
            else:
                module.downgrade()
        finally:
            if original_op is None:
                delattr(alembic_op, "_proxy")
            else:
                alembic_op._proxy = original_op

    def _create_legacy_run_traces(self, conn) -> None:
        metadata = MetaData()
        Table(
            "run_traces",
            metadata,
            Column("trace_id", String, primary_key=True),
            Column("status", String, nullable=False),
            Column("payload", JSON, nullable=False),
            PrimaryKeyConstraint("trace_id", name="run_traces_pkey"),
        )
        metadata.create_all(conn)

    def test_upgrade_adds_tenant_id_composite_pk(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            self._create_legacy_run_traces(conn)
            self._run_migration(conn, "upgrade")
        inspector = inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("run_traces")}
        self.assertIn("tenant_id", columns)
        pk = inspector.get_pk_constraint("run_traces")
        self.assertEqual(set(pk["constrained_columns"]), {"tenant_id", "trace_id"})

    def test_downgrade_restores_trace_id_only_pk(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            self._create_legacy_run_traces(conn)
            self._run_migration(conn, "upgrade")
            self._run_migration(conn, "downgrade")
        inspector = inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("run_traces")}
        self.assertNotIn("tenant_id", columns)
        pk = inspector.get_pk_constraint("run_traces")
        self.assertEqual(pk["constrained_columns"], ["trace_id"])


if __name__ == "__main__":
    unittest.main()
