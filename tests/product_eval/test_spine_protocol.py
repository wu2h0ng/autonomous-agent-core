"""Frozen behavioral specification for the SPINE-E2E-1 public harness.

This suite intentionally stays RED until Task 3 production modules exist.  It
contains no wall-clock wait and gives Product code no clock or persistence
injection seam.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "product_evals"
CASES = HARNESS / "spine_e2e_1" / "frozen_cases.json"
INPUTS = {"target_path": "subject.py", "test_command": "python -m pytest"}
PROVIDER_ENV = {
    "AGENT_OS_PROVIDER_MODEL": "spine-e2e-1-frozen",
    "AGENT_OS_PROVIDER_TEMPERATURE": "0",
    "AGENT_OS_PROVIDER_API_KEY_ENV": "SPINE_E2E_1_PROVIDER_KEY",
    "SPINE_E2E_1_PROVIDER_KEY": "spine-e2e-1-local-dummy",
}
FORBIDDEN_PROVIDER_ENV = {
    "AGENT_OS_PROVIDER_BASE_URL",
    "AGENT_OS_PROVIDER_MODEL",
    "AGENT_OS_PROVIDER_TEMPERATURE",
    "AGENT_OS_PROVIDER_API_KEY_ENV",
    "OPENAI_API_KEY",
    "AGENT_OS_RUNTIME_PROVIDER_KEY",
    "SPINE_E2E_1_PROVIDER_KEY",
}


def _module(name: str) -> ModuleType:
    return importlib.import_module(name)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _all_harness_python() -> list[Path]:
    expected = {
        HARNESS / "common" / "public_surface.py",
        HARNESS / "spine_e2e_1" / "protocol.py",
        HARNESS / "spine_e2e_1" / "coordinator.py",
    }
    assert expected <= set(HARNESS.rglob("*.py"))
    return sorted(HARNESS.rglob("*.py"))


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _attribute_chain(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_harness_rejects_private_product_organs_and_dynamic_reflection() -> None:
    banned_attributes = {
        "store",
        "tasks",
        "sandbox",
        "provider",
        "provider_configured",
        "correction",
        "policy",
        "grants",
        "compensation_grant",
        "_event_store",
        "__dict__",
    }
    banned_calls = {"getattr", "setattr", "vars", "eval", "exec"}
    for path in _all_harness_python():
        tree = _tree(path)
        bad_attrs = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in banned_attributes
        }
        bad_calls = {
            node.func.id
            for node in _calls(tree)
            if isinstance(node.func, ast.Name) and node.func.id in banned_calls
        }
        assert not bad_attrs, f"{path}: private Product organs: {sorted(bad_attrs)}"
        if path in expected_task3_paths():
            assert not bad_calls, f"{path}: dynamic reflection: {sorted(bad_calls)}"


def expected_task3_paths() -> set[Path]:
    return {
        HARNESS / "common" / "public_surface.py",
        HARNESS / "spine_e2e_1" / "protocol.py",
        HARNESS / "spine_e2e_1" / "coordinator.py",
    }


def test_harness_rejects_product_persistence_and_in_process_runner_imports() -> None:
    forbidden_fragments = (
        "agent_os_core.persistence",
        "agent_os_core.event_store",
        "agent_os_core.postgres",
        "sqlite3",
        "workflow_runner",
        "ai_agent_engineering_workflow",
    )
    for path in _all_harness_python():
        tree = _tree(path)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not any(
            fragment in imported
            for imported in imports
            for fragment in forbidden_fragments
        ), f"{path}: forbidden import {imports}"
        assert "SELECT " not in path.read_text(encoding="utf-8").upper()


def test_interrupt_seam_is_literal_apply_only_and_has_no_takeover_or_kill() -> None:
    allowed_locations = {
        (HARNESS / "spine_e2e_1" / "protocol.py").resolve(),
    }
    occurrences = 0
    for path in _all_harness_python():
        tree = _tree(path)
        source = path.read_text(encoding="utf-8")
        assert "recover_lease" not in source
        assert "os._exit" not in source
        for call in _calls(tree):
            if _attribute_chain(call.func).endswith("run_task"):
                keywords = {item.arg: item.value for item in call.keywords if item.arg}
                if "stop_after_node" in keywords:
                    occurrences += 1
                    assert path.resolve() in allowed_locations
                    value = keywords["stop_after_node"]
                    assert isinstance(value, ast.Constant) and value.value == "apply"
    assert occurrences == 1


def test_stop_after_node_is_not_routable_over_server_http_or_cli() -> None:
    for relative in (
        "apps/api_server/server.py",
        "apps/api_server/__main__.py",
        "apps/cli/__main__.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "stop_after_node" not in source


def test_frozen_contracts_are_exact() -> None:
    protocol = _module("product_evals.spine_e2e_1.protocol")
    case = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    contract_time = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)
    payload = protocol.build_case_contracts(case, contract_time)

    assert set(payload) == {
        "goal",
        "commitment",
        "workflow",
        "expected_outcome",
        "inputs",
    }
    goal = payload["goal"]
    assert set(goal) == {
        "goal_id",
        "tenant_id",
        "workspace_id",
        "created_by",
        "created_at",
        "statement",
    }
    assert goal["tenant_id"] == "tenant:local"
    assert goal["workspace_id"] == "workspace:local"
    assert goal["created_by"] == "user:local"
    assert goal["statement"] == case["goal"]
    assert "expires_at" not in goal

    commitment = payload["commitment"]
    assert commitment["deliverables"] == ["subject.py patch"]
    assert commitment["acceptance_criteria"] == ["python -m pytest exits 0"]
    assert commitment["authority_scopes"] == ["workspace:read", "workspace:write"]
    assert commitment["risk_tier"] == 1
    assert commitment["exit_conditions"] == ["verified"]
    assert commitment["budget"] == {
        "max_cost_usd": "10",
        "max_duration_seconds": 3600,
        "max_provider_tokens": 100000,
        "max_tool_calls": 100,
    }
    assert payload["inputs"] == INPUTS

    graph = payload["workflow"]
    assert graph["version"] == 1
    assert graph["policy_version"] == "policy-1"
    assert graph["evaluator_refs"] == ["evaluator:pytest:1"]
    assert graph["max_replans"] == 0
    assert [node["node_id"] for node in graph["nodes"]] == [
        "read",
        "provider",
        "approve",
        "apply",
        "tests",
        "evaluate",
        "done",
    ]
    assert [(edge["source"], edge["target"]) for edge in graph["edges"]] == [
        ("read", "provider"),
        ("provider", "approve"),
        ("approve", "apply"),
        ("apply", "tests"),
        ("tests", "evaluate"),
        ("evaluate", "done"),
    ]
    assert graph["nodes"][0]["capability"] == "workspace.read"
    assert graph["nodes"][1]["capability"] == "provider.chat"
    assert graph["nodes"][3]["capability"] == "workspace.apply_patch"
    assert graph["nodes"][3]["risk_tier"] == 1
    assert graph["nodes"][4]["capability"] == "workspace.run_tests"

    outcome = payload["expected_outcome"]
    assert outcome["evaluator_type"] == "pytest"
    assert outcome["evaluator_version"] == "1"
    assert outcome["threshold"] == 1.0
    assert outcome["observation_window_seconds"] == 3600
    assert outcome["evidence_requirements"] == [
        "pytest-report",
        "apply-receipt",
        "final-workspace-digest",
    ]
    assert outcome["failure_semantics"] == [
        "non-zero pytest exit",
        "missing evidence",
        "final digest mismatch",
    ]


def test_case_paths_and_database_are_explicit_and_isolated(tmp_path: Path) -> None:
    surface = _module("product_evals.common.public_surface")
    paths = surface.case_arm_paths(tmp_path, "st_reverse", "interrupted")
    assert paths.workspace == tmp_path / "cases/st_reverse/interrupted/workspace"
    assert (
        paths.database
        == tmp_path / "cases/st_reverse/interrupted/state/agent-os.sqlite3"
    )
    assert str(paths.database) != ":memory:"


def test_provider_environment_is_cleared_then_set_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _module("product_evals.common.public_surface")
    for name in FORBIDDEN_PROVIDER_ENV:
        monkeypatch.setenv(name, "ambient-drift")
    surface.configure_provider_environment("http://127.0.0.1:12345/v1")
    assert {
        name: __import__("os").environ.get(name) for name in PROVIDER_ENV
    } == PROVIDER_ENV
    assert (
        __import__("os").environ["AGENT_OS_PROVIDER_BASE_URL"]
        == "http://127.0.0.1:12345/v1"
    )
    assert "OPENAI_API_KEY" not in __import__("os").environ
    assert "AGENT_OS_RUNTIME_PROVIDER_KEY" not in __import__("os").environ


def test_public_application_construction_verifies_provider_status(
    tmp_path: Path,
) -> None:
    surface = _module("product_evals.common.public_surface")
    signature = inspect.signature(surface.open_application)
    assert tuple(signature.parameters) == ("database", "workspace")
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
    source = inspect.getsource(surface.open_application)
    assert "provider_status" in source
    assert "DeterministicProvider" not in source


def test_normalized_projection_excludes_nondeterministic_fields() -> None:
    surface = _module("product_evals.common.public_surface")
    projection = surface.normalize_projection(
        {
            "task_id": "task:random",
            "run_id": "run:random",
            "event_id": "event:random",
            "created_at": "2026-07-13T00:00:00Z",
            "duration_seconds": 0.123,
            "artifact_id": "artifact:pytest-duration-dependent",
            "status": "VERIFIED",
            "sequence": 17,
            "lease_fence": 2,
        }
    )
    encoded = json.dumps(projection, sort_keys=True)
    for forbidden in (
        "task:random",
        "run:random",
        "event:random",
        "2026-07-13",
        "0.123",
        "pytest-duration-dependent",
    ):
        assert forbidden not in encoded
    assert projection["status"] == "VERIFIED"
    assert projection["sequence"] == 17
    assert projection["lease_fence"] == 2


def test_public_evidence_binds_workspace_and_provider_ledger(tmp_path: Path) -> None:
    surface = _module("product_evals.common.public_surface")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "subject.py").write_text("before\n")
    ledger = tmp_path / "provider.jsonl"
    ledger.write_text('{"accepted":true}\n')
    application = _ScriptedPublicApp("task:i", [])
    evidence = surface.public_evidence(application, "task:i", workspace, ledger)
    assert evidence["status"] == "VERIFIED"
    assert evidence["lease_fence"] == 1
    assert evidence["action_receipt_count"] == 0
    assert len(evidence["workspace_tree_sha256"]) == 64
    assert len(evidence["provider_ledger_sha256"]) == 64


def test_fixture_setup_writes_exact_case_files_and_rejects_unsafe_paths(
    tmp_path: Path,
) -> None:
    surface = _module("product_evals.common.public_surface")
    case = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    surface.write_case_fixture(tmp_path, case)
    assert (tmp_path / case["target_path"]).read_text() == case["initial_content"]
    assert (tmp_path / case["test_path"]).read_text() == case["pytest_source"]
    for key in ("target_path", "test_path"):
        unsafe = {**case, key: "../escape.py"}
        with pytest.raises(ValueError, match="safe relative"):
            surface.write_case_fixture(tmp_path, unsafe)


class _ScriptedPublicApp:
    def __init__(self, task_id: str, run_script: list[object]) -> None:
        self.task_id = task_id
        self.run_script = list(run_script)
        self.calls: list[tuple[object, ...]] = []
        self.projection_version = 0

    def provider_status(self) -> dict[str, object]:
        self.calls.append(("provider_status",))
        return {"configured": True}

    def create_task(self, payload: dict[str, object]) -> SimpleNamespace:
        self.calls.append(("create_task", payload))
        return SimpleNamespace(task_id=self.task_id)

    def commit_task(self, task_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("commit_task", task_id, payload))

    def run_task(
        self, task_id: str, inputs: dict[str, str], **kwargs: object
    ) -> object:
        self.calls.append(("run_task", task_id, inputs, kwargs))
        result = self.run_script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def record_approval(self, task_id: str, payload: dict[str, str]) -> None:
        self.calls.append(("record_approval", task_id, payload))

    def task_json(self, task_id: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "status": "VERIFIED",
            "sequence": self.projection_version,
        }

    def evidence_json(self, task_id: str) -> list[dict[str, object]]:
        return [
            {
                "task_id": task_id,
                "event_id": "random",
                "sequence": self.projection_version,
            }
        ]

    def recovery_json(self, task_id: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "lease_fence": 1,
            "sequence": self.projection_version,
        }


def _status(value: str) -> SimpleNamespace:
    return SimpleNamespace(
        status=SimpleNamespace(value="COMPLETED" if value == "VERIFIED" else "ACTIVE"),
        run=SimpleNamespace(status=SimpleNamespace(value=value)),
        observed_outcome=(
            SimpleNamespace(status=SimpleNamespace(value="VERIFIED"))
            if value == "VERIFIED"
            else None
        ),
    )


def test_prepare_executes_both_arms_with_one_contract_time_and_exact_inputs() -> None:
    from agent_os_contracts import Commitment, ExpectedOutcome, Goal, WorkflowGraph

    protocol = _module("product_evals.spine_e2e_1.protocol")
    case = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    when = datetime(2026, 7, 13, tzinfo=timezone.utc)
    uninterrupted = _ScriptedPublicApp(
        "task:u", [_status("WAITING_APPROVAL"), _status("VERIFIED")]
    )
    interrupted = _ScriptedPublicApp("task:i", [_status("WAITING_APPROVAL")])

    result = protocol.prepare(uninterrupted, interrupted, case, when)

    assert result["task_ids"] == {"uninterrupted": "task:u", "interrupted": "task:i"}
    for application, expected_runs in ((uninterrupted, 2), (interrupted, 1)):
        create = next(call for call in application.calls if call[0] == "create_task")
        commit = next(call for call in application.calls if call[0] == "commit_task")
        Goal.model_validate(create[1])
        Commitment.model_validate(commit[2]["commitment"])
        WorkflowGraph.model_validate(commit[2]["workflow"])
        ExpectedOutcome.model_validate(commit[2]["expected_outcome"])
        assert create[1]["created_at"] == when
        assert commit[2]["commitment"]["accepted_at"] == when
        runs = [call for call in application.calls if call[0] == "run_task"]
        assert len(runs) == expected_runs
        assert all(call[2] == INPUTS and call[3] == {} for call in runs)
        assert (
            len([call for call in application.calls if call[0] == "record_approval"])
            == 1
        )


def test_prepare_case_opens_independent_file_backed_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    surface = _module("product_evals.common.public_surface")
    case = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    opened: list[tuple[Path, Path]] = []

    def fake_open(database: Path, workspace: Path) -> _ScriptedPublicApp:
        opened.append((database, workspace))
        script = (
            [_status("WAITING_APPROVAL"), _status("VERIFIED")]
            if len(opened) == 1
            else [_status("WAITING_APPROVAL")]
        )
        return _ScriptedPublicApp(f"task:{len(opened)}", script)

    monkeypatch.setattr(surface, "open_application", fake_open)
    result = surface.prepare_case(
        tmp_path, case, "http://127.0.0.1:12345/v1", tmp_path / "provider.jsonl"
    )
    assert len(opened) == 2 and opened[0] != opened[1]
    assert all(database.name == "agent-os.sqlite3" for database, _ in opened)
    assert result["task_ids"] == {
        "uninterrupted": "task:1",
        "interrupted": "task:2",
    }
    for _, workspace in opened:
        assert (workspace / case["target_path"]).read_text() == case["initial_content"]


def test_real_single_case_prepare_interrupt_and_immediate_probe(tmp_path: Path) -> None:
    surface = _module("product_evals.common.public_surface")
    protocol = _module("product_evals.spine_e2e_1.protocol")
    from product_evals.common.provider_bank import FrozenProviderServer

    case = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    ledger = tmp_path / "provider-calls.jsonl"
    server = FrozenProviderServer(
        HARNESS / "spine_e2e_1" / "provider_responses.json",
        ledger_path=ledger,
        context_sha256="a" * 64,
    )
    server.start()
    try:
        prepared = surface.prepare_case(tmp_path, case, server.base_url, ledger)
        paths = surface.case_arm_paths(tmp_path, case["case_id"], "interrupted")
        surface.configure_provider_environment(server.base_url)
        interrupted = surface.open_application(paths.database, paths.workspace)

        def evidence(application: object, task_id: str) -> dict[str, object]:
            return surface.public_evidence(
                application, task_id, paths.workspace, ledger
            )

        protocol.interrupt_batch(
            interrupted, (prepared["task_ids"]["interrupted"],), evidence
        )
        surface.configure_provider_environment(server.base_url)
        probe = surface.open_application(paths.database, paths.workspace)
        protocol.probe_active_lease(
            probe, (prepared["task_ids"]["interrupted"],), evidence
        )
    finally:
        server.close(validate_counts=False)
    records = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert sum(record["accepted"] is True for record in records) == 2


def test_interrupt_probe_and_resume_enforce_typed_public_behavior() -> None:
    from agent_os_core import ConcurrentWriteError, WorkerInterrupted

    protocol = _module("product_evals.spine_e2e_1.protocol")
    interrupted = _ScriptedPublicApp("task:i", [WorkerInterrupted("apply")])
    interrupt_evidence = iter(
        (
            {
                "status": "ACTIVE",
                "lease_fence": 1,
                "action_receipt_count": 1,
                "workspace_tree_sha256": "before",
                "provider_ledger_sha256": "provider",
            },
            {
                "status": "ACTIVE",
                "lease_fence": 1,
                "action_receipt_count": 2,
                "workspace_tree_sha256": "after",
                "provider_ledger_sha256": "provider",
            },
        )
    )
    protocol.interrupt_batch(
        interrupted,
        ("task:i",),
        lambda _application, _task_id: next(interrupt_evidence),
    )
    assert interrupted.calls[0] == (
        "run_task",
        "task:i",
        INPUTS,
        {"stop_after_node": "apply"},
    )

    probe = _ScriptedPublicApp("task:i", [ConcurrentWriteError("active")])
    frozen = {
        "status": "ACTIVE",
        "lease_fence": 1,
        "action_receipt_count": 2,
        "workspace_tree_sha256": "after",
        "provider_ledger_sha256": "provider",
    }
    protocol.probe_active_lease(
        probe, ("task:i",), lambda _application, _task_id: dict(frozen)
    )
    run = next(call for call in probe.calls if call[0] == "run_task")
    assert run == ("run_task", "task:i", INPUTS, {"recover_stale_lease": False})

    resume = _ScriptedPublicApp("task:i", [_status("VERIFIED"), _status("VERIFIED")])
    resume_evidence = iter(
        (
            {**frozen},
            {
                **frozen,
                "status": "COMPLETED",
                "lease_fence": 2,
            },
            {
                **frozen,
                "status": "COMPLETED",
                "lease_fence": 2,
            },
        )
    )
    protocol.resume_spine(
        resume, ("task:i",), lambda _application, _task_id: next(resume_evidence)
    )
    runs = [call for call in resume.calls if call[0] == "run_task"]
    assert runs == [
        ("run_task", "task:i", INPUTS, {"recover_stale_lease": False}),
        ("run_task", "task:i", INPUTS, {"recover_stale_lease": False}),
    ]


def test_protocol_exports_exact_public_phase_seams() -> None:
    protocol = _module("product_evals.spine_e2e_1.protocol")
    for name in ("prepare", "interrupt_batch", "probe_active_lease", "resume_spine"):
        function = getattr(protocol, name)
        assert callable(function)
    source = inspect.getsource(protocol)
    assert "DeterministicProvider" not in source
    assert "recover_stale_lease=True" not in source.replace(" ", "")
    assert "time.sleep" not in source


def test_prepare_interrupt_probe_resume_public_behavior_seams() -> None:
    protocol = _module("product_evals.spine_e2e_1.protocol")
    source = inspect.getsource(protocol)
    for call in (
        "create_task",
        "commit_task",
        "run_task",
        "record_approval",
        "task_json",
        "evidence_json",
        "recovery_json",
        "provider_status",
    ):
        assert call in source
    assert source.count('stop_after_node="apply"') == 1
    assert source.count("recover_stale_lease=False") >= 2
    assert "WorkerInterrupted" in source
    assert "ConcurrentWriteError" in source


def test_coordinator_commands_and_immediate_order_are_frozen() -> None:
    coordinator = _module("product_evals.spine_e2e_1.coordinator")
    expected_interrupt = (
        sys.executable,
        "-m",
        "product_evals.spine_e2e_1.cli",
        "interrupt-batch",
    )
    expected_probe = (
        sys.executable,
        "-m",
        "product_evals.spine_e2e_1.cli",
        "probe-active-lease",
    )
    expected_anchor = (
        sys.executable,
        "-m",
        "product_evals.spine_e2e_1.cli",
        "record-runner-anchor",
    )
    assert coordinator.INTERRUPT_COMMAND == expected_interrupt
    assert coordinator.RUNNER_ANCHOR_COMMAND == expected_anchor
    assert coordinator.PROBE_COMMAND == expected_probe
    source = inspect.getsource(coordinator.run_interrupt_and_probe)
    interrupt_at = source.index("INTERRUPT_COMMAND")
    anchor_at = source.index("RUNNER_ANCHOR_COMMAND")
    probe_at = source.index("PROBE_COMMAND")
    assert interrupt_at < anchor_at < probe_at
    assert "sleep" not in source
    assert "shell=True" not in source


def test_coordinator_runs_three_exact_checked_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _module("product_evals.spine_e2e_1.coordinator")
    calls: list[tuple[tuple[str, ...], bool]] = []

    def capture(command: tuple[str, ...], *, check: bool) -> None:
        calls.append((command, check))

    monkeypatch.setattr(coordinator.subprocess, "run", capture)
    coordinator.run_interrupt_and_probe()
    assert calls == [
        (coordinator.INTERRUPT_COMMAND, True),
        (coordinator.RUNNER_ANCHOR_COMMAND, True),
        (coordinator.PROBE_COMMAND, True),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"python_executable": "/tmp/python"},
        {"interrupt_args": ("--node", "read")},
        {"probe_args": ("--recover",)},
    ],
)
def test_coordinator_refuses_alternate_executables_or_arguments(
    kwargs: dict[str, object],
) -> None:
    coordinator = _module("product_evals.spine_e2e_1.coordinator")
    with pytest.raises((TypeError, ValueError)):
        coordinator.run_interrupt_and_probe(**kwargs)


def test_task3_protocol_has_no_cli_or_phase_authority() -> None:
    protocol = _module("product_evals.spine_e2e_1.protocol")
    assert not hasattr(protocol, "PHASE_COMMANDS")
    assert not hasattr(protocol, "main")
