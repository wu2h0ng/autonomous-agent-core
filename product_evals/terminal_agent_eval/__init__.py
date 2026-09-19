"""TERMINAL-AGENT-EVAL-0 — product eval instrument (GC/CP-AB 2026-09-13).

TERMINAL-CODING-EVAL-1 (`coding_tasks`, `coding_solver`, `coding_harness`,
`coding_live`) is the terminal coding corpus built on this instrument; those
modules pull in `apps.api_server`, so they are imported explicitly by their
harness/CLI and are deliberately not re-exported here.
"""

from __future__ import annotations

from .gateway import EvalGatewayViolation, assert_no_tier3_auto_approval
from .manifest import (
    ManifestIntegrityError,
    freeze_manifest,
    load_manifest,
    manifest_digest,
    refreeze_manifest,
    verify_manifest,
)
from .metrics import (
    count_approvals,
    count_corrections,
    count_denials,
    count_provider_steps,
    count_tool_calls,
    count_turns,
    count_unsafe_actions,
    durable_outcome_verified,
    project_task,
    summarize,
    total_tokens,
)
from .models import (
    CompletionSource,
    CostStatus,
    EvalManifest,
    EvalReport,
    EvalTask,
    EvidenceLevel,
    MetricSummary,
    OperatorPolicy,
    TaskKind,
    TaskResult,
)
from .report import render_report
from .product_executor import ProductTurnExecutor, SurfaceSessionClient
from .runner import EvalRunner, TurnExecutor, run_eval

__all__ = [
    "CompletionSource",
    "CostStatus",
    "EvalGatewayViolation",
    "EvalManifest",
    "EvalReport",
    "EvalRunner",
    "EvalTask",
    "EvidenceLevel",
    "ManifestIntegrityError",
    "MetricSummary",
    "OperatorPolicy",
    "ProductTurnExecutor",
    "SurfaceSessionClient",
    "TaskKind",
    "TaskResult",
    "TurnExecutor",
    "assert_no_tier3_auto_approval",
    "count_approvals",
    "count_corrections",
    "count_denials",
    "count_provider_steps",
    "count_tool_calls",
    "count_turns",
    "count_unsafe_actions",
    "durable_outcome_verified",
    "freeze_manifest",
    "load_manifest",
    "manifest_digest",
    "project_task",
    "refreeze_manifest",
    "render_report",
    "run_eval",
    "summarize",
    "total_tokens",
    "verify_manifest",
]
