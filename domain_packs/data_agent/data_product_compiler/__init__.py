from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from ..domain_contracts import (
    BusinessIntent,
    DataProductCandidate,
    DataRequirement,
    FederatedQueryPlan,
    LineageSnapshot,
    LogicalView,
    MaterializationHint,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryPlan,
    RuntimeFeatureFlags,
)

from ..data_access_plane import ProviderRegistry
from .federation import FederationPlanner
from .provider_planner import ProviderPlanner, ProviderPlanningError as ProviderPlanningError
from .query_planner import QueryPlanner, QueryPlanningError as QueryPlanningError

__all__ = [
    "DataProductCompiler",
    "FederationPlanner",
    "ProviderPlanningError",
    "QueryPlanningError",
]

TABLE_REF = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)?)",
    re.IGNORECASE,
)


class DataProductCompiler:
    """Compiles intent and semantic contracts into MVP data product candidates."""

    def __init__(
        self,
        provider_planner: ProviderPlanner | None = None,
        query_planner: QueryPlanner | None = None,
        federation_planner: FederationPlanner | None = None,
    ) -> None:
        self.provider_planner = provider_planner or ProviderPlanner()
        self.query_planner = query_planner or QueryPlanner()
        self.federation_planner = federation_planner or FederationPlanner(self.query_planner)

    def compile(
        self,
        *,
        intent: BusinessIntent,
        metric_contract: MetricContract,
        parameters: dict[str, Any],
        provider_registry: ProviderRegistry,
        provider_ids: tuple[str, ...] | None = None,
        logical_views: tuple[LogicalView, ...] | None = None,
        materialization_hints: tuple[MaterializationHint, ...] | None = None,
        feature_flags: RuntimeFeatureFlags | None = None,
    ) -> dict[str, object]:
        """Run the full compile pipeline and return intermediate artifacts.

        Returns a dict with keys: ``requirement``, ``provider_contract``,
        ``query_plan``, ``lineage_snapshot``, ``data_product_candidate``.

        When ``RuntimeFeatureFlags.data_fabric_v1`` is enabled and the
        requirement spans multiple providers, a :class:`FederatedQueryPlan` is
        returned instead of a single :class:`QueryPlan`.
        """
        feature_flags = feature_flags or RuntimeFeatureFlags()
        logical_views = logical_views or ()
        materialization_hints = materialization_hints or ()

        requirement = self.compile_requirement(
            intent=intent,
            metric_contract=metric_contract,
            provider_contract=ProviderContract(
                provider_id="placeholder",
                kind=ProviderKind.WAREHOUSE,
                name="placeholder",
                owner="system",
                allowed_schemas=metric_contract.allowed_schemas,
            ),
            parameters=parameters,
            provider_ids=provider_ids,
        )

        if feature_flags.data_fabric_v1 and len(requirement.provider_ids) > 1:
            provider_contracts = tuple(
                provider_registry.get(provider_id) for provider_id in requirement.provider_ids
            )
            query_plan: QueryPlan | FederatedQueryPlan = (
                self.federation_planner.plan_federated_query(
                    requirement=requirement,
                    provider_contracts=provider_contracts,
                    logical_views=logical_views,
                    metric_contract=metric_contract,
                    parameters=parameters,
                )
            )
            provider_contract: ProviderContract | None = None
        else:
            provider_contract = self.provider_planner.plan(
                requirement=requirement,
                metric_contract=metric_contract,
                provider_registry=provider_registry,
            )
            query_plan = self.query_planner.plan(
                metric_contract=metric_contract,
                parameters=parameters,
                provider_contract=provider_contract,
            )

        lineage_snapshot = self.build_lineage_snapshot(
            provider_contract=provider_contract,
            query_plan=query_plan,
        )
        data_product_candidate = self.build_candidate(
            requirement=requirement,
            metric_contract=metric_contract,
            query_plan=query_plan,
            lineage_snapshot=lineage_snapshot,
            materialization_hints=materialization_hints,
        )
        return {
            "requirement": requirement,
            "provider_contract": provider_contract,
            "query_plan": query_plan,
            "lineage_snapshot": lineage_snapshot,
            "data_product_candidate": data_product_candidate,
        }

    def compile_requirement(
        self,
        *,
        intent: BusinessIntent,
        metric_contract: MetricContract,
        provider_contract: ProviderContract,
        parameters: dict[str, object],
        provider_ids: tuple[str, ...] | None = None,
    ) -> DataRequirement:
        """Build a provider-agnostic data requirement from intent and metric.

        ``provider_contract`` is retained for backward compatibility with callers
        that already pass it; the requirement no longer embeds a provider choice
        so that :class:`ProviderPlanner` can make that decision downstream.
        """
        del provider_contract
        time_window = {
            key: parameters[key] for key in ("start_date", "end_date") if key in parameters
        }
        return DataRequirement(
            requirement_id=f"requirement-{uuid4().hex[:12]}",
            intent_id=intent.intent_id,
            metric_names=(metric_contract.metric_name,),
            dimensions=metric_contract.dimensions,
            time_window=time_window,
            provider_ids=provider_ids or (),
        )

    def build_lineage_snapshot(
        self,
        *,
        provider_contract: ProviderContract | None,
        query_plan: QueryPlan | FederatedQueryPlan,
    ) -> LineageSnapshot:
        if isinstance(query_plan, FederatedQueryPlan):
            source_objects: tuple[str, ...] = tuple(
                table for sub in query_plan.sub_queries for table in TABLE_REF.findall(sub.sql)
            )
            provider_id = provider_contract.provider_id if provider_contract else "federated"
            metric_name = query_plan.sub_queries[0].metric_name if query_plan.sub_queries else ""
        else:
            source_objects = tuple(TABLE_REF.findall(query_plan.sql))
            provider_id = provider_contract.provider_id if provider_contract else "unknown"
            metric_name = query_plan.metric_name
        return LineageSnapshot(
            lineage_id=f"lineage-{uuid4().hex[:12]}",
            provider_id=provider_id,
            source_objects=source_objects,
            generated_by="data_product_compiler",
            metadata={"metric_name": metric_name},
        )

    def build_candidate(
        self,
        *,
        requirement: DataRequirement,
        metric_contract: MetricContract,
        query_plan: QueryPlan | FederatedQueryPlan,
        lineage_snapshot: LineageSnapshot,
        materialization_hints: tuple[MaterializationHint, ...] | None = None,
    ) -> DataProductCandidate:
        metadata: dict[str, Any] = {}
        if materialization_hints:
            metadata["materialization_hints"] = materialization_hints
        query_plan_id = (
            query_plan.plan_id
            if isinstance(query_plan, FederatedQueryPlan)
            else query_plan.metric_name
        )
        return DataProductCandidate(
            data_product_id=f"data-product-{uuid4().hex[:12]}",
            requirement_id=requirement.requirement_id,
            name=f"{metric_contract.metric_name}_candidate",
            owner=metric_contract.owner,
            query_plan_id=query_plan_id,
            lineage_snapshot_id=lineage_snapshot.lineage_id,
            quality_status="unchecked",
            metadata=metadata,
        )
