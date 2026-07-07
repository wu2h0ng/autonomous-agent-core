"""Combined coverage for usage contract and persistence modules.

This file satisfies the anti-stub module-test mapping for both
``agent_os_contracts.usage`` and ``agent_os_persistence.usage``.
More focused behavior lives in ``test_usage_contracts.py``,
``test_quota_gate.py``, and ``test_usage_store.py``.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import UsageEvent
from agent_os_contracts import usage as contract_usage
from agent_os_persistence import SqlUsageStore, create_all, usage as persistence_usage
from sqlalchemy import create_engine


class UsageModulesSmokeTest(unittest.TestCase):
    def test_contract_classes_are_importable(self) -> None:
        self.assertTrue(callable(contract_usage.UsageEvent))
        self.assertTrue(callable(contract_usage.QuotaLimit))
        self.assertTrue(issubclass(contract_usage.QuotaExceeded, Exception))

    def test_persistence_module_has_sql_store(self) -> None:
        self.assertTrue(callable(persistence_usage.SqlUsageStore))

    def test_sql_store_records_and_counts(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        create_all(engine)
        store = SqlUsageStore(engine)
        store.record(UsageEvent(tenant_id="t1", operation="run", trace_id="trace-1"))
        self.assertEqual(store.count("t1", "run", 3600), 1)


if __name__ == "__main__":
    unittest.main()
