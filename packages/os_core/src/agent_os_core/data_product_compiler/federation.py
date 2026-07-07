"""Federated query planning for data fabric v1 (ADR-0013 Workstream A)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    DataRequirement,
    FederatedQueryPlan,
    LogicalView,
    MetricContract,
    ProviderContract,
    QueryPlan,
)

from .query_planner import QueryPlanner


class FederationPlanner:
    """Plan a federated query across multiple provider contracts.

    This is a minimal v1 implementation: each provider gets its own sub-query,
    and the results are combined with a ``UNION ALL`` strategy label.  Logical
    views are accepted as input but are not yet wired into sub-query generation.
    """

    def __init__(self, query_planner: QueryPlanner | None = None) -> None:
        self.query_planner = query_planner or QueryPlanner()

    def plan_federated_query(
        self,
        requirement: DataRequirement,
        provider_contracts: tuple[ProviderContract, ...],
        logical_views: tuple[LogicalView, ...],
        *,
        metric_contract: MetricContract | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> FederatedQueryPlan:
        """Build a federated plan for the given providers.

        ``metric_contract`` and ``parameters`` are required to produce real
        sub-queries via :class:`QueryPlanner`.  When omitted, placeholder
        sub-queries are emitted so the structure can still be inspected.
        """
        sub_queries: list[QueryPlan] = []
        for provider in provider_contracts:
            if metric_contract is not None and parameters is not None:
                sub_queries.append(
                    self.query_planner.plan(
                        metric_contract=metric_contract,
                        parameters=parameters,
                        provider_contract=provider,
                    )
                )
            else:
                sub_queries.append(
                    QueryPlan(
                        metric_name=requirement.metric_names[0] if requirement.metric_names else "",
                        sql=f"-- federated sub-query for {provider.provider_id}",
                        parameters={},
                        source_template=None,
                    )
                )
        return FederatedQueryPlan(
            plan_id=f"federated-{uuid4().hex[:12]}",
            sub_queries=tuple(sub_queries),
            combine_strategy="UNION ALL",
        )


__all__ = ["FederationPlanner"]
