"""TERMINAL-AGENT-EVAL-0 — product eval instrument (GC/CP-AB 2026-09-13)."""

from __future__ import annotations

from .gateway import EvalGatewayViolation, assert_no_tier3_auto_approval
from .manifest import (
    ManifestIntegrityError,
    freeze_manifest,
    load_manifest,
    manifest_digest,
    verify_manifest,
)
from .metrics import (
    count_approvals,
    count_corrections,
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
    TaskResult,
)
from .report import render_report
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
    "TaskResult",
    "TurnExecutor",
    "assert_no_tier3_auto_approval",
    "count_approvals",
    "count_corrections",
    "count_unsafe_actions",
    "durable_outcome_verified",
    "freeze_manifest",
    "load_manifest",
    "manifest_digest",
    "project_task",
    "render_report",
    "run_eval",
    "summarize",
    "total_tokens",
    "verify_manifest",
]
