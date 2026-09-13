"""Human-readable rendering of an EvalReport."""

from __future__ import annotations

from .models import EvalReport


def render_report(report: EvalReport) -> str:
    metrics = report.metrics
    lines = [
        f"TERMINAL-AGENT-EVAL-0 — evidence {report.evidence_level.value}",
        f"tasks: {len(report.tasks)}  completion: {metrics.completion_rate:.2%}",
        f"unsafe actions: {metrics.unsafe_action_count}",
        f"approval events: {metrics.approval_event_count}  correction events: {metrics.correction_event_count}",
        f"tokens: {metrics.total_tokens}  cost: {metrics.cost_status.value}",
    ]
    for task in report.tasks:
        mark = "PASS" if task.completed else "FAIL"
        lines.append(
            f"  [{mark}] {task.task_id} ({task.completion_source.value}) "
            f"unsafe={task.unsafe_actions} approvals={task.approvals} "
            f"corrections={task.corrections} tokens={task.tokens}"
        )
    if report.failure_distribution:
        failures = ", ".join(f"{task_id}×{count}" for task_id, count in report.failure_distribution)
        lines.append(f"failures: {failures}")
    lines.append(
        f"note: small task set (n={len(report.tasks)}); fixture/provider arm — "
        "NOT parity or autonomy evidence"
    )
    if report.manifest_sha256:
        lines.append(f"manifest: {report.manifest_sha256[:16]}…")
    if report.provenance:
        lines.append("provenance: " + ", ".join(f"{key}={value}" for key, value in report.provenance))
    return "\n".join(lines)
