from __future__ import annotations

from uuid import uuid4

from agent_os_contracts import (
    BusinessIntent,
    MetricContract,
    QueryPlan,
    SQLTemplate,
    TrustedLoopResult,
)

from .action_proposal import ActionProposalBuilder
from .evidence_chain import EvidenceChainBuilder
from .query_runtime import StaticQueryExecutor
from .sql_safety import SQLSafetyChecker
from .trace import TraceRecorder


class TrustedLoopRuntime:
    def __init__(
        self,
        *,
        metric_contract: MetricContract,
        sql_template: SQLTemplate,
        query_executor: StaticQueryExecutor,
    ) -> None:
        self.metric_contract = metric_contract
        self.sql_template = sql_template
        self.query_executor = query_executor
        self.sql_safety = SQLSafetyChecker(metric_contract.allowed_schemas)
        self.evidence_builder = EvidenceChainBuilder()
        self.action_builder = ActionProposalBuilder()

    def run(self, question: str, parameters: dict[str, object]) -> TrustedLoopResult:
        trace_id = f"trace-{uuid4().hex[:12]}"
        trace = TraceRecorder(trace_id)

        intent = BusinessIntent(
            intent_id=f"intent-{uuid4().hex[:12]}",
            question=question,
            metric_name=self.metric_contract.metric_name,
        )
        trace.record("intent", {"intent_id": intent.intent_id, "metric": intent.metric_name})

        query_plan = QueryPlan(
            metric_name=self.metric_contract.metric_name,
            sql=self.sql_template.sql,
            parameters=parameters,
        )
        trace.record("query_plan", {"metric": query_plan.metric_name})

        safety = self.sql_safety.check(
            self.sql_template.sql,
            self.sql_template.required_parameters,
            parameters,
            required_time_parameters=self.sql_template.required_time_parameters,
            max_limit=self.sql_template.max_limit,
            allow_select_star=self.sql_template.allow_select_star,
        )
        trace.record("sql_safety", {"allowed": safety.allowed, "reasons": list(safety.reasons)})
        if not safety.allowed:
            raise ValueError(f"SQL safety check failed: {'; '.join(safety.reasons)}")

        query_result = self.query_executor.execute(query_plan)
        trace.record("query_result", {"row_count": query_result.row_count})

        evidence = self.evidence_builder.build(
            evidence_chain_id=f"evidence-{uuid4().hex[:12]}",
            intent=intent,
            metric_contract=self.metric_contract,
            query_plan=query_plan,
            sql_safety=safety,
            query_result=query_result,
            trace_id=trace_id,
        )
        trace.record("evidence_chain", {"evidence_chain_id": evidence.evidence_chain_id})

        proposal = self.action_builder.build(
            proposal_id=f"proposal-{uuid4().hex[:12]}",
            evidence=evidence,
        )
        trace.record(
            "action_proposal",
            {
                "proposal_id": proposal.proposal_id,
                "risk_level": proposal.risk_level.value,
                "approval_required": proposal.approval_required,
            },
        )

        return TrustedLoopResult(
            intent=intent,
            query_plan=query_plan,
            evidence_chain=evidence,
            action_proposal=proposal,
            trace_events=trace.events(),
        )
