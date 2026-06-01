from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))

from agent_os_contracts import (
    DataClassification,
    MetricContract,
    SQLSafetyIssue,
    SQLSafetyResult,
    SQLTemplate,
)


class ContractDefaultsTest(unittest.TestCase):
    def test_metric_contract_has_reviewable_defaults(self) -> None:
        metric = MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value.",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
        )

        self.assertEqual(metric.version, "v1")
        self.assertEqual(metric.data_classification, DataClassification.INTERNAL)
        self.assertEqual(metric.dimensions, ())

    def test_sql_template_has_safety_defaults(self) -> None:
        template = SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql="select order_date from sales.orders where order_date >= :start_date limit :limit",
            required_parameters=("start_date", "limit"),
        )

        self.assertEqual(template.required_time_parameters, ("start_date", "end_date"))
        self.assertEqual(template.default_limit, 100)
        self.assertEqual(template.max_limit, 1000)
        self.assertFalse(template.allow_select_star)

    def test_sql_safety_result_preserves_stable_issue_codes(self) -> None:
        result = SQLSafetyResult(
            allowed=False,
            reasons=("SQL must include an explicit LIMIT.",),
            checked_schemas=("sales",),
            issues=(SQLSafetyIssue(code="MISSING_LIMIT", message="SQL must include an explicit LIMIT."),),
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.issues[0].code, "MISSING_LIMIT")


if __name__ == "__main__":
    unittest.main()
