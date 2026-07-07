"""Tests for FederationPlanner (ADR-0013 Workstream A)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    DataRequirement,
    FederatedQueryPlan,
    ProviderContract,
    ProviderKind,
    QueryPlan,
)
from agent_os_core.data_product_compiler.federation import FederationPlanner  # noqa: E402


class FederationPlannerTest(unittest.TestCase):
    def test_plan_federated_query_returns_union_all_plan(self) -> None:
        planner = FederationPlanner()
        requirement = DataRequirement(
            requirement_id="r1",
            intent_id="i1",
            metric_names=("gmv",),
            dimensions=("order_date",),
            time_window={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            provider_ids=("pg", "mysql"),
        )
        providers = (
            ProviderContract(
                provider_id="pg",
                kind=ProviderKind.WAREHOUSE,
                name="postgres",
                owner="data",
                allowed_schemas=("sales",),
            ),
            ProviderContract(
                provider_id="mysql",
                kind=ProviderKind.WAREHOUSE,
                name="mysql",
                owner="data",
                allowed_schemas=("sales",),
            ),
        )
        plan = planner.plan_federated_query(requirement, providers, ())
        self.assertIsInstance(plan, FederatedQueryPlan)
        self.assertEqual(plan.combine_strategy, "UNION ALL")
        self.assertEqual(len(plan.sub_queries), 2)
        self.assertTrue(all(isinstance(sub, QueryPlan) for sub in plan.sub_queries))


if __name__ == "__main__":
    unittest.main()
