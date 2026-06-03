from __future__ import annotations

import re
from uuid import uuid4

from agent_os_contracts import (
    BusinessIntent,
    DataProductCandidate,
    DataRequirement,
    LineageSnapshot,
    MetricContract,
    ProviderContract,
    QueryPlan,
)

TABLE_REF = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)",
    re.IGNORECASE,
)


class DataProductCompiler:
    """Compiles intent and semantic contracts into MVP data product candidates."""

    def compile_requirement(
        self,
        *,
        intent: BusinessIntent,
        metric_contract: MetricContract,
        provider_contract: ProviderContract,
        parameters: dict[str, object],
    ) -> DataRequirement:
        time_window = {
            key: parameters[key] for key in ("start_date", "end_date") if key in parameters
        }
        return DataRequirement(
            requirement_id=f"requirement-{uuid4().hex[:12]}",
            intent_id=intent.intent_id,
            metric_names=(metric_contract.metric_name,),
            dimensions=metric_contract.dimensions,
            time_window=time_window,
            provider_ids=(provider_contract.provider_id,),
        )

    def build_lineage_snapshot(
        self,
        *,
        provider_contract: ProviderContract,
        query_plan: QueryPlan,
    ) -> LineageSnapshot:
        return LineageSnapshot(
            lineage_id=f"lineage-{uuid4().hex[:12]}",
            provider_id=provider_contract.provider_id,
            source_objects=tuple(TABLE_REF.findall(query_plan.sql)),
            generated_by="data_product_compiler",
            metadata={"metric_name": query_plan.metric_name},
        )

    def build_candidate(
        self,
        *,
        requirement: DataRequirement,
        metric_contract: MetricContract,
        query_plan: QueryPlan,
        lineage_snapshot: LineageSnapshot,
    ) -> DataProductCandidate:
        return DataProductCandidate(
            data_product_id=f"data-product-{uuid4().hex[:12]}",
            requirement_id=requirement.requirement_id,
            name=f"{metric_contract.metric_name}_candidate",
            owner=metric_contract.owner,
            query_plan_id=query_plan.metric_name,
            lineage_snapshot_id=lineage_snapshot.lineage_id,
            quality_status="unchecked",
        )
