"""Tests for MetricContract YAML loader and enhanced schema."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    ActionCandidate,
    DataClassification,
    MetricContract,
    QualityContract,
    RiskLevel,
    SQLTemplate,
)
from agent_os_core.metric_contract_loader import (  # noqa: E402
    MetricContractLoadError,
    load_metric_contract,
    load_metric_contracts,
)


class MetricContractLoaderTest(unittest.TestCase):
    def test_loads_content_commerce_gmv(self) -> None:
        contract = load_metric_contract(
            ROOT / "domain_packs" / "content_commerce" / "metrics" / "gmv.yaml"
        )

        self.assertEqual(contract.metric_name, "gmv")
        self.assertEqual(contract.display_name, "GMV")
        self.assertEqual(contract.unit, "CNY")
        self.assertEqual(contract.allowed_schemas, ("sales",))
        self.assertEqual(contract.dimensions, ("order_date",))
        self.assertEqual(contract.data_classification, DataClassification.INTERNAL)

        self.assertIsInstance(contract.quality_contract, QualityContract)
        assert contract.quality_contract is not None
        self.assertEqual(contract.quality_contract.freshness, "24h")
        self.assertEqual(contract.quality_contract.null_rate, "<0.01")

        self.assertEqual(len(contract.verified_queries), 1)
        query = contract.verified_queries[0]
        self.assertIsInstance(query, SQLTemplate)
        self.assertEqual(query.template_id, "gmv_daily")
        self.assertIn("SELECT order_date", query.sql)
        self.assertEqual(query.required_parameters, ("start_date", "end_date"))
        self.assertEqual(query.max_limit, 1000)

        self.assertEqual(len(contract.action_candidates), 1)
        action = contract.action_candidates[0]
        self.assertIsInstance(action, ActionCandidate)
        self.assertEqual(action.action_id, "investigate_gmv_drop")
        self.assertEqual(action.risk_level, RiskLevel.R2)

        self.assertEqual(contract.feedback_metric, "weekly_gmv_recovery")

    def test_missing_required_field_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.yaml"
            path.write_text("name: x\n", encoding="utf-8")
            with self.assertRaises(MetricContractLoadError):
                load_metric_contract(path)

    def test_load_directory(self) -> None:
        contracts = load_metric_contracts(ROOT / "domain_packs" / "content_commerce" / "metrics")
        self.assertIn("gmv", contracts)
        self.assertIsInstance(contracts["gmv"], MetricContract)

    def test_invalid_risk_level_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.yaml"
            path.write_text(
                "name: x\n"
                "display_name: X\n"
                "definition: d\n"
                "owner: o\n"
                "unit: u\n"
                "action_candidates:\n"
                "  - id: a\n"
                "    risk_level: R99\n",
                encoding="utf-8",
            )
            with self.assertRaises(MetricContractLoadError):
                load_metric_contract(path)


if __name__ == "__main__":
    unittest.main()
