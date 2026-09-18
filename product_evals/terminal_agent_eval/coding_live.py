"""TERMINAL-CODING-EVAL-1 live arm (opt-in): the same corpus, a real model.

This is the only arm that measures terminal coding capability. It runs the
frozen corpus through the real product loop with the provider the environment
configures (an OpenAI-compatible / Anthropic / Gemini endpoint), one session
per task, and reads back the same durable events and the same harness-owned
acceptance graders the offline arms use.

Rules this module enforces:

- a real provider must be configured before any task runs (`live_provider_available`),
  and the workspace root must be given explicitly — state never goes to a
  shared or default location;
- the runner stamps E3_REAL_PROVIDER only because this executor declares live
  provenance; a deterministic provider cannot be labelled live;
- the operator policy is the task's frozen policy, so a tier>=3 shell command
  and a confirmation-required edit fail closed exactly as they do offline;
- no credential is ever read into a report: provenance carries provider id,
  model id, base URL and commit only.

Usage (workspace must be a directory you own, e.g. under a temp dir)::

    AGENT_OS_PROVIDER_PROFILE=<kimi|openai|anthropic|deepseek|gemini> ... \
    python -m product_evals.terminal_agent_eval.coding_harness \
        --live --workspace /tmp/terminal-coding-eval-live --out-dir <run dir>
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_os_core import AutoApproveGateway, NonInteractiveDenyGateway

from apps.api_server.app import AgentOSApplication

from .coding_harness import SUITE_NAME, CodingEvalError, VERIFY_TIMEOUT_SECONDS
from .coding_tasks import MANIFEST_PATH, verify_fixture_digests
from .manifest import load_manifest
from .models import EvidenceLevel, EvalManifest, EvalReport, EvalTask, OperatorPolicy
from .provider_isolation import isolated_provider_config
from .runner import run_eval

_PROFILE_PREFIXES = {
    "kimi": "KIMI",
    "openai": "OPENAI",
    "anthropic": "ANTHROPIC",
    "deepseek": "DEEPSEEK",
    "gemini": "GEMINI",
}

# Synthetic tier-3 action for the runner's gateway probe: a gateway that
# auto-approves it would make the unsafe-action metric blind to a real bypass.
_PROBE_ACTION = SimpleNamespace(risk_tier=3)


def live_provider_available() -> bool:
    """True only when a full live provider configuration is present in the env."""
    profile = os.environ.get("AGENT_OS_PROVIDER_PROFILE", "").strip().lower()
    prefix = _PROFILE_PREFIXES.get(profile)
    if prefix is None:
        return False
    base = os.environ.get(f"{prefix}_BASE_URL") or os.environ.get(f"{prefix}_API_URL")
    return bool(base) and bool(os.environ.get(f"{prefix}_API_KEY")) and bool(
        os.environ.get(f"{prefix}_MODEL")
    )


def _gateway_for(task: EvalTask) -> Any:
    if task.operator_policy is OperatorPolicy.DENY_CONFIRMATIONS:
        return NonInteractiveDenyGateway()
    return AutoApproveGateway()


class LiveCodingExecutor:
    """One real-provider session per task; explicit workspace; no auto-approve tier 3."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        manifest: EvalManifest,
        verify_timeout_seconds: float = VERIFY_TIMEOUT_SECONDS,
    ) -> None:
        self._root = workspace_root
        self._manifest = manifest
        self._verify_timeout = verify_timeout_seconds
        self.acceptance_detail: dict[str, str] = {}
        self._provenance = _probe_provenance(workspace_root)

    def provenance(self) -> Mapping[str, str]:
        return self._provenance

    def run_task(self, task: EvalTask) -> tuple[Sequence[Mapping[str, Any]], bool]:
        root = self._root / task.task_id
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        for relative, content in task.fixture:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        if not app.provider_configured or app.provider_profile.provider_id == "deterministic":
            raise CodingEvalError("the live arm requires a configured non-deterministic provider")
        session, loop = app.open_chat_session(
            f"{SUITE_NAME} live {task.task_id}",
            _gateway_for(task),
        )
        loop.run_turn(session, task.input)

        events = [
            {
                "event_type": str(getattr(event.event_type, "value", event.event_type)),
                "sequence": event.sequence,
                "occurred_at": str(event.occurred_at),
                "payload": event.decoded_payload(),
            }
            for event in app.tasks._event_store.read(session.task_id)  # noqa: SLF001
        ]
        return events, self._verify(task, root)

    def _verify(self, task: EvalTask, root: Path) -> bool:
        try:
            completed = subprocess.run(
                list(task.verify_command),
                cwd=root,
                capture_output=True,
                text=True,
                timeout=self._verify_timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.acceptance_detail[task.task_id] = f"acceptance command failed to run: {exc}"
            return False
        ok = completed.returncode == 0
        output = (completed.stdout + completed.stderr).strip()
        self.acceptance_detail[task.task_id] = (
            f"exit {completed.returncode}" + (f" | {output[-400:]}" if output else "")
        )
        return ok


def _probe_provenance(workspace_root: Path) -> Mapping[str, str]:
    if not live_provider_available():
        raise CodingEvalError(
            "no live provider is configured; set AGENT_OS_PROVIDER_PROFILE and its "
            "BASE_URL / MODEL / API_KEY variables"
        )
    probe_root = workspace_root / "_probe"
    probe_root.mkdir(parents=True, exist_ok=True)
    with isolated_provider_config(probe_root):
        probe = AgentOSApplication(
            database=probe_root / "agent-os.sqlite3", workspace=probe_root
        )
        if not probe.provider_configured:
            raise CodingEvalError("the configured live provider could not be installed")
        profile = probe.provider_profile
        base_url = str(getattr(probe.provider, "base_url", ""))
    # Only an explicitly configured provider may be labelled live. The
    # operator's persisted provider config is deliberately out of reach here
    # (see provider_isolation), so a run cannot be stamped E3 from state the
    # operator did not hand to this eval.
    if profile.provider_id == "deterministic":
        raise CodingEvalError("a deterministic provider cannot back the live coding arm")
    return {
        "provider_kind": "live",
        "provider_id": profile.provider_id,
        "model_id": profile.model_id,
        "base_url": base_url,
        "profile": os.environ.get("AGENT_OS_PROVIDER_PROFILE", ""),
        "commit": os.environ.get("GIT_COMMIT", ""),
    }


def run_live_coding_arm(
    workspace_root: str | Path,
    *,
    manifest_path: str | Path = MANIFEST_PATH,
    report_json_path: str | Path | None = None,
) -> EvalReport:
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    verify_fixture_digests(manifest)
    # Only an env-configured provider may back an E3 claim: the operator's
    # persisted provider config stays out of reach for the whole run.
    with isolated_provider_config(root):
        executor = LiveCodingExecutor(root, manifest=manifest)
        report = run_eval(
            manifest,
            executor,
            AutoApproveGateway(),
            _PROBE_ACTION,
            arm="live",
            report_json_path=report_json_path,
            evidence_level=EvidenceLevel.E3_REAL_PROVIDER,
        )
    if report_json_path is not None and executor.acceptance_detail:
        detail = "\n".join(
            f"{task}: {text}" for task, text in sorted(executor.acceptance_detail.items())
        )
        Path(report_json_path).with_name("acceptance.live.txt").write_text(
            detail + "\n", "utf-8"
        )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=f"{SUITE_NAME} live arm")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not live_provider_available():
        print(
            "no live provider configured: set AGENT_OS_PROVIDER_PROFILE plus "
            "<PROFILE>_BASE_URL, <PROFILE>_MODEL and <PROFILE>_API_KEY",
            file=sys.stderr,
        )
        return 2
    report = run_live_coding_arm(args.workspace, report_json_path=args.out)
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
