from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "packages" / "persistence" / "src" / "agent_os_persistence" / "schema.py"
VERSIONS = ROOT / "packages" / "persistence" / "alembic" / "versions"

# Pure-text check (no sqlalchemy/alembic import) so it gates even bare-env CI.
_TABLE = re.compile(r'Table\(\s*"(\w+)"')
_CREATE = re.compile(r'create_table\(\s*"(\w+)"')


class MigrationsCoverSchemaTest(unittest.TestCase):
    """Every table declared in schema.py must be created by some Alembic migration.

    Guards against the class of defect where a table is added to the SQLAlchemy
    metadata (so create_all/SQLite tests pass) but its migration is never committed,
    leaving Alembic-managed PostgreSQL without the table.
    """

    def test_every_schema_table_has_a_migration(self) -> None:
        schema_tables = set(_TABLE.findall(SCHEMA.read_text(encoding="utf-8")))
        self.assertTrue(schema_tables, "no Table(...) found in schema.py — regex drift?")

        migrated: set[str] = set()
        for path in sorted(VERSIONS.glob("*.py")):
            migrated |= set(_CREATE.findall(path.read_text(encoding="utf-8")))

        missing = schema_tables - migrated
        self.assertEqual(
            missing,
            set(),
            f"schema.py tables with no create_table migration: {sorted(missing)}",
        )

    def test_create_extension_is_guarded_by_availability_check(self) -> None:
        """Optional-extension migrations must not break the chain when the extension
        binaries are absent (verified live: an unguarded CREATE EXTENSION vector rolled
        back the ENTIRE 0001->0004 chain on a PostgreSQL without pgvector installed).
        Any migration that creates an extension must first probe pg_available_extensions.
        """
        for path in sorted(VERSIONS.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "CREATE EXTENSION" in source:
                self.assertIn(
                    "pg_available_extensions",
                    source,
                    f"{path.name} runs CREATE EXTENSION without checking "
                    "pg_available_extensions first — an absent extension would abort "
                    "the whole migration chain",
                )


if __name__ == "__main__":
    unittest.main()
