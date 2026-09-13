"""TERMINAL-AGENT-EVAL-0 E3 arm — real provider (opt-in).

Runs a small live task set through the REAL product loop with a real
OpenAI-compatible provider configured from the environment. The provider is
built by AgentOSApplication from env (profile `deepseek`); no secret is stored
in code or artifacts.

Environment (all required; the key is never written anywhere):
  AGENT_OS_PROVIDER_PROFILE=deepseek
  DEEPSEEK_BASE_URL=<openai-compatible base url>
  DEEPSEEK_MODEL=<model id>
  DEEPSEEK_API_KEY=<secret>

Evidence E3_REAL_PROVIDER is honored only when this executor declares live
provenance (provider_id != deterministic); the runner enforces that.
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

MANIFEST_PATH = Path(__file__).resolve().parent / "manifests" / "e3_live_basic.json"


def live_provider_available() -> bool:
    if os.environ.get("AGENT_OS_PROVIDER_PROFILE", "").strip().lower() != "deepseek":
        return False
    base = os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("DEEPSEEK_API_URL")
    return bool(os.environ.get("DEEPSEEK_API_KEY")) and bool(base) and bool(
        os.environ.get("DEEPSEEK_MODEL")
    )


def _build_manifest() -> EvalManifest:
    """The E3 task set (written to a frozen file once; used to regenerate)."""
    return freeze_manifest(
        EvalManifest(
            tasks=(
                _task("e3-edit-fixture", "fixture.txt", "fixed"),
                _task("e3-edit-note", "note.txt", "final"),
            )
        )
    )


def _task(task_id: str, filename: str, target: str) -> EvalTask:
    return EvalTask(
        task_id=task_id,
        input=(
            f"Read {filename} with workspace.read, then use workspace.edit to set its "
            f"entire contents to exactly one line: {target}"
        ),
        verify_command=(
            "python",
            "-c",
            f"import pathlib,sys; sys.exit(0 if pathlib.Path('{filename}').read_text()=='{target}\\n' else 1)",
        ),
    )


class _LiveExecutor:
    """One real-provider session per task; no auto-approve tier-3.

    Provenance is captured from a probe AgentOSApplication so the runner can
    refuse an E3 label when the environment is not actually live.
    """

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root
        probe_dir = workspace_root / "_probe"
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe = AgentOSApplication(
            database=probe_dir / "agent-os.sqlite3",
            workspace=probe_dir,
        )
        if not probe.provider_configured:
            raise RuntimeError("live provider is not configured from the environment")
        profile = probe.provider_profile
        if profile.provider_id == "deterministic":
            raise RuntimeError("deterministic provider cannot back the E3 arm")
        self._provenance = {
            "provider_kind": "live",
            "provider_id": profile.provider_id,
            "model_id": profile.model_id,
            "base_url": str(getattr(probe.provider, "base_url", "")),
            "profile": os.environ.get("AGENT_OS_PROVIDER_PROFILE", ""),
            "commit": os.environ.get("GIT_COMMIT", ""),
        }

    def provenance(self) -> Mapping[str, str]:
        return self._provenance

    def run_task(self, task: EvalTask) -> tuple[Sequence[Mapping[str, Any]], bool]:
        root = self._root / task.task_id
        root.mkdir(parents=True, exist_ok=True)
        fixture = FIXTURES.get(task.task_id)
        if fixture is not None:
            (root / fixture[0]).write_text(fixture[1], encoding="utf-8")

        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        if not app.provider_configured or app.provider_profile.provider_id == "deterministic":
            raise RuntimeError("live provider was not configured for the E3 task run")
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
        MANIFEST_PATH,
        executor,
        AutoApproveGateway(),
        SimpleNamespace(risk_tier=3),
        report_json_path=report_json_path,
        evidence_level=EvidenceLevel.E3_REAL_PROVIDER,
    )


def _write_manifest(path: Path) -> None:
    path.write_text(_build_manifest().model_dump_json(indent=2) + "\n", "utf-8")


if __name__ == "__main__":  # regenerate the frozen E3 manifest
    _write_manifest(MANIFEST_PATH)
    print(f"wrote {MANIFEST_PATH}")
