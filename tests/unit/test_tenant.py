from __future__ import annotations

import unittest

from agent_os_core import InMemoryTenantStore, TenantStorePort


class TenantStorePortTest(unittest.TestCase):
    def _make_store(self) -> TenantStorePort:
        return InMemoryTenantStore()

    def test_create_and_get_round_trip(self) -> None:
        store = self._make_store()
        tenant = store.create("t1", display_name="T One", config={"region": "eu"})
        self.assertEqual(tenant.tenant_id, "t1")
        self.assertEqual(tenant.display_name, "T One")
        self.assertEqual(tenant.status, "active")
        self.assertEqual(tenant.config, {"region": "eu"})

        retrieved = store.get("t1")
        self.assertIsNotNone(retrieved)
        assert retrieved is not None
        self.assertEqual(retrieved.tenant_id, "t1")
        self.assertEqual(retrieved.display_name, "T One")

    def test_get_missing_returns_none(self) -> None:
        store = self._make_store()
        self.assertIsNone(store.get("missing"))

    def test_duplicate_create_raises_valueerror(self) -> None:
        store = self._make_store()
        store.create("t1", display_name="T One")
        with self.assertRaises(ValueError):
            store.create("t1", display_name="T One Again")

    def test_default_status_and_config(self) -> None:
        store = self._make_store()
        tenant = store.create("t2", display_name="T Two")
        self.assertEqual(tenant.status, "active")
        self.assertEqual(tenant.config, {})


class SqlTenantStoreTest(TenantStorePortTest):
    def _make_store(self) -> TenantStorePort:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from agent_os_persistence import SqlTenantStore, create_all

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        create_all(engine)
        return SqlTenantStore(engine)


if __name__ == "__main__":
    unittest.main()
