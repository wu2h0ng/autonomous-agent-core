"""Tests for the metric alias maps shared by rule-based NLP modules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_core._metric_aliases import (  # noqa: E402
    DISPLAY_TO_METRIC,
    METRIC_DISPLAY_NAMES,
)


class MetricAliasesTest(unittest.TestCase):
    def test_display_to_metric_inverts_display_names(self) -> None:
        for metric_name, display_name in METRIC_DISPLAY_NAMES.items():
            self.assertEqual(DISPLAY_TO_METRIC[display_name.lower()], metric_name)
            self.assertEqual(DISPLAY_TO_METRIC[metric_name], metric_name)

    def test_chinese_aliases_resolve(self) -> None:
        self.assertEqual(DISPLAY_TO_METRIC["成交额"], "gmv")
        self.assertEqual(DISPLAY_TO_METRIC["投入产出比"], "roi")
        self.assertEqual(DISPLAY_TO_METRIC["转化率"], "conversion_rate")

    def test_all_display_names_are_reachable(self) -> None:
        for metric_name in METRIC_DISPLAY_NAMES:
            self.assertIn(metric_name, DISPLAY_TO_METRIC.values())


if __name__ == "__main__":
    unittest.main()
