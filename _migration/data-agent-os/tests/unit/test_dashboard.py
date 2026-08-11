"""Tests for the NL Data Product Workspace dashboard store port."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_core import Dashboard, DashboardCard, InMemoryDashboardStore  # noqa: E402


_SQLALCHEMY = __import__("importlib.util").util.find_spec("sqlalchemy") is not None


def _sample_dashboard(tenant_id: str = "default", dashboard_id: str = "dash-1") -> Dashboard:
    return Dashboard(
        dashboard_id=dashboard_id,
        tenant_id=tenant_id,
        title="Weekly Review",
        cards=(
            DashboardCard(
                card_id="card-1",
                title="GMV",
                question="What was the GMV last week?",
                metric_name="gmv",
                chart_type="line",
            ),
        ),
        created_at="2026-07-06T10:00:00+00:00",
    )


class InMemoryDashboardStoreTest(unittest.TestCase):
    def test_save_and_get_round_trip(self) -> None:
        store = InMemoryDashboardStore()
        dashboard = _sample_dashboard()
        store.save(dashboard)
        fetched = store.get("dash-1", "default")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.dashboard_id, "dash-1")
        self.assertEqual(fetched.title, "Weekly Review")
        self.assertEqual(len(fetched.cards), 1)
        self.assertEqual(fetched.cards[0].metric_name, "gmv")

    def test_get_missing_returns_none(self) -> None:
        store = InMemoryDashboardStore()
        self.assertIsNone(store.get("missing", "default"))

    def test_list_pagination_and_tenant_isolation(self) -> None:
        store = InMemoryDashboardStore()
        for idx in range(3):
            store.save(
                Dashboard(
                    dashboard_id=f"dash-{idx}",
                    tenant_id="tenant-a",
                    title=f"Board {idx}",
                    cards=(),
                    created_at=f"2026-07-06T10:00:0{idx}+00:00",
                )
            )
        store.save(
            Dashboard(
                dashboard_id="other",
                tenant_id="tenant-b",
                title="Other",
                cards=(),
                created_at="2026-07-06T10:00:10+00:00",
            )
        )
        page = store.list("tenant-a", limit=2, offset=0)
        self.assertEqual(len(page), 2)
        self.assertEqual([d.dashboard_id for d in page], ["dash-2", "dash-1"])

        second_page = store.list("tenant-a", limit=2, offset=2)
        self.assertEqual(len(second_page), 1)
        self.assertEqual(second_page[0].dashboard_id, "dash-0")

        other_tenant = store.list("tenant-b", limit=10, offset=0)
        self.assertEqual(len(other_tenant), 1)
        self.assertEqual(other_tenant[0].tenant_id, "tenant-b")


@unittest.skipUnless(_SQLALCHEMY, "sqlalchemy not installed")
class SqlDashboardStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy import create_engine

        from agent_os_persistence import SqlDashboardStore, create_all

        self.engine = create_engine("sqlite:///:memory:")
        create_all(self.engine)
        self.store = SqlDashboardStore(self.engine)

    def test_save_and_get_round_trip(self) -> None:
        dashboard = _sample_dashboard()
        self.store.save(dashboard)
        fetched = self.store.get("dash-1", "default")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.dashboard_id, "dash-1")
        self.assertEqual(fetched.title, "Weekly Review")
        self.assertEqual(fetched.cards[0].metric_name, "gmv")

    def test_save_updates_existing_dashboard(self) -> None:
        dashboard = _sample_dashboard()
        self.store.save(dashboard)
        updated = Dashboard(
            dashboard_id="dash-1",
            tenant_id="default",
            title="Updated Review",
            cards=dashboard.cards,
            created_at=dashboard.created_at,
        )
        self.store.save(updated)
        fetched = self.store.get("dash-1", "default")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "Updated Review")

    def test_list_orders_by_created_desc(self) -> None:
        for idx in range(3):
            self.store.save(
                Dashboard(
                    dashboard_id=f"dash-{idx}",
                    tenant_id="tenant-a",
                    title=f"Board {idx}",
                    cards=(),
                    created_at=f"2026-07-06T10:00:0{idx}+00:00",
                )
            )
        page = self.store.list("tenant-a", limit=10, offset=0)
        self.assertEqual([d.dashboard_id for d in page], ["dash-2", "dash-1", "dash-0"])


if __name__ == "__main__":
    unittest.main()
