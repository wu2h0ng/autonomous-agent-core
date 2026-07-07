"""Tests for the NL->Query engine (rule-based v0).

Test-first discipline: these tests define the expected behavior before implementation.
Each test proves real logic -- a stub or constant-return implementation must fail.
"""

from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import MetricContract  # noqa: E402
from agent_os_core.semantic_runtime import SemanticRegistry  # noqa: E402


def _build_metrics() -> tuple[MetricContract, ...]:
    """Build the 4 content-commerce metrics used by the domain pack."""
    return (
        MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value from paid orders within the selected time window.",
            owner="content_commerce_ops",
            unit="CNY",
            allowed_schemas=("sales",),
            dimensions=("order_date",),
        ),
        MetricContract(
            metric_name="roi",
            display_name="ROI",
            definition="Return on advertising investment within the selected time window.",
            owner="content_commerce_ops",
            unit="ratio",
            allowed_schemas=("sales",),
            dimensions=("order_date",),
        ),
        MetricContract(
            metric_name="conversion_rate",
            display_name="Conversion Rate",
            definition="Paid order conversion rate within the selected time window.",
            owner="content_commerce_ops",
            unit="ratio",
            allowed_schemas=("sales",),
            dimensions=("order_date",),
        ),
        MetricContract(
            metric_name="spend",
            display_name="Ad Spend",
            definition="Advertising spend within the selected time window.",
            owner="content_commerce_ops",
            unit="CNY",
            allowed_schemas=("sales",),
            dimensions=("order_date",),
        ),
    )


def _build_registry() -> SemanticRegistry:
    return SemanticRegistry(metric_contracts=_build_metrics())


class IntentParserMetricExtractionTest(unittest.TestCase):
    """Test that the NL intent parser extracts metric keywords from questions."""

    def setUp(self) -> None:
        from agent_os_core.nl_query import NLIntentParser

        self.parser = NLIntentParser()

    def test_parser_extracts_gmv_from_english(self) -> None:
        result = self.parser.parse("What was the GMV last week?")
        self.assertEqual(result.metric_keyword, "gmv")

    def test_parser_extracts_roi_from_english(self) -> None:
        result = self.parser.parse("Show me the ROI for this month")
        self.assertEqual(result.metric_keyword, "roi")

    def test_parser_extracts_conversion_rate_from_english(self) -> None:
        result = self.parser.parse("What is the conversion rate?")
        self.assertEqual(result.metric_keyword, "conversion_rate")

    def test_parser_extracts_spend_from_english(self) -> None:
        result = self.parser.parse("How much did we spend on ads?")
        self.assertEqual(result.metric_keyword, "spend")

    def test_parser_extracts_gmv_from_chinese(self) -> None:
        result = self.parser.parse("上周的GMV是多少?")
        self.assertEqual(result.metric_keyword, "gmv")

    def test_parser_extracts_roi_from_chinese(self) -> None:
        result = self.parser.parse("本月投入产出比怎么样?")
        self.assertEqual(result.metric_keyword, "roi")

    def test_parser_extracts_conversion_rate_from_chinese(self) -> None:
        result = self.parser.parse("转化率是多少")
        self.assertEqual(result.metric_keyword, "conversion_rate")

    def test_parser_extracts_spend_from_chinese(self) -> None:
        result = self.parser.parse("广告花费有多少")
        self.assertEqual(result.metric_keyword, "spend")

    def test_parser_extracts_gmv_from_chinese_synonym(self) -> None:
        result = self.parser.parse("成交额是多少")
        self.assertEqual(result.metric_keyword, "gmv")

    def test_parser_returns_unknown_for_unrecognized(self) -> None:
        result = self.parser.parse("What is the weather today?")
        self.assertEqual(result.metric_keyword, "unknown")

    def test_parser_preserves_raw_question(self) -> None:
        question = "What was the GMV last week?"
        result = self.parser.parse(question)
        self.assertEqual(result.raw_question, question)


