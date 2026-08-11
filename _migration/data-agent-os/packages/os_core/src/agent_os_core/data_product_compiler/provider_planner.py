"""ProviderPlanner selects a concrete provider for a DataRequirement."""

from __future__ import annotations

from agent_os_contracts import DataRequirement, MetricContract, ProviderContract

from ..data_access_plane import ProviderRegistry


class ProviderPlanner:
    """Choose the provider contract that can satisfy a data requirement.

    The planner looks up the requirement's preferred ``provider_ids`` first;
    if none are specified, it falls back to schema matching via the registry
    using the metric contract's allowed schemas.
    """

    def plan(
        self,
        requirement: DataRequirement,
        metric_contract: MetricContract,
        provider_registry: ProviderRegistry,
    ) -> ProviderContract:
        if requirement.provider_ids:
            # Use the first requested provider that exists.
            for provider_id in requirement.provider_ids:
                try:
                    return provider_registry.get(provider_id)
                except KeyError:
                    continue
            raise ProviderPlanningError(
                f"None of the requested providers are registered: {requirement.provider_ids}"
            )

        try:
            return provider_registry.choose_for_schemas(metric_contract.allowed_schemas)
        except KeyError as exc:
            raise ProviderPlanningError(str(exc)) from exc


class ProviderPlanningError(Exception):
    """Raised when no registered provider can satisfy a data requirement."""
