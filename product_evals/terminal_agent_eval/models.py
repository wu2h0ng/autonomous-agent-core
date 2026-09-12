"""Typed contracts for TERMINAL-AGENT-EVAL-0 (product eval instrument).

Evidence level is E2_CONTROLLED_SIMULATION: the L1 task set is a deterministic
hermetic fixture, never parity evidence. Cost is unconditionally UNKNOWN under
L1 (ProviderUsage exposes no pricing_source_ref and this instrument changes no
contract).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class EvidenceLevel(str, Enum):
    E2_CONTROLLED_SIMULATION = "E2_CONTROLLED_SIMULATION"


class CostStatus(str, Enum):
    UNKNOWN = "UNKNOWN"


class CompletionSource(str, Enum):
    DURABLE_OUTCOME = "durable_outcome"
    HARNESS_LOCAL = "harness_local"


class EvalTask(BaseModel):
    """One frozen task: input, the independent acceptance command, digests."""

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(min_length=1)
    input: str = Field(min_length=1)
    verify_command: tuple[str, ...] = Field(min_length=1)
    expected_outcome: str | None = None
    file_digests: tuple[tuple[str, str], ...] = ()


class EvalManifest(BaseModel):
    """Frozen task set. `manifest_sha256` covers schema_version + tasks."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    tasks: tuple[EvalTask, ...] = Field(min_length=1)
    manifest_sha256: str | None = None


class TaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    completed: bool
    completion_source: CompletionSource
    unsafe_actions: int = 0
    approvals: int = 0
    corrections: int = 0
    tokens: int = 0


class MetricSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    completion_rate: float
    unsafe_action_count: int
    approval_event_count: int
    correction_event_count: int
    total_tokens: int
    cost_status: CostStatus = CostStatus.UNKNOWN


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_level: EvidenceLevel = EvidenceLevel.E2_CONTROLLED_SIMULATION
    metrics: MetricSummary
    tasks: tuple[TaskResult, ...]
    failure_distribution: tuple[tuple[str, int], ...] = ()
