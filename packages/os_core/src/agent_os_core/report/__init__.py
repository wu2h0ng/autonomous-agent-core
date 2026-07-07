"""Template-based report generation from evidence chain data.

This module generates structured narrative reports from Trusted Loop evidence
without any LLM dependency. Each section is derived from real evidence data,
never hardcoded or mocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_os_contracts import (
    ActionProposal,
    EvidenceChain,
    MetricContract,
    QueryResult,
)


@dataclass(frozen=True)
class ReportSection:
    """A single section of a generated report."""

    heading: str
    content: str
    section_type: str  # summary | data_source | safety | results | recommendation | limitations


@dataclass(frozen=True)
class GeneratedReport:
    """A complete generated report with sections and metadata."""

    title: str
    summary: str
    sections: list[ReportSection]
    generated_at: datetime


class ReportGenerator:
    """Generates structured reports from evidence chain data.

    This is a template-based generator (v0) that produces narrative sections
    from real evidence without any LLM dependency. Every section is derived
    from the evidence chain, query result, metric contract, and action proposal.
    """

    def generate(
        self,
        evidence_chain: EvidenceChain,
        query_result: QueryResult,
        metric_contract: MetricContract,
        action_proposal: ActionProposal | None = None,
    ) -> GeneratedReport:
        """Generate a report from evidence chain data.

        Args:
            evidence_chain: The complete evidence chain from the Trusted Loop.
            query_result: The query result with rows and row count.
            metric_contract: The metric contract defining the computation.
            action_proposal: Optional action proposal if one was generated.

        Returns:
            A GeneratedReport with sections derived from the evidence.
        """
        sections = []

        # Summary section: one-line summary with metric name, value, and context
        summary_content = self._build_summary(metric_contract, query_result)
        sections.append(
            ReportSection(
                heading="Summary",
                content=summary_content,
                section_type="summary",
            )
        )

        # Data Source section: which provider was used, what schemas
        data_source_content = self._build_data_source(metric_contract, evidence_chain)
        sections.append(
            ReportSection(
                heading="Data Source",
                content=data_source_content,
                section_type="data_source",
            )
        )

        # SQL Safety section: whether the query passed safety checks
        safety_content = self._build_safety(evidence_chain)
        sections.append(
            ReportSection(
                heading="SQL Safety",
                content=safety_content,
                section_type="safety",
            )
        )

        # Results section: formatted query results (top N rows)
        results_content = self._build_results(query_result)
        sections.append(
            ReportSection(
                heading="Results",
                content=results_content,
                section_type="results",
            )
        )

        # Recommendation section: if action_proposal exists, format it
        if action_proposal is not None:
            recommendation_content = self._build_recommendation(action_proposal)
            sections.append(
                ReportSection(
                    heading="Recommendation",
                    content=recommendation_content,
                    section_type="recommendation",
                )
            )

        # Limitations section: any evidence gaps or limitations
        limitations_content = self._build_limitations(evidence_chain, metric_contract)
        sections.append(
            ReportSection(
                heading="Limitations",
                content=limitations_content,
                section_type="limitations",
            )
        )

        return GeneratedReport(
            title=f"{metric_contract.display_name} Report",
            summary=summary_content,
            sections=sections,
            generated_at=datetime.now(),
        )

    def _build_summary(self, metric_contract: MetricContract, query_result: QueryResult) -> str:
        """Build the summary section with metric name and primary value."""
        metric_name = metric_contract.display_name
        row_count = query_result.row_count

        # Extract primary metric value from first row if available
        primary_value = None
        if row_count > 0 and query_result.rows:
            first_row = query_result.rows[0]
            # Try to find a value matching the metric name
            for key, value in first_row.items():
                if metric_contract.metric_name.lower() in key.lower():
                    primary_value = value
                    break
            # If not found, use the last numeric value
            if primary_value is None:
                for value in reversed(list(first_row.values())):
                    if isinstance(value, (int, float)):
                        primary_value = value
                        break

        if primary_value is not None:
            return f"{metric_name}: {primary_value} ({row_count} row(s) returned)"
        return f"{metric_name}: {row_count} row(s) returned"

    def _build_data_source(
        self, metric_contract: MetricContract, evidence_chain: EvidenceChain
    ) -> str:
        """Build the data source section with schema information."""
        schemas = ", ".join(metric_contract.allowed_schemas)
        return f"Data sourced from schemas: {schemas}. Metric: {metric_contract.metric_name} ({metric_contract.version})."

    def _build_safety(self, evidence_chain: EvidenceChain) -> str:
        """Build the SQL safety section."""
        if evidence_chain.sql_safety.allowed:
            return "SQL safety check passed. Query conforms to allowed schemas and safety rules."
        reasons = ", ".join(evidence_chain.sql_safety.reasons)
        return f"SQL safety check failed: {reasons}"

    def _build_results(self, query_result: QueryResult, max_rows: int = 10) -> str:
        """Build the results section with top N rows."""
        if query_result.row_count == 0:
            return "No results returned."

        lines = []
        rows_to_show = min(query_result.row_count, max_rows)

        for i in range(rows_to_show):
            row = query_result.rows[i]
            row_str = ", ".join(f"{k}={v}" for k, v in row.items())
            lines.append(f"Row {i + 1}: {row_str}")

        if query_result.row_count > max_rows:
            lines.append(
                f"... and {query_result.row_count - max_rows} more row(s) (showing top {max_rows} of {query_result.row_count})"
            )

        return "\n".join(lines)

    def _build_recommendation(self, action_proposal: ActionProposal) -> str:
        """Build the recommendation section from action proposal."""
        return f"{action_proposal.recommended_action}: {action_proposal.reason}"

    def _build_limitations(
        self, evidence_chain: EvidenceChain, metric_contract: MetricContract
    ) -> str:
        """Build the limitations section from evidence limitations."""
        if not evidence_chain.limitations:
            return "No specific limitations identified."

        lines = []
        for limitation in evidence_chain.limitations:
            lines.append(f"- {limitation}")

        return "\n".join(lines)
