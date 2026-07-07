from __future__ import annotations

import importlib.util
import unittest

_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed (install .[postgres])")
class SchemaTenantIsolationTest(unittest.TestCase):
    """Every persistence table is tenant-scoped via an indexed tenant_id column."""

    def test_every_table_has_tenant_id_column(self) -> None:
        from agent_os_persistence.schema import (
            action_records,
            agent_runtime_checkpoints,
            approval_operation_contexts,
            approval_records,
            feedback_events,
            knowledge_assets,
            knowledge_index,
            report_snapshots,
            run_traces,
            state_snapshots,
            usage_events,
        )

        tables = [
            feedback_events,
            knowledge_assets,
            state_snapshots,
            agent_runtime_checkpoints,
            report_snapshots,
            action_records,
            approval_records,
            approval_operation_contexts,
            knowledge_index,
            run_traces,
            usage_events,
        ]
        for table in tables:
            self.assertIn(
                "tenant_id",
                table.c,
                f"table '{table.name}' is missing tenant_id column",
            )

    def test_natural_key_tables_include_tenant_id_in_primary_key(self) -> None:
        from agent_os_persistence.schema import (
            agent_runtime_checkpoints,
            approval_operation_contexts,
            approval_records,
            knowledge_assets,
            report_snapshots,
            run_traces,
            state_snapshots,
        )

        for table in (
            knowledge_assets,
            state_snapshots,
            agent_runtime_checkpoints,
            approval_records,
            approval_operation_contexts,
            run_traces,
            report_snapshots,
        ):
            pk_columns = {c.name for c in table.primary_key.columns}
            self.assertIn(
                "tenant_id",
                pk_columns,
                f"table '{table.name}' must include tenant_id in its primary key",
            )


if __name__ == "__main__":
    unittest.main()