class IntentParserTimeRangeExtractionTest(unittest.TestCase):
    """Test that the parser extracts time references from questions."""

    def setUp(self) -> None:
        from agent_os_core.nl_query import NLIntentParser

        self.parser = NLIntentParser()

    def test_parser_extracts_last_week_chinese(self) -> None:
        result = self.parser.parse("上周的GMV是多少")
        self.assertIsNotNone(result.time_range)
        start, end = result.time_range
        # last week should be a 7-day range ending at the most recent Monday
        self.assertEqual((end - start).days, 7)

    def test_parser_extracts_last_week_english(self) -> None:
        result = self.parser.parse("What was the GMV last week?")
        self.assertIsNotNone(result.time_range)
        start, end = result.time_range
        self.assertEqual((end - start).days, 7)

    def test_parser_extracts_this_month_chinese(self) -> None:
        result = self.parser.parse("本月ROI怎么样")
        self.assertIsNotNone(result.time_range)
        start, end = result.time_range
        # this month: start should be the 1st of the current month
        today = datetime.date.today()
        self.assertEqual(start, today.replace(day=1))
        # end should be today + 1 day (exclusive)
        self.assertEqual(end, today + datetime.timedelta(days=1))

    def test_parser_extracts_this_month_english(self) -> None:
        result = self.parser.parse("Show me ROI this month")
        self.assertIsNotNone(result.time_range)
        start, end = result.time_range
        today = datetime.date.today()
        self.assertEqual(start, today.replace(day=1))
        self.assertEqual(end, today + datetime.timedelta(days=1))

    def test_parser_extracts_today_chinese(self) -> None:
        result = self.parser.parse("今天的成交额")
        self.assertIsNotNone(result.time_range)
        start, end = result.time_range
        today = datetime.date.today()
        self.assertEqual(start, today)
        self.assertEqual(end, today + datetime.timedelta(days=1))

    def test_parser_extracts_yesterday_english(self) -> None:
        result = self.parser.parse("What was the spend yesterday?")
        self.assertIsNotNone(result.time_range)
        start, end = result.time_range
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        self.assertEqual(start, yesterday)
        self.assertEqual(end, datetime.date.today())

    def test_parser_returns_none_time_for_no_reference(self) -> None:
        result = self.parser.parse("What is the GMV?")
        self.assertIsNone(result.time_range)

    def test_parser_extracts_last_7_days_chinese(self) -> None:
        result = self.parser.parse("最近7天的转化率")
        self.assertIsNotNone(result.time_range)
        start, end = result.time_range
        today = datetime.date.today()
        self.assertEqual(end, today + datetime.timedelta(days=1))
        self.assertEqual(start, today - datetime.timedelta(days=6))


class IntentParserDimensionExtractionTest(unittest.TestCase):
    """Test that the parser extracts dimension requests from questions."""

    def setUp(self) -> None:
        from agent_os_core.nl_query import NLIntentParser

        self.parser = NLIntentParser()

    def test_parser_extracts_by_channel_chinese(self) -> None:
        result = self.parser.parse("按渠道看一下GMV")
        self.assertIn("channel", result.dimensions)

    def test_parser_extracts_by_region_english(self) -> None:
        result = self.parser.parse("Show GMV by region")
        self.assertIn("region", result.dimensions)

    def test_parser_extracts_by_category_chinese(self) -> None:
        result = self.parser.parse("按品类看转化率")
        self.assertIn("category", result.dimensions)

    def test_parser_extracts_by_date_english(self) -> None:
        result = self.parser.parse("Show spend by date")
        self.assertIn("date", result.dimensions)

    def test_parser_returns_empty_dimensions_when_none(self) -> None:
        result = self.parser.parse("What is the GMV?")
        self.assertEqual(result.dimensions, ())


class MetricContractMatcherTest(unittest.TestCase):
    """Test that the matcher scores and selects the correct MetricContract."""

    def setUp(self) -> None:
        from agent_os_core.nl_query import MetricContractMatcher, ParsedIntent

        self.matcher = MetricContractMatcher()
        self.registry = _build_registry()
        self._ParsedIntent = ParsedIntent

    def test_matcher_finds_gmv(self) -> None:
        intent = self._ParsedIntent(
            metric_keyword="gmv",
            raw_question="What was the GMV?",
        )
        result = self.matcher.match(intent, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.metric_name, "gmv")

    def test_matcher_finds_roi(self) -> None:
        intent = self._ParsedIntent(
            metric_keyword="roi",
            raw_question="Show me the ROI",
        )
        result = self.matcher.match(intent, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.metric_name, "roi")

    def test_matcher_finds_conversion_rate(self) -> None:
        intent = self._ParsedIntent(
            metric_keyword="conversion_rate",
            raw_question="What is the conversion rate?",
        )
        result = self.matcher.match(intent, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.metric_name, "conversion_rate")

    def test_matcher_finds_spend(self) -> None:
        intent = self._ParsedIntent(
            metric_keyword="spend",
            raw_question="How much did we spend?",
        )
        result = self.matcher.match(intent, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.metric_name, "spend")

    def test_matcher_returns_none_for_unknown(self) -> None:
        intent = self._ParsedIntent(
            metric_keyword="unknown",
            raw_question="What is the weather?",
        )
        result = self.matcher.match(intent, self.registry)
        self.assertIsNone(result)

    def test_matcher_returns_none_for_empty_keyword(self) -> None:
        intent = self._ParsedIntent(
            metric_keyword="",
            raw_question="hello",
        )
        result = self.matcher.match(intent, self.registry)
        self.assertIsNone(result)


