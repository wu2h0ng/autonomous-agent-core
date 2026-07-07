"""Tests for ProviderPlanner."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    DataRequirement,
    MetricContract,
    ProviderContract,
    ProviderKind,
)
from agent_os_core.data_access_plane import ProviderRegistry  # noqa: E402
from agent_os_core.data_product_compiler.provider_planner import (  # noqa: E402
    ProviderPlanner,
    ProviderPlanningError,
)


class ProviderPlannerTest(unittest.TestCase):
    def _metric(self, allowed_schemas: tuple[str, ...] = ("sales",)) -> MetricContract:
        return MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="g",
            owner="o",
            unit="CNY",
            allowed_schemas=allowed_schemas,
        )

    def _requirement(self, provider_ids: tuple[str, ...] = ()) -> DataRequirement:
        return DataRequirement(
            requirement_id="r1",
            intent_id="i1",
            metric_names=("gmv",),
            dimensions=("order_date",),
            time_window={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            provider_ids=provider_ids,
        )

    def test_selects_provider_by_provider_id(self) -> None:
        registry = ProviderRegistry(
            (
                ProviderContract(
                    provider_id="pg-1",
                    kind=ProviderKind.WAREHOUSE,
                    name="pg",
                    owner="data",
                    allowed_schemas=("sales",),
                ),
                ProviderContract(
                    provider_id="mysql-1",
                    kind=ProviderKind.WAREHOUSE,
                    name="mysql",
                    owner="data",
                    allowed_schemas=("finance",),
                ),
            )
        )
        planner = ProviderPlanner()
        provider = planner.plan(
            requirement=self._requirement(provider_ids=("mysql-1",)),
            metric_contract=self._metric(),
            provider_registry=registry,
        )
        self.assertEqual(provider.provider_id, "mysql-1")

    def test_falls_back_to_schema_matching(self) -> None:
        registry = ProviderRegistry(
            (
                ProviderContract(
                    provider_id="pg-1",
                    kind=ProviderKind.WAREHOUSE,
                    name="pg",
                    owner="data",
                    allowed_schemas=("sales",),
                ),
            )
        )
        planner = ProviderPlanner()
        provider = planner.plan(
            requirement=self._requirement(),
            metric_contract=self._metric(),
            provider_registry=registry,
        )
        self.assertEqual(provider.provider_id, "pg-1")

    def test_raises_when_requested_provider_missing(self) -> None:
        registry = ProviderRegistry(
            (
                ProviderContract(
                    provider_id="pg-1",
                    kind=ProviderKind.WAREHOUSE,
                    name="pg",
                    owner="data",
                    allowed_schemas=("sales",),
                ),
            )
        )
        planner = ProviderPlanner()
        with self.assertRaises(ProviderPlanningError):
            planner.plan(
                requirement=self._requirement(provider_ids=("missing",)),
                metric_contract=self._metric(),
                provider_registry=registry,
            )

    def test_raises_when_no_provider_matches_schemas(self) -> None:
        registry = ProviderRegistry(
            (
                ProviderContract(
                    provider_id="pg-1",
                    kind=ProviderKind.WAREHOUSE,
                    name="pg",
                    owner="data",
                    allowed_schemas=("sales",),
                ),
            )
        )
        planner = ProviderPlanner()
        with self.assertRaises(ProviderPlanningError):
            planner.plan(
                requirement=self._requirement(),
                metric_contract=self._metric(("finance",)),
                provider_registry=registry,
            )


if __name__ == "__main__":
    unittest.main()
