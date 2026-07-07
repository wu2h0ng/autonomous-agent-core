"""Composition-layer heavy infrastructure adapters (ADR-0013 workstream G).

Fail-closed disabled adapters when feature flags are off. No Temporal/OPA/Trino
SDK imports — production wiring is a later deployment slice.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_os_contracts import (
    OpPolicyEvaluationPort,
    OpPolicyEvaluationRequest,
    OpPolicyEvaluationResult,
    RuntimeFeatureFlags,
    TemporalOrchestrationPort,
    TemporalScheduleRequest,
    TemporalScheduleResult,
    TrinoExplainRequest,
    TrinoExplainResult,
    TrinoFederationPort,
)


class DisabledTemporalOrchestration(TemporalOrchestrationPort):
    def schedule(self, request: TemporalScheduleRequest) -> TemporalScheduleResult:
        return TemporalScheduleResult(
            workflow_id=request.workflow_id,
            status="disabled",
            detail="temporal_orchestration flag is off",
        )


class DisabledOpPolicyEvaluation(OpPolicyEvaluationPort):
    def evaluate(self, request: OpPolicyEvaluationRequest) -> OpPolicyEvaluationResult:
        return OpPolicyEvaluationResult(
            allowed=False,
            status="disabled",
            violations=("opa_external_policy flag is off",),
        )


class DisabledTrinoFederation(TrinoFederationPort):
    def explain(self, request: TrinoExplainRequest) -> TrinoExplainResult:
        return TrinoExplainResult(
            status="disabled",
            plan_summary="trino_federation flag is off",
        )


@dataclass(frozen=True)
class HeavyInfrastructureAdapters:
    temporal: TemporalOrchestrationPort
    opa: OpPolicyEvaluationPort
    trino: TrinoFederationPort


def build_heavy_infrastructure_adapters(
    flags: RuntimeFeatureFlags,
) -> HeavyInfrastructureAdapters:
    """Return adapter instances for workstream G (disabled stubs unless flags on).

    Even when flags are on, this slice ships fail-closed placeholders until real
    endpoints are configured in a deployment-specific composition module.
    """
    if flags.temporal_orchestration:
        temporal: TemporalOrchestrationPort = _FlagOnTemporalPlaceholder()
    else:
        temporal = DisabledTemporalOrchestration()
    if flags.opa_external_policy:
        opa: OpPolicyEvaluationPort = _FlagOnOpaPlaceholder()
    else:
        opa = DisabledOpPolicyEvaluation()
    if flags.trino_federation:
        trino: TrinoFederationPort = _FlagOnTrinoPlaceholder()
    else:
        trino = DisabledTrinoFederation()
    return HeavyInfrastructureAdapters(temporal=temporal, opa=opa, trino=trino)


class _FlagOnTemporalPlaceholder(TemporalOrchestrationPort):
    def schedule(self, request: TemporalScheduleRequest) -> TemporalScheduleResult:
        return TemporalScheduleResult(
            workflow_id=request.workflow_id,
            status="error",
            detail="temporal endpoint not configured",
        )


class _FlagOnOpaPlaceholder(OpPolicyEvaluationPort):
    def evaluate(self, request: OpPolicyEvaluationRequest) -> OpPolicyEvaluationResult:
        return OpPolicyEvaluationResult(
            allowed=False,
            status="error",
            violations=("opa endpoint not configured",),
        )


class _FlagOnTrinoPlaceholder(TrinoFederationPort):
    def explain(self, request: TrinoExplainRequest) -> TrinoExplainResult:
        return TrinoExplainResult(status="error", plan_summary="trino endpoint not configured")


__all__ = [
    "DisabledOpPolicyEvaluation",
    "DisabledTemporalOrchestration",
    "DisabledTrinoFederation",
    "HeavyInfrastructureAdapters",
    "build_heavy_infrastructure_adapters",
]
