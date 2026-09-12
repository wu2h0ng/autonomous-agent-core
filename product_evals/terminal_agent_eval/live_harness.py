"""TERMINAL-AGENT-EVAL-0 E3 arm — real provider (opt-in).

Runs a small live task set through the REAL product loop with a real
OpenAI-compatible provider configured from the environment. The provider is
built by AgentOSApplication from env (profile `deepseek`), so no secret is
stored in code or artifacts.

Environment (all required; the key is never written anywhere):
  AGENT_OS_PROVIDER_PROFILE=deepseek
  DEEPSEEK_BASE_URL=<openai-compatible base url>
  DEEPSEEK_MODEL=<model id>
  DEEPSEEK_API_KEY=<secret>

Evidence level E3_REAL_PROVIDER: this exercises a real provider call, unlike
the hermetic L1 (E2). It is still a small task set — not parity evidence.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from agent_os_core import AutoApproveGateway

from apps.api_server.app import AgentOSApplication

from product_evals.terminal_agent_eval import EvalTask, freeze_manifest, run_eval
from product_evals.terminal_agent_eval.models import EvalManifest, EvidenceLevel

FIXTURES: dict[str, tuple[str, str]] = {
    "e3-edit-fixture": ("fixture.txt", "stable\n"),
    "e3-edit-note": ("note.txt", "draft\n"),
}


def live_provider_available() -> bool:
    if os.environ.get("AGENT_OS_PROVIDER_PROFILE", "").strip().lower() != "deepseek":
        return False
    base = os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("DEEPSEEK_API_URL")
    return bool(os.environ.get("DEEPSEEK_API_KEY")) and bool(base) and bool(
        os.environ.get("DEEPSEEK_MODEL")
    )


def _e3_manifest() -> EvalManifest:
    return freeze_manifest(
        EvalManifest(
            tasks=(
                EvalTask(
                    task_id="e3-edit-fixture",
                    input=(
                        "Read fixture.txt with workspace.read, then use workspace.edit to set its "
                        "entire contents to exactly one line: fixed"
                    ),
                    verify_command=(
                        "python",
                        "-c",
                        "import pathlib,sys; sys.exit(0 if pathlib.Path('fixture.txt').read_text()=='fixed\\n' else 1)",
                    ),
                ),
                EvalTask(
                    task_id="e3-edit-note",
                    input=(
                        "Read note.txt with workspace.read, then use workspace.edit to set its "
                        "entire contents to exactly one line: final"
                    ),
                    verify_command=(
                        "python",
                        "-c",
                        "import pathlib,sys; sys.exit(0 if pathlib.Path('note.txt').read_text()=='final\\n' else 1)",
                    ),
                ),
            )
        )
    )


class _LiveExecutor:
    """One real-provider session per task; reads durable events; no auto-approve tier-3."""

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root

    def run_task(self, task: EvalTask) -> tuple[Sequence[Mapping[str, Any]], bool]:
        root = self._root / task.task_id
        root.mkdir(parents=True, exist_ok=True)
        fixture = FIXTURES.get(task.task_id)
        if fixture is not None:
            (root / fixture[0]).write_text(fixture[1], encoding="utf-8")

        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        assert app.provider_configured, "live provider was not configured from the environment"
        session, loop = app.open_chat_session("TERMINAL-AGENT-EVAL-0 E3", AutoApproveGateway())
        loop.run_turn(session, task.input)

        events: list[Mapping[str, Any]] = [
            {
                "event_type": str(getattr(event.event_type, "value", event.event_type)),
                "sequence": event.sequence,
                "occurred_at": str(event.occurred_at),
                "payload": event.decoded_payload(),
            }
            for event in app.tasks._event_store.read(session.task_id)  # noqa: SLF001
        ]
        verify = subprocess.run(
            list(task.verify_command), cwd=root, capture_output=True, check=False
        )
        return events, verify.returncode == 0


def run_live_eval(workspace_root: Path, report_json_path: Path | None = None) -> Any:
    executor = _LiveExecutor(workspace_root)
    # AutoApproveGateway admits only tier<3; the probe (synthetic tier-3) must
    # be refused, which it is (returns False).
    return run_eval(
        _e3_manifest(),
        executor,
        AutoApproveGateway(),
        SimpleNamespace(risk_tier=3),
        report_json_path=report_json_path,
        evidence_level=EvidenceLevel.E3_REAL_PROVIDER,
    )