class NLQueryEngineEndToEndTest(unittest.TestCase):
    """Test the full NL query pipeline: parse -> match -> build parameters."""

    def setUp(self) -> None:
        from agent_os_core.nl_query import NLQueryEngine

        self.registry = _build_registry()
        self.engine = NLQueryEngine(metric_registry=self.registry)

    def test_end_to_end_gmv_with_time(self) -> None:
        result = self.engine.query("上周的GMV是多少")
        self.assertIsNotNone(result.matched_metric)
        self.assertEqual(result.matched_metric.metric_name, "gmv")
        self.assertIn("start_date", result.parameters)
        self.assertIn("end_date", result.parameters)
        self.assertGreater(result.confidence, 0.0)

    def test_end_to_end_roi_english(self) -> None:
        result = self.engine.query("What was the ROI last week?")
        self.assertIsNotNone(result.matched_metric)
        self.assertEqual(result.matched_metric.metric_name, "roi")
        self.assertIn("start_date", result.parameters)
        self.assertIn("end_date", result.parameters)

    def test_end_to_end_no_time_provides_defaults(self) -> None:
        result = self.engine.query("What is the conversion rate?")
        self.assertIsNotNone(result.matched_metric)
        self.assertEqual(result.matched_metric.metric_name, "conversion_rate")
        # Even without explicit time, the engine should provide default parameters
        self.assertIn("start_date", result.parameters)
        self.assertIn("end_date", result.parameters)

    def test_end_to_end_spend_chinese(self) -> None:
        result = self.engine.query("本月广告花费有多少")
        self.assertIsNotNone(result.matched_metric)
        self.assertEqual(result.matched_metric.metric_name, "spend")
        self.assertIn("start_date", result.parameters)
        self.assertIn("end_date", result.parameters)

    def test_end_to_end_unknown_metric_returns_none(self) -> None:
        result = self.engine.query("What is the weather today?")
        self.assertIsNone(result.matched_metric)
        self.assertEqual(result.confidence, 0.0)
        # Time range present -> line under the rule-based chart policy.
        self.assertEqual(result.chart_type, "line")

    def test_end_to_end_chinese_natural_language(self) -> None:
        result = self.engine.query("帮我看一下上周的投入产出比")
        self.assertIsNotNone(result.matched_metric)
        self.assertEqual(result.matched_metric.metric_name, "roi")

    def test_end_to_end_preserves_dimensions(self) -> None:
        result = self.engine.query("按渠道看GMV")
        self.assertIsNotNone(result.matched_metric)
        self.assertEqual(result.matched_metric.metric_name, "gmv")
        self.assertIn("channel", result.dimensions)

    def test_end_to_end_confidence_high_for_exact_match(self) -> None:
        result = self.engine.query("GMV")
        self.assertIsNotNone(result.matched_metric)
        self.assertGreaterEqual(result.confidence, 0.8)
        self.assertEqual(result.chart_type, "number")

    def test_end_to_end_english_full_question(self) -> None:
        result = self.engine.query("How much did we spend on advertising this month?")
        self.assertIsNotNone(result.matched_metric)
        self.assertEqual(result.matched_metric.metric_name, "spend")

    def test_chart_type_line_for_date_dimension(self) -> None:
        result = self.engine.query("GMV by date")
        self.assertEqual(result.chart_type, "line")

    def test_chart_type_line_for_time_range(self) -> None:
        result = self.engine.query("GMV last week")
        self.assertEqual(result.chart_type, "line")

    def test_chart_type_bar_for_categorical_dimension(self) -> None:
        result = self.engine.query("GMV by region")
        self.assertEqual(result.chart_type, "bar")

    def test_chart_type_number_for_singular_metric(self) -> None:
        result = self.engine.query("What is the GMV?")
        self.assertEqual(result.chart_type, "number")


class NLQueryEngineDefaultTimeRangeTest(unittest.TestCase):
    """Test that the engine provides sensible default time ranges."""

    def setUp(self) -> None:
        from agent_os_core.nl_query import NLQueryEngine

        self.registry = _build_registry()
        self.engine = NLQueryEngine(metric_registry=self.registry)

    def test_default_time_range_is_last_30_days(self) -> None:
        result = self.engine.query("What is the GMV?")
        self.assertIsNotNone(result.matched_metric)
        start_str = result.parameters["start_date"]
        end_str = result.parameters["end_date"]
        start = datetime.date.fromisoformat(start_str)
        end = datetime.date.fromisoformat(end_str)
        today = datetime.date.today()
        # Default: last 30 days ending tomorrow (exclusive end)
        self.assertEqual(end, today + datetime.timedelta(days=1))
        self.assertEqual(start, today - datetime.timedelta(days=29))


class SemanticRegistrySearchMetricsTest(unittest.TestCase):
    """Test metric catalog search by keyword, display name, and aliases."""

    def setUp(self) -> None:
        self.registry = _build_registry()

    def test_search_returns_all_metrics_when_query_empty(self) -> None:
        results = self.registry.search_metrics("")
        self.assertEqual(len(results), 4)
        self.assertEqual(
            [m.metric_name for m in results], ["conversion_rate", "gmv", "roi", "spend"]
        )

    def test_search_matches_metric_name(self) -> None:
        results = self.registry.search_metrics("gmv")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metric_name, "gmv")

    def test_search_matches_display_name(self) -> None:
        results = self.registry.search_metrics("ad spend")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metric_name, "spend")

    def test_search_matches_alias(self) -> None:
        results = self.registry.search_metrics("成交额")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metric_name, "gmv")

    def test_search_respects_limit(self) -> None:
        results = self.registry.search_metrics("", limit=2)
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
