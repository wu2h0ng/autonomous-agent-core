from __future__ import annotations

from agent_os_contracts import (
    BusinessIntent,
    Claim,
    ConfidenceScore,
    EvidenceChain,
    EvalBinding,
    Limitation,
    MetricContract,
    MetricContractRef,
    ProviderContract,
    ProviderContractRef,
    QueryPlan,
    QueryResult,
    QueryResultSummary,
    SQLSafetyResult,
)


class EvidenceChainBuilder:
    def __init__(self, *, semantic_registry=None) -> None:
        self._registry = semantic_registry

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
        provider_contract: ProviderContract | None = None,
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

        column_names = tuple(query_result.rows[0].keys()) if query_result.rows else ()
        query_result_summary = QueryResultSummary(
            row_count=query_result.row_count,
            column_names=column_names,
            sample_fingerprint="",
        )

        metric_contract_refs = (
            MetricContractRef(
                metric_name=metric_contract.metric_name,
                contract_version=metric_contract.version,
            ),
        )
        provider_contract_refs = (
            (ProviderContractRef(provider_id=provider_contract.provider_id),)
            if provider_contract is not None
            else ()
        )

        claims = (
            Claim(
                statement=conclusion,
                evidence_refs=("query_result", "sql_safety", "query_plan"),
                confidence="medium" if confidence < 0.7 else "high",
                scope="in-scope",
            ),
        )
        limitation_objects = tuple(Limitation(description=limitation) for limitation in limitations)
        confidence_score = ConfidenceScore(score=confidence, calibration="rule_based")
        eval_bindings = (EvalBinding(eval_case_id=trace_id, dimension="evidence"),)

        semantic_object_refs: tuple = ()
        semantic_lineage: tuple = ()
        if self._registry is not None:
            semantic_object_refs, semantic_lineage = self._semantic_lineage(
                metric_contract, provider_contract
            )

        evidence = EvidenceChain(
            semantic_object_refs=semantic_object_refs,
            semantic_lineage=semantic_lineage,
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
            metric_contract_refs=metric_contract_refs,
            provider_contract_refs=provider_contract_refs,
            query_result_summary=query_result_summary,
            claims=claims,
            limitation_objects=limitation_objects,
            confidence_score=confidence_score,
            eval_bindings=eval_bindings,
        )

        if not evidence.is_complete():
            raise ValueError("EvidenceChain is incomplete")

        return evidence

    def _semantic_lineage(self, metric_contract, provider_contract):
        """Collect semantic objects + link paths related to this metric.

        Returns (semantic_object_refs, semantic_lineage) tuples. Objects whose
        related_metrics include the metric are collected; all links between
        collected objects form the lineage path.
        """
        from agent_os_contracts import EvidenceObjectLinkRef, EvidenceSemanticObjectRef

        graph = getattr(self._registry, "graph", None)
        if graph is None:
            return (), ()
        related_ids = []
        for obj in graph.objects():
            if metric_contract.metric_name in obj.related_metrics:
                related_ids.append(obj.object_id)
        obj_refs = tuple(
            EvidenceSemanticObjectRef(
                object_id=graph.resolve_object(oid).object_id,
                object_type=graph.resolve_object(oid).object_type,
                name=graph.resolve_object(oid).name,
            )
            for oid in related_ids
        )
        link_refs = []
        for link in graph.links():
            if link.source_object_id in related_ids and link.target_object_id in related_ids:
                link_refs.append(
                    EvidenceObjectLinkRef(
                        link_id=link.link_id,
                        link_type_id=link.link_type_id,
                        source_object_id=link.source_object_id,
                        target_object_id=link.target_object_id,
                    )
                )
        return obj_refs, tuple(link_refs)
