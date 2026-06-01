from __future__ import annotations

from agent_os_contracts import (
    BusinessIntent,
    EvidenceChain,
    MetricContract,
    QueryPlan,
    QueryResult,
    SQLSafetyResult,
)


class EvidenceChainBuilder:
    def build(
        self,
        *,
        evidence_chain_id: str,
        intent: BusinessIntent,
        metric_contract: MetricContract,
        query_plan: QueryPlan,
        sql_safety: SQLSafetyResult,
        query_result: QueryResult,
        trace_id: str,
    ) -> EvidenceChain:
        if query_result.row_count == 0:
            conclusion = f"No rows returned for {metric_contract.display_name}."
            confidence = 0.55
            limitations = ("No data rows were available for the requested scope.",)
        else:
            conclusion = (
                f"{metric_contract.display_name} returned {query_result.row_count} row(s) "
                f"under the approved metric contract."
            )
            confidence = 0.82
            limitations = ("Result depends on the approved SQL template and source freshness.",)

        evidence = EvidenceChain(
            evidence_chain_id=evidence_chain_id,
            intent=intent,
            metric_contract=metric_contract,
            query_plan=query_plan,
            sql_safety=sql_safety,
            query_result=query_result,
            conclusion=conclusion,
            confidence=confidence,
            limitations=limitations,
            trace_id=trace_id,
        )

        if not evidence.is_complete():
            raise ValueError("EvidenceChain is incomplete")

        return evidence
