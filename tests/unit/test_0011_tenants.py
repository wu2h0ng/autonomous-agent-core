"""Unit test for the 0011_tenants Alembic migration."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = ROOT / "packages" / "persistence" / "alembic" / "versions" / "0011_tenants.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0011", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TenantsMigrationTest(unittest.TestCase):
    def test_migration_module_has_revision_metadata(self) -> None:
        module = _load_migration()
        self.assertEqual(module.revision, "0011_tenants")
        self.assertEqual(module.down_revision, "0010_usage_events")
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

    def test_upgrade_creates_tenants_table(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            self._run_migration(conn, "upgrade")
        inspector = inspect(engine)
        self.assertIn("tenants", inspector.get_table_names())
        columns = {c["name"] for c in inspector.get_columns("tenants")}
        for required in {
            "tenant_id",
            "display_name",
            "status",
            "created_at",
            "updated_at",
            "config",
        }:
            self.assertIn(required, columns)

    def test_downgrade_drops_tenants_table(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            self._run_migration(conn, "upgrade")
            self._run_migration(conn, "downgrade")
        inspector = inspect(engine)
        self.assertNotIn("tenants", inspector.get_table_names())


if __name__ == "__main__":
    unittest.main()
