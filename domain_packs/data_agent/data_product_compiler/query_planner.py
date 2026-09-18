"""QueryPlanner selects a verified SQL template and binds runtime parameters."""

from __future__ import annotations

from typing import Any

from ..domain_contracts import MetricContract, ProviderContract, QueryPlan, SQLTemplate


class QueryPlanner:
    """Turn a metric contract and runtime parameters into an executable QueryPlan.

    The planner picks the first verified query whose ``required_parameters`` are
    all present in the supplied parameters.  It then binds the time-window
    parameters (default ``start_date`` and ``end_date``) and any additional
    required parameters into the final parameter map.
    """

    def plan(
        self,
        metric_contract: MetricContract,
        parameters: dict[str, Any],
        provider_contract: ProviderContract,
    ) -> QueryPlan:
        template = self._select_template(metric_contract, parameters)
        bound = self._bind_parameters(template, parameters)
        return QueryPlan(
            metric_name=metric_contract.metric_name,
            sql=template.sql,
            parameters=bound,
            source_template=template,
        )

    def _select_template(
        self, metric_contract: MetricContract, parameters: dict[str, Any]
    ) -> SQLTemplate:
        verified = metric_contract.verified_queries
        if not verified:
            raise QueryPlanningError(
                f"MetricContract {metric_contract.metric_name} has no verified_queries"
            )

        for template in verified:
            if all(
                param in parameters
                or (
                    param == "limit"
                    and template.default_limit is not None
                    and template.default_limit > 0
                )
                for param in template.required_parameters
            ):
                return template

        raise QueryPlanningError(
            f"No verified query for {metric_contract.metric_name} matches supplied parameters"
        )

    def _bind_parameters(self, template: SQLTemplate, parameters: dict[str, Any]) -> dict[str, Any]:
        bound: dict[str, Any] = {}
        for param in template.required_parameters:
            if param not in parameters:
                if param == "limit" and template.default_limit is not None:
                    bound[param] = template.default_limit
                    continue
                raise QueryPlanningError(f"Missing required parameter: {param}")
            bound[param] = parameters[param]
        for param in template.required_time_parameters:
            if param not in parameters:
                raise QueryPlanningError(f"Missing required time parameter: {param}")
            bound[param] = parameters[param]
        return bound


class QueryPlanningError(Exception):
    """Raised when a query cannot be planned from the metric contract and parameters."""
