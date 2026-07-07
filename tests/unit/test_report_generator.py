from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    ActionProposal,
    BusinessIntent,
    EvidenceChain,
    MetricContract,
    QueryPlan,
    QueryResult,
    RiskLevel,
    SQLSafetyResult,
)
from agent_os_core.report import (  # noqa: E402
    GeneratedReport,
    ReportGenerator,
)


def _build_evidence(
    *,
    metric_name: str = "gmv",
    display_name: str = "GMV",
    rows: tuple[dict[str, object], ...] | None = None,
    row_count: int | None = None,
    sql_safety_allowed: bool = True,
    limitations: tuple[str, ...] = (
        "Result depends on the approved SQL template and source freshness.",
    ),
    conclusion: str | None = None,
    confidence: float = 0.82,
    provider_name: str = "default",
    allowed_schemas: tuple[str, ...] = ("sales",),
) -> tuple[EvidenceChain, MetricContract, QueryResult]:
    if rows is None:
        rows = ({"order_date": "2026-01-01", "gmv": 1000.0},)
    if row_count is None:
        row_count = len(rows)
    metric = MetricContract(
        metric_name=metric_name,
        display_name=display_name,
        definition=f"{display_name} definition.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=allowed_schemas,
    )
    intent = BusinessIntent(
        intent_id="intent-test",
        question=f"What is the {display_name}?",
        metric_name=metric_name,
    )
    query_plan = QueryPlan(
        metric_name=metric_name,
        sql="SELECT order_date, gmv FROM sales.orders LIMIT 100",
        parameters={"start_date": "2026-01-01", "end_date": "2026-01-31"},
    )
    sql_safety = SQLSafetyResult(
        allowed=sql_safety_allowed,
        reasons=() if sql_safety_allowed else ("Unsafe query",),
        checked_schemas=allowed_schemas,
        checked_tables=("sales.orders",),
        bound_parameters=("start_date", "end_date"),
        limit_value=100,
    )
    query_result = QueryResult(rows=rows, row_count=row_count)
    if conclusion is None:
        conclusion = (
            f"{display_name} returned {row_count} row(s) under the approved metric contract."
        )
    evidence = EvidenceChain(
        evidence_chain_id="evidence-test",
        intent=intent,
        metric_contract=metric,
        query_plan=query_plan,
        sql_safety=sql_safety,
        query_result=query_result,
        conclusion=conclusion,
        confidence=confidence,
        limitations=limitations,
        trace_id="trace-test",
    )
    return evidence, metric, query_result


def _build_action_proposal(
    *,
    title: str = "Increase ad spend",
    reason: str = "ROI is above threshold.",
    risk_level: RiskLevel = RiskLevel.R1,
) -> ActionProposal:
    return ActionProposal(
        proposal_id="proposal-test",
        evidence_chain_id="evidence-test",
        target_object="ad_campaign",
        recommended_action=title,
        reason=reason,
        risk_level=risk_level,
        expected_impact="Expected 10% improvement.",
        approval_required=False,
        approver_role=None,
    )


class ReportGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = ReportGenerator()

    def test_report_has_summary_section(self) -> None:
        evidence, metric, query_result = _build_evidence()
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        section_types = [s.section_type for s in report.sections]
        self.assertIn("summary", section_types)
        summary = next(s for s in report.sections if s.section_type == "summary")
        self.assertTrue(len(summary.content) > 0)

    def test_report_has_data_source_section(self) -> None:
        evidence, metric, query_result = _build_evidence(
            allowed_schemas=("sales", "marketing"),
        )
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        section_types = [s.section_type for s in report.sections]
        self.assertIn("data_source", section_types)
        data_source = next(s for s in report.sections if s.section_type == "data_source")
        self.assertIn("sales", data_source.content)

    def test_report_has_safety_section(self) -> None:
        evidence, metric, query_result = _build_evidence()
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        section_types = [s.section_type for s in report.sections]
        self.assertIn("safety", section_types)
        safety = next(s for s in report.sections if s.section_type == "safety")
        self.assertIn("passed", safety.content)

    def test_report_has_results_section_with_data(self) -> None:
        rows = (
            {"order_date": "2026-01-01", "gmv": 1000.0},
            {"order_date": "2026-01-02", "gmv": 1500.0},
        )
        evidence, metric, query_result = _build_evidence(rows=rows)
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        section_types = [s.section_type for s in report.sections]
        self.assertIn("results", section_types)
        results = next(s for s in report.sections if s.section_type == "results")
        self.assertIn("1000.0", results.content)
        self.assertIn("1500.0", results.content)

    def test_report_has_recommendation_when_action_proposal_exists(self) -> None:
        evidence, metric, query_result = _build_evidence()
        proposal = _build_action_proposal(
            title="Increase ad spend",
            reason="ROI is above threshold.",
        )

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        section_types = [s.section_type for s in report.sections]
        self.assertIn("recommendation", section_types)
        recommendation = next(s for s in report.sections if s.section_type == "recommendation")
        self.assertIn("Increase ad spend", recommendation.content)
        self.assertIn("ROI is above threshold.", recommendation.content)

    def test_report_has_no_recommendation_when_no_action_proposal(self) -> None:
        evidence, metric, query_result = _build_evidence()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=None,
        )

        section_types = [s.section_type for s in report.sections]
        self.assertNotIn("recommendation", section_types)

    def test_report_has_limitations_section(self) -> None:
        evidence, metric, query_result = _build_evidence(
            limitations=("Data freshness is not guaranteed.", "Limited to sales schema."),
        )
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        section_types = [s.section_type for s in report.sections]
        self.assertIn("limitations", section_types)
        limitations = next(s for s in report.sections if s.section_type == "limitations")
        self.assertIn("Data freshness is not guaranteed.", limitations.content)
        self.assertIn("Limited to sales schema.", limitations.content)

    def test_report_summary_includes_metric_name_and_value(self) -> None:
        rows = ({"order_date": "2026-01-01", "gmv": 42000.50},)
        evidence, metric, query_result = _build_evidence(
            metric_name="gmv",
            display_name="GMV",
            rows=rows,
        )
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        summary = next(s for s in report.sections if s.section_type == "summary")
        self.assertIn("GMV", summary.content)
        self.assertIn("42000.5", summary.content)

    def test_report_results_truncate_large_datasets(self) -> None:
        rows = tuple(
            {"order_date": f"2026-01-{i:02d}", "gmv": float(i * 100)} for i in range(1, 1001)
        )
        evidence, metric, query_result = _build_evidence(rows=rows, row_count=1000)
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        results = next(s for s in report.sections if s.section_type == "results")
        # Should only show top 10 rows, not all 1000
        # The last row in top 10 would have gmv=1000.0 (i=10)
        self.assertIn("1000.0", results.content)
        # Row 11 would have gmv=1100.0 — should NOT be present
        self.assertNotIn("1100.0", results.content)
        # Should indicate truncation
        self.assertIn("1000", results.content)

    def test_report_generation_does_not_require_llm(self) -> None:
        evidence, metric, query_result = _build_evidence()
        proposal = _build_action_proposal()

        report = self.generator.generate(
            evidence_chain=evidence,
            query_result=query_result,
            metric_contract=metric,
            action_proposal=proposal,
        )

        # ReportGenerator is template-based, no LLM imports or calls
        self.assertIsInstance(report, GeneratedReport)
        self.assertTrue(len(report.sections) > 0)
        # Verify it has a generated_at timestamp
        self.assertIsNotNone(report.generated_at)


if __name__ == "__main__":
    unittest.main()
