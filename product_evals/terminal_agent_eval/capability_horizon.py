"""Capability-horizon measurement for the MCP precondition (measurement only).

The question this module answers: **is the chat tool surface a measurable
bottleneck for the frozen terminal coding corpus?** The MCP gating card makes
that a precondition for any MCP work, and asks for a number, not an opinion.

What is measured, on the real product path and with no model involved:

1. *closure* — for every frozen task, which capability ids the corpus's own
   reference solution demands, and whether that demand is a subset of the
   surface the chat loop exposes (``agent_os_core.agent_loop.CHAT_CAPABILITY_IDS``).
   A demand outside the surface would be a task no chat-configured agent can
   complete, whatever model drives it.
2. *the gate* — what the loop does to a proposal that reaches outside the
   surface, and what the eval's own projection records for it. Two probe ids
   are used against one frozen task: a capability that exists and is
   dispatchable but is not on the chat surface, and an id in the shape an
   MCP-derived capability would take (registered nowhere in this repository —
   no server is contacted, no transport is opened, no SDK is imported).

The probes are **instruments, not findings**: they show that a surface gap
would be attributable if the corpus contained one. The closure pass is the
finding. Nothing here changes product behaviour, adds a capability, or
authorises MCP work.

Every task runs in its own throwaway directory under ``workspace_root``, and
the persisted-provider lookup is redirected inside it
(``isolated_provider_config``) before any application object exists, so no run
can reach the operator's own provider configuration.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_os_core import AutoApproveGateway
from agent_os_core.agent_loop import CHAT_CAPABILITY_IDS

from apps.api_server.app import AgentOSApplication

# The frozen harness owns the operator-policy -> gateway mapping and the tier-3
# probe action; the probes must use the same ones or they are not comparable.
from .coding_harness import (
    SUITE_NAME,
    VERIFY_TIMEOUT_SECONDS,
    _PROBE_ACTION,
    _gateway_for,
    expectations,
    qualify,
)
from .coding_solver import CodingPlanProvider, OfflineArm, PlanStep, plan_for, step
from .coding_tasks import MANIFEST_PATH, verify_fixture_digests
from .manifest import freeze_manifest, load_manifest
from .models import EvalManifest, EvalReport, EvalTask, TaskResult
from .provider_isolation import assert_env_provider_absent, isolated_provider_config
from .runner import run_eval

# The surface the chat loop enforces (agent_loop.py:941): a proposal whose
# capability id is not in this tuple is denied before any Action is built.
SURFACE = tuple(CHAT_CAPABILITY_IDS)
DENY_BASIS_OUT_OF_ALLOWLIST = "out_of_allowlist"
ACTION_PROPOSED = "ACTION_PROPOSED"
POLICY_VERDICT_RECORDED = "POLICY_VERDICT_RECORDED"
REFERENCE_PROBE = "reference"

# Registered and dispatchable, but deliberately not exposed to chat turns: the
# developer pack's `specs()` carries it, while CHAT_CAPABILITY_IDS does not.
OFF_SURFACE_REGISTERED_PROBE = "artifact.write"
# The id shape an MCP-derived capability would take. No MCP code exists in this
# repository, so this id is registered nowhere; it is a name, not a connection.
OFF_SURFACE_UNREGISTERED_PROBE = "mcp.filesystem.read_file"

# The frozen task the probes run against: its acceptance command is a
# deterministic file-content check, so "the effect happened" is unambiguous.
PROBE_TASK_ID = "code-read-and-derive"

# The same directories the corpus graders ignore when they snapshot a workspace.
_SKIP_NAMES = frozenset(
    {"__pycache__", ".pytest_cache", ".agent-os-artifacts", ".agent_os", ".git"}
)
_SKIP_PREFIXES = ("agent-os.sqlite3",)


class HorizonError(Exception):
    """Raised when the measurement cannot be taken as specified."""


class TaskObservation(BaseModel):
    """One task driven through the real loop under an explicit plan."""

    model_config = ConfigDict(frozen=True)

    probe: str
    task_id: str
    proposed_capability_ids: tuple[str, ...] = ()
    off_surface_proposals: tuple[str, ...] = ()
    policy_denials: tuple[tuple[str, str], ...] = ()
    stop_reason: str
    # These four are the frozen projection's own numbers (metrics.py), not a
    # local re-count, so a claim about what the instrument records is about the
    # instrument rather than about this module's arithmetic.
    completed: bool
    tool_calls: int
    denials: int
    provider_steps: int
    workspace_paths_changed: tuple[str, ...] = ()


class HorizonMeasurement(BaseModel):
    model_config = ConfigDict(frozen=True)

    suite: str
    manifest_sha256: str
    surface: tuple[str, ...]
    dispatchable: tuple[str, ...]
    registered_but_not_exposed: tuple[str, ...]
    corpus_task_count: int
    corpus_tasks_demanding_off_surface: int
    reference_matches_frozen_expectation: bool
    reference_calibration_violations: tuple[str, ...] = ()
    observations: tuple[TaskObservation, ...] = ()


@dataclass
class _Run:
    """What one task run left behind, before projection."""

    events: Sequence[Mapping[str, Any]]
    verify_ok: bool
    stop_reason: str
    root: Path
    workspace_paths_changed: tuple[str, ...] = ()


@dataclass
class PlannedExecutor:
    """``TurnExecutor`` that replays one explicit plan per task.

    The plan is the only thing that differs between the closure pass and the
    probes; everything downstream (loop, policy, broker, projection) is the
    product's own path, reached through ``run_eval`` exactly as the frozen
    harness reaches it.
    """

    plans: Mapping[str, Sequence[PlanStep]]
    workspace_root: Path
    label: str
    runs: dict[str, _Run] = field(default_factory=dict)

    def run_task(self, task: EvalTask) -> tuple[Sequence[Mapping[str, Any]], bool]:
        try:
            plan = self.plans[task.task_id]
        except KeyError as exc:
            raise HorizonError(f"no plan for task {task.task_id}") from exc

        root = self.workspace_root / task.task_id
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        for relative, content in task.fixture:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
        assert_env_provider_absent(app, arm=self.label)
        app.provider = CodingPlanProvider(
            plan, invocation_binding=app.provider.invocation_binding
        )
        app.provider_configured = True
        session, loop = app.open_chat_session(
            f"{SUITE_NAME} {self.label} {task.task_id}", _gateway_for(task)
        )
        turn = loop.run_turn(session, task.input)
        events = _read_events(app, session.task_id)
        self.runs[task.task_id] = _Run(
            events=events,
            verify_ok=_verify(task, root),
            stop_reason=turn.stop_reason,
            root=root,
            workspace_paths_changed=_changed_paths(task, root),
        )
        return events, self.runs[task.task_id].verify_ok


def _read_events(app: AgentOSApplication, task_id: str) -> list[Mapping[str, Any]]:
    return [
        {
            "event_type": str(getattr(event.event_type, "value", event.event_type)),
            "sequence": event.sequence,
            "occurred_at": str(event.occurred_at),
            "payload": event.decoded_payload(),
        }
        for event in app.tasks._event_store.read(task_id)  # noqa: SLF001 - product store
    ]


def _verify(task: EvalTask, root: Path) -> bool:
    try:
        completed = subprocess.run(
            list(task.verify_command),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=VERIFY_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HorizonError(f"{task.task_id}: acceptance command failed to run: {exc}") from exc
    return completed.returncode == 0


def _changed_paths(task: EvalTask, root: Path) -> tuple[str, ...]:
    """Paths the turn created or modified relative to the frozen fixture."""
    fixture = dict(task.fixture)
    changed = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        head = relative.split("/", 1)[0]
        if head in _SKIP_NAMES or head.startswith(_SKIP_PREFIXES):
            continue
        if fixture.get(relative) != path.read_text("utf-8", errors="replace"):
            changed.append(relative)
    return tuple(changed)


def _capability_ids(events: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    ids = []
    for event in events:
        if event.get("event_type") != ACTION_PROPOSED:
            continue
        payload = event.get("payload")
        action = payload.get("action") if isinstance(payload, Mapping) else None
        capability_id = action.get("capability_id") if isinstance(action, Mapping) else None
        if isinstance(capability_id, str):
            ids.append(capability_id)
    return tuple(ids)


def _policy_denials(events: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, str], ...]:
    denials = []
    for event in events:
        if event.get("event_type") != POLICY_VERDICT_RECORDED:
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping) or str(payload.get("verdict")) != "DENY":
            continue
        denials.append((str(payload.get("capability_id")), str(payload.get("basis"))))
    return tuple(denials)


def _observe(probe: str, task_id: str, run: _Run, result: TaskResult) -> TaskObservation:
    proposed = _capability_ids(run.events)
    return TaskObservation(
        probe=probe,
        task_id=task_id,
        proposed_capability_ids=proposed,
        off_surface_proposals=tuple(
            capability_id for capability_id in proposed if capability_id not in SURFACE
        ),
        policy_denials=_policy_denials(run.events),
        stop_reason=run.stop_reason,
        completed=result.completed,
        tool_calls=result.tool_calls,
        denials=result.denials,
        provider_steps=result.provider_steps,
        workspace_paths_changed=run.workspace_paths_changed,
    )


def _run_plans(
    plans: Mapping[str, Sequence[PlanStep]],
    manifest: EvalManifest,
    workspace_root: Path,
    *,
    label: str,
) -> tuple[list[TaskObservation], EvalReport]:
    executor = PlannedExecutor(plans=plans, workspace_root=workspace_root, label=label)
    with isolated_provider_config(workspace_root):
        report = run_eval(manifest, executor, AutoApproveGateway(), _PROBE_ACTION, arm=label)
    results = {task.task_id: task for task in report.tasks}
    observations = [
        _observe(label, task.task_id, executor.runs[task.task_id], results[task.task_id])
        for task in manifest.tasks
    ]
    return observations, report


def _open_quantity(task: EvalTask) -> str:
    """The answer the frozen fixture implies, derived here rather than copied.

    The probe's on-surface control writes this value, so the probe needs no
    expected literal and the acceptance grader stays the only discriminator.
    """
    csv_text = dict(task.fixture)["inventory.csv"]
    total = 0
    for line in csv_text.strip().splitlines()[1:]:
        _item, quantity, status = line.split(",")
        if status == "open":
            total += int(quantity)
    return f"{total}\n"


def _probe_plans(task: EvalTask) -> dict[str, Sequence[PlanStep]]:
    answer = _open_quantity(task)
    write_args: dict[str, object] = {"path": "answer.txt", "content": answer}
    return {
        "surface-control": (
            step("", ("workspace.apply_patch", write_args)),
            step("wrote the answer through an on-surface capability"),
        ),
        f"off-surface-registered:{OFF_SURFACE_REGISTERED_PROBE}": (
            step("", (OFF_SURFACE_REGISTERED_PROBE, write_args)),
            step("wrote the answer through an off-surface capability"),
        ),
        f"off-surface-unregistered:{OFF_SURFACE_UNREGISTERED_PROBE}": (
            step("", (OFF_SURFACE_UNREGISTERED_PROBE, write_args)),
            step("wrote the answer through an unregistered capability"),
        ),
    }


def _dispatchable_capability_ids(workspace_root: Path) -> tuple[str, ...]:
    """The registered capability ids of the connector the loop actually uses.

    The application object is built inside the isolated provider lookup for the
    same reason every other run is: its constructor re-installs a persisted
    provider (and tests it) when it finds one, which must never happen here.
    """
    probe_root = workspace_root / "_registry-probe"
    probe_root.mkdir(parents=True, exist_ok=True)
    with isolated_provider_config(probe_root):
        app = AgentOSApplication(
            database=probe_root / "agent-os.sqlite3", workspace=probe_root
        )
    return tuple(sorted(app.sandbox.specs()))


def measure_capability_horizon(
    workspace_root: str | Path,
    *,
    manifest_path: str | Path = MANIFEST_PATH,
    out_dir: str | Path | None = None,
) -> HorizonMeasurement:
    """Run the closure pass and the probes; write artifacts when asked."""
    root = Path(workspace_root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    verify_fixture_digests(manifest)

    reference_plans = {
        task.task_id: plan_for(OfflineArm.REFERENCE, task) for task in manifest.tasks
    }
    observations, report = _run_plans(
        reference_plans, manifest, root / REFERENCE_PROBE, label=REFERENCE_PROBE
    )

    # Self-calibration: this module's bootstrap must reproduce the frozen
    # harness's own expectations, or its probe results mean nothing.
    violations = qualify(report, expectations(manifest)[OfflineArm.REFERENCE])

    probe_task = next((task for task in manifest.tasks if task.task_id == PROBE_TASK_ID), None)
    if probe_task is None:
        raise HorizonError(f"probe task {PROBE_TASK_ID} is not in the frozen manifest")
    # A probe run drives exactly one task; freezing a one-task manifest keeps the
    # runner's freeze boundary intact instead of bypassing it for a subset.
    probe_manifest = freeze_manifest(
        EvalManifest(schema_version=manifest.schema_version, tasks=(probe_task,))
    )
    for probe, plans in _probe_plans(probe_task).items():
        probe_observations, _ = _run_plans(
            {probe_task.task_id: plans},
            probe_manifest,
            root / probe.replace(":", "-"),
            label=probe,
        )
        observations.extend(probe_observations)

    surface = tuple(SURFACE)
    dispatchable = _dispatchable_capability_ids(root)
    demanding = sum(
        1
        for observation in observations
        if observation.probe == REFERENCE_PROBE
        and any(capability_id not in surface for capability_id in observation.proposed_capability_ids)
    )
    measurement = HorizonMeasurement(
        suite=f"{SUITE_NAME}-CAPABILITY-HORIZON",
        manifest_sha256=manifest.manifest_sha256 or "",
        surface=surface,
        dispatchable=dispatchable,
        registered_but_not_exposed=tuple(
            capability_id for capability_id in dispatchable if capability_id not in surface
        ),
        corpus_task_count=len(manifest.tasks),
        corpus_tasks_demanding_off_surface=demanding,
        reference_matches_frozen_expectation=not violations,
        reference_calibration_violations=tuple(violations),
        observations=tuple(observations),
    )
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "capability-horizon.json").write_text(
            measurement.model_dump_json(indent=2) + "\n", "utf-8"
        )
        (out / "capability-horizon.md").write_text(render_measurement(measurement), "utf-8")
    return measurement


def render_measurement(measurement: HorizonMeasurement) -> str:
    lines = [
        measurement.suite,
        f"manifest: {measurement.manifest_sha256[:16]}…",
        f"surface ({len(measurement.surface)}): {', '.join(measurement.surface)}",
        f"dispatchable ({len(measurement.dispatchable)}): " + ", ".join(measurement.dispatchable),
        "registered but not exposed: "
        + (", ".join(measurement.registered_but_not_exposed) or "none"),
        f"corpus: {measurement.corpus_task_count} tasks, "
        f"{measurement.corpus_tasks_demanding_off_surface} demanding a capability "
        "outside the surface",
        "reference pass reproduces the frozen expectations: "
        + ("YES" if measurement.reference_matches_frozen_expectation else "NO"),
    ]
    for violation in measurement.reference_calibration_violations:
        lines.append(f"  calibration violation: {violation}")
    lines.append("")
    for observation in measurement.observations:
        lines.append(
            f"  [{observation.probe}] {observation.task_id}: "
            f"proposed={list(observation.proposed_capability_ids)} "
            f"off_surface={list(observation.off_surface_proposals)} "
            f"policy_denials={list(observation.policy_denials)} "
            f"stop={observation.stop_reason} completed={observation.completed} "
            f"tool_calls={observation.tool_calls} "
            f"operator_denials={observation.denials} "
            f"steps={observation.provider_steps} "
            f"changed={list(observation.workspace_paths_changed)}"
        )
    lines.extend(
        [
            "",
            "boundary: this is a measurement instrument, not a capability result. "
            "The probes are engineered gaps; the closure pass is the finding. "
            "It says nothing about what a model would do, and it authorises no "
            "MCP work.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{SUITE_NAME} capability horizon")
    parser.add_argument("--workspace", required=True, help="parent dir for probe workspaces")
    parser.add_argument("--out-dir", default=None, help="write the measurement here")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    args = parser.parse_args(argv)

    measurement = measure_capability_horizon(
        args.workspace, manifest_path=args.manifest, out_dir=args.out_dir
    )
    print(render_measurement(measurement))
    if args.out_dir:
        print(f"[capability-horizon] wrote {args.out_dir}/capability-horizon.json and .md")
    return 0 if measurement.reference_matches_frozen_expectation else 1


if __name__ == "__main__":
    raise SystemExit(main())
