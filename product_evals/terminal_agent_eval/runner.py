"""Eval runner: orchestrate frozen tasks through an injectable TurnExecutor.

The product executor (driving the real surface/Task pipeline) is a separate
slice; this module owns the instrument: gateway probing, per-task projection
and report assembly. `TurnExecutor` returns the durable events produced for a
task plus the harness-local acceptance result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .gateway import assert_no_tier3_auto_approval
from .manifest import EvalManifest, load_manifest, verify_manifest
from .metrics import failure_distribution, project_task, summarize
from .models import EvalReport, EvalTask, EvidenceLevel
from .report import render_report


class EvidenceLevelError(Exception):
    """Raised when an evidence level is claimed without the required provenance."""


class TurnExecutor(Protocol):
    def run_task(self, task: EvalTask) -> tuple[Sequence[Mapping[str, Any]], bool]:
        """Run one task; return (durable_events, harness_verify_ok)."""
        ...


def _live_provenance(executor: TurnExecutor) -> dict[str, str]:
    """Return executor provenance, raising if a live level is claimed without it."""
    provider = getattr(executor, "provenance", None)
    if not callable(provider):
        raise EvidenceLevelError("E3_REAL_PROVIDER requires an executor with provenance()")
    raw = provider()
    if not isinstance(raw, Mapping):
        raise EvidenceLevelError("executor provenance must be a mapping")
    declared = {str(key): str(value) for key, value in raw.items()}
    if declared.get("provider_kind") != "live" or not declared.get("provider_id"):
        raise EvidenceLevelError("executor does not declare live provider provenance")
    if declared.get("provider_id") == "deterministic":
        raise EvidenceLevelError("deterministic executor cannot claim E3_REAL_PROVIDER")
    return declared


class EvalRunner:
    def __init__(
        self,
        executor: TurnExecutor,
        gateway: Any,
        probe_action: Any,
        evidence_level: EvidenceLevel = EvidenceLevel.E2_CONTROLLED_SIMULATION,
        arm: str | None = None,
    ) -> None:
        self._executor = executor
        self._gateway = gateway
        self._probe_action = probe_action
        self._evidence_level = evidence_level
        self._arm = arm

    def run(self, manifest: EvalManifest) -> EvalReport:
        # Fail-closed before any task runs.
        assert_no_tier3_auto_approval(self._gateway, self._probe_action)
        provenance: dict[str, str] = {}
        if self._evidence_level is EvidenceLevel.E3_REAL_PROVIDER:
            provenance = _live_provenance(self._executor)
        results = []
        for task in manifest.tasks:
            events, verify_ok = self._executor.run_task(task)
            results.append(project_task(events, task.task_id, verify_ok, task.task_kind))
        return EvalReport(
            evidence_level=self._evidence_level,
            arm=self._arm,
            manifest_sha256=manifest.manifest_sha256,
            provenance=tuple(sorted(provenance.items())),
            metrics=summarize(results),
            tasks=tuple(results),
            failure_distribution=failure_distribution(results),
        )


def run_eval(
    manifest: EvalManifest | str | Path,
    executor: TurnExecutor,
    gateway: Any,
    probe_action: Any,
    *,
    report_json_path: str | Path | None = None,
    report_text_path: str | Path | None = None,
    evidence_level: EvidenceLevel = EvidenceLevel.E2_CONTROLLED_SIMULATION,
    arm: str | None = None,
) -> EvalReport:
    """Public entry point for TERMINAL-AGENT-EVAL-0.

    The manifest is the freeze boundary: a path is loaded and digest-verified,
    and an in-memory manifest is accepted only if already frozen and valid.
    """
    resolved = load_manifest(manifest) if isinstance(manifest, (str, Path)) else verify_manifest(manifest)
    report = EvalRunner(executor, gateway, probe_action, evidence_level, arm).run(resolved)
    if report_json_path is not None:
        Path(report_json_path).write_text(report.model_dump_json(indent=2) + "\n", "utf-8")
    if report_text_path is not None:
        Path(report_text_path).write_text(render_report(report) + "\n", "utf-8")
    return report
