"""TERMINAL-AGENT-EVAL-0 L1 end-to-end harness (hermetic, in-process).

Runs the frozen L1 manifest through the REAL product loop
(AgentOSApplication + DeterministicProvider + AutoApproveGateway) and writes an
E2 report. This is the run-harness for the instrument: it proves the frozen
tasks actually run and project, not that the agent is good.

Boundary: deterministic hermetic fixture + scripted provider -> E2 only, never
parity/autonomy evidence.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from agent_os_contracts import ProviderToolProposal
from agent_os_core import AutoApproveGateway, DeterministicProvider

from apps.api_server.app import AgentOSApplication

from product_evals.terminal_agent_eval import EvalTask, freeze_manifest, run_eval
from product_evals.terminal_agent_eval.models import EvalManifest


def _proposal(call_id: str, capability_id: str, arguments: dict[str, object]) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _scenario_fix_fixture(root: Path) -> tuple[str, str, tuple]:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    scripted = (
        ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
        (
            "",
            (
                _proposal(
                    "call-2",
                    "workspace.edit",
                    {"path": "fixture.txt", "old_string": "stable", "new_string": "fixed"},
                ),
            ),
        ),
        ("fixture fixed", ()),
    )
    return "fix the failing fixture", "fixture fixed", scripted


def _scenario_add_note(root: Path) -> tuple[str, str, tuple]:
    (root / "note.txt").write_text("draft\n", encoding="utf-8")
    scripted = (
        ("", (_proposal("call-1", "workspace.read", {"path": "note.txt"}),)),
        (
            "",
            (
                _proposal(
                    "call-2",
                    "workspace.edit",
                    {"path": "note.txt", "old_string": "draft", "new_string": "final"},
                ),
            ),
        ),
        ("note updated", ()),
    )
    return "update the note", "note updated", scripted


SCENARIOS = {
    "l1-fix-fixture": _scenario_fix_fixture,
    "l1-add-note": _scenario_add_note,
}


class _InProcessExecutor:
    """Runs one L1 task through the real product loop; reads durable events."""

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root

    def provenance(self) -> Mapping[str, str]:
        return {"provider_kind": "deterministic", "provider_id": "deterministic"}

    def run_task(self, task: EvalTask) -> tuple[Sequence[Mapping[str, Any]], bool]:
        scenario = SCENARIOS.get(task.task_id)
        if scenario is None:
            raise KeyError(f"no L1 scenario for task {task.task_id}")
        root = self._root / task.task_id
        root.mkdir(parents=True, exist_ok=True)
        statement, expected_text, scripted = scenario(root)

        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        app.provider = DeterministicProvider(
            scripted=scripted,
            invocation_binding=app.provider.invocation_binding,
        )
        app.provider_configured = True
        session, loop = app.open_chat_session(statement, AutoApproveGateway())
        result = loop.run_turn(session, task.input)
        assert result.text == expected_text, f"{task.task_id}: {result.text!r}"
        events = self._read_events(app, session.task_id)
        return events, self._verify(task, root)

    @staticmethod
    def _read_events(app: AgentOSApplication, task_id: str) -> list[Mapping[str, Any]]:
        out: list[Mapping[str, Any]] = []
        for event in app.tasks._event_store.read(task_id):  # noqa: SLF001 - product store
            out.append(
                {
                    "event_type": str(getattr(event.event_type, "value", event.event_type)),
                    "sequence": event.sequence,
                    "occurred_at": str(event.occurred_at),
                    "payload": event.decoded_payload(),
                }
            )
        return out

    @staticmethod
    def _verify(task: EvalTask, root: Path) -> bool:
        completed = subprocess.run(
            list(task.verify_command), cwd=root, capture_output=True, check=False
        )
        return completed.returncode == 0


def _l1_manifest() -> EvalManifest:
    return freeze_manifest(
        EvalManifest(
            tasks=(
                EvalTask(
                    task_id="l1-fix-fixture",
                    input="fix the failing fixture",
                    verify_command=(
                        "python",
                        "-c",
                        "import pathlib,sys; sys.exit(0 if pathlib.Path('fixture.txt').read_text()=='fixed\\n' else 1)",
                    ),
                ),
                EvalTask(
                    task_id="l1-add-note",
                    input="update the note",
                    verify_command=(
                        "python",
                        "-c",
                        "import pathlib,sys; sys.exit(0 if pathlib.Path('note.txt').read_text()=='final\\n' else 1)",
                    ),
                ),
            )
        )
    )


def run_l1_eval(workspace_root: Path, report_json_path: Path | None = None) -> Any:
    executor = _InProcessExecutor(workspace_root)
    # AutoApproveGateway auto-approves tier<3 and denies tier>=3 -> the probe
    # (synthetic tier-3 action) must be refused, which it is (returns False).
    return run_eval(
        _l1_manifest(),
        executor,
        AutoApproveGateway(),
        SimpleNamespace(risk_tier=3),
        report_json_path=report_json_path,
    )
