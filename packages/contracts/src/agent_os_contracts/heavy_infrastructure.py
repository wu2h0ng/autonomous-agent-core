"""Heavy infrastructure adapter contracts (ADR-0013 workstream G).

Temporal, OPA, and Trino/Calcite integrations live outside OS Core as injectable
ports. Concrete SDK clients belong in the composition layer only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TemporalScheduleRequest:
    workflow_type: str
    task_queue: str
    workflow_id: str
    input_payload: dict[str, Any]
    tenant_id: str = "default"


@dataclass(frozen=True)
class TemporalScheduleResult:
    workflow_id: str
    status: str  # "scheduled" | "disabled" | "error"
    detail: str = ""


@dataclass(frozen=True)
class OpPolicyEvaluationRequest:
    policy_path: str
    input_document: dict[str, Any]
    tenant_id: str = "default"


@dataclass(frozen=True)
class OpPolicyEvaluationResult:
    allowed: bool
    status: str  # "allowed" | "denied" | "disabled" | "error"
    violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrinoExplainRequest:
    sql: str
    catalog: str
    schema: str
    tenant_id: str = "default"


@dataclass(frozen=True)
class TrinoExplainResult:
    status: str  # "ok" | "disabled" | "error"
    plan_summary: str = ""


class TemporalOrchestrationPort(ABC):
    @abstractmethod
    def schedule(self, request: TemporalScheduleRequest) -> TemporalScheduleResult: ...


class OpPolicyEvaluationPort(ABC):
    @abstractmethod
    def evaluate(self, request: OpPolicyEvaluationRequest) -> OpPolicyEvaluationResult: ...


class TrinoFederationPort(ABC):
    @abstractmethod
    def explain(self, request: TrinoExplainRequest) -> TrinoExplainResult: ...


__all__ = [
    "OpPolicyEvaluationPort",
    "OpPolicyEvaluationRequest",
    "OpPolicyEvaluationResult",
    "TemporalOrchestrationPort",
    "TemporalScheduleRequest",
    "TemporalScheduleResult",
    "TrinoExplainRequest",
    "TrinoExplainResult",
    "TrinoFederationPort",
]
