from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import SQLTemplate  # noqa: E402
from agent_os_core.query_runtime import TemplateRegistry  # noqa: E402


def _tpl(metric: str, sql: str) -> SQLTemplate:
    return SQLTemplate(
        template_id=f"{metric}_daily",
        metric_name=metric,
        sql=sql,
        required_parameters=("start_date", "end_date", "limit"),
    )


class TemplateRegistryTest(unittest.TestCase):
    def test_resolve_returns_metric_matching_template(self) -> None:
        gmv = _tpl("gmv", "select 1 as value")
        spend = _tpl("spend", "select 2 as value")
        registry = TemplateRegistry((gmv, spend))
        self.assertIs(registry.resolve("gmv"), gmv)
        self.assertIs(registry.resolve("spend"), spend)

    def test_resolve_missing_metric_raises_in_strict_mode(self) -> None:
        registry = TemplateRegistry((_tpl("gmv", "select 1 as value"),))
        with self.assertRaisesRegex(ValueError, "No SQL template registered for metric 'roi'"):
            registry.resolve("roi")

    def test_from_single_falls_back_to_the_one_template(self) -> None:
        gmv = _tpl("gmv", "select 1 as value")
        registry = TemplateRegistry.from_single(gmv)
        # exact-metric hit
        self.assertIs(registry.resolve("gmv"), gmv)
        # back-compat: any other metric falls back to the single default template
        self.assertIs(registry.resolve("anything_else"), gmv)

    def test_duplicate_metric_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TemplateRegistry((_tpl("gmv", "select 1 as value"), _tpl("gmv", "select 9 as value")))

    def test_metrics_lists_registered_metric_names(self) -> None:
        registry = TemplateRegistry((_tpl("gmv", "select 1"), _tpl("spend", "select 2")))
        self.assertEqual(set(registry.metrics()), {"gmv", "spend"})


if __name__ == "__main__":
    unittest.main()
