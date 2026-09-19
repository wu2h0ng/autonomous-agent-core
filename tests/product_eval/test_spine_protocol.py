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


def test_workflow_binding_is_frozen_per_case_not_last_observation() -> None:
    protocol = _module("product_evals.spine_e2e_1.protocol")
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"][:2]
    contract_time = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)
    digests = [
        protocol.expected_workflow_sha256(case, contract_time) for case in cases
    ]
    assert len(set(digests)) == 2
    assert all(len(digest) == 64 for digest in digests)


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
    with surface.provider_environment("http://127.0.0.1:12345/v1"):
        assert {
            name: __import__("os").environ.get(name) for name in PROVIDER_ENV
        } == PROVIDER_ENV
        assert (
            __import__("os").environ["AGENT_OS_PROVIDER_BASE_URL"]
            == "http://127.0.0.1:12345/v1"
        )
        assert "OPENAI_API_KEY" not in __import__("os").environ
        assert "AGENT_OS_RUNTIME_PROVIDER_KEY" not in __import__("os").environ
    assert {
        name: __import__("os").environ.get(name) for name in FORBIDDEN_PROVIDER_ENV
    } == {name: "ambient-drift" for name in FORBIDDEN_PROVIDER_ENV}


def test_provider_environment_leaves_no_configuration_behind_for_the_next_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two arms in one process: the second one must start from a clean environment.

    ``configure_provider_environment`` writes the frozen configuration into the
    process environment because that is where the application reads it. When the
    write outlives the arm that needed it, every later arm in the same pytest
    process is silently pointed at a loopback endpoint the earlier arm has
    already closed -- which is why the suite's result used to depend on the order
    the files happened to be collected in.
    """
    surface = _module("product_evals.common.public_surface")
    for name in FORBIDDEN_PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    baseline = {
        name: __import__("os").environ.get(name) for name in FORBIDDEN_PROVIDER_ENV
    }

    with surface.provider_environment("http://127.0.0.1:12345/v1"):
        first_arm = {
            name: __import__("os").environ.get(name) for name in FORBIDDEN_PROVIDER_ENV
        }
    second_arm_entry = {
        name: __import__("os").environ.get(name) for name in FORBIDDEN_PROVIDER_ENV
    }

    assert first_arm["AGENT_OS_PROVIDER_BASE_URL"] == "http://127.0.0.1:12345/v1"
    assert second_arm_entry == baseline


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


def test_prepare_case_scopes_the_provider_environment_to_its_own_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both arms of one ``prepare_case`` run, and neither leaves configuration behind.

    The frozen arms are configured through the process environment, so
    ``prepare_case`` has to restore it on the way out; otherwise the arms of the
    *next* case -- and every unrelated test collected after this module -- start
    from this case's dead loopback endpoint.
    """
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
    for name in FORBIDDEN_PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    baseline = {
        name: __import__("os").environ.get(name) for name in FORBIDDEN_PROVIDER_ENV
    }
    arm_entry_states: list[dict[str, str | None]] = []
    configure = surface.configure_provider_environment

    def observing_configure(base_url: str) -> None:
        arm_entry_states.append(
            {name: __import__("os").environ.get(name) for name in FORBIDDEN_PROVIDER_ENV}
        )
        configure(base_url)

    monkeypatch.setattr(surface, "configure_provider_environment", observing_configure)
    surface.prepare_case(
        tmp_path, case, "http://127.0.0.1:12345/v1", tmp_path / "provider.jsonl"
    )

    # Two arms in one process, then the flow's own re-apply: every one of them
    # starts from the environment its caller had, never from the previous arm's
    # leftovers.
    assert len(arm_entry_states) == 3
    assert arm_entry_states == [baseline, baseline, baseline]
    assert {
        name: __import__("os").environ.get(name) for name in FORBIDDEN_PROVIDER_ENV
    } == baseline


def test_open_application_accepts_the_frozen_provider_status(tmp_path: Path) -> None:
    """The frozen status check must describe every field the product reports.

    ``AgentOSApplication.provider_status`` gained ``model_revision_digest`` after
    this instrument was frozen; a status comparison that names only the five
    older fields never matches, so ``open_application`` refused every correctly
    configured application.
    """
    surface = _module("product_evals.common.public_surface")
    with surface.provider_environment("http://127.0.0.1:12345/v1"):
        application = surface.open_application(
            tmp_path / "state" / "agent-os.sqlite3", tmp_path / "workspace"
        )
    assert application.provider_status() == {
        "configured": True,
        "provider_id": "openai-compatible",
        "model_id": "spine-e2e-1-frozen",
        "model_revision_digest": None,
        "endpoint_class": "openai-compatible",
        "credential_ref_id": "credential:default",
    }


def test_open_application_still_fails_closed_on_a_revision_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    surface = _module("product_evals.common.public_surface")
    monkeypatch.setenv("AGENT_OS_PROVIDER_MODEL_REVISION_DIGEST", "b" * 64)
    with surface.provider_environment("http://127.0.0.1:12345/v1"):
        with pytest.raises(RuntimeError, match="frozen provider status mismatch"):
            surface.open_application(
                tmp_path / "state" / "agent-os.sqlite3", tmp_path / "workspace"
            )


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
        observed_workflow = prepared["public_evidence"]["uninterrupted"][
            "projection"
        ]["task"]["run"]["workflow_digest"]
        contract_time = datetime.fromisoformat(prepared["contract_time"])
        assert observed_workflow == protocol.expected_workflow_sha256(
            case, contract_time
        )
        paths = surface.case_arm_paths(tmp_path, case["case_id"], "interrupted")

        def evidence(application: object, task_id: str) -> dict[str, object]:
            return surface.public_evidence(application, task_id, paths.workspace, ledger)

        with surface.provider_environment(server.base_url):
            interrupted = surface.open_application(paths.database, paths.workspace)
            protocol.interrupt_batch(
                interrupted, (prepared["task_ids"]["interrupted"],), evidence
            )
        with surface.provider_environment(server.base_url):
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


def test_resume_preserves_ordinary_not_met_for_later_adjudication() -> None:
    protocol = _module("product_evals.spine_e2e_1.protocol")
    not_met = SimpleNamespace(
        status=SimpleNamespace(value="COMPLETED"),
        run=SimpleNamespace(status=SimpleNamespace(value="SUCCEEDED")),
        observed_outcome=SimpleNamespace(status=SimpleNamespace(value="NOT_MET")),
    )
    resume = _ScriptedPublicApp("task:i", [not_met, not_met])
    frozen = {
        "status": "ACTIVE",
        "lease_fence": 1,
        "action_receipt_count": 1,
        "workspace_tree_sha256": "after",
        "provider_ledger_sha256": "provider",
    }
    terminal = {
        **frozen,
        "status": "COMPLETED",
        "lease_fence": 2,
    }
    evidence = iter((frozen, terminal, terminal))
    result = protocol.resume_spine(
        resume,
        ("task:i",),
        lambda _application, _task_id: dict(next(evidence)),
    )
    assert result == [
        {"resumed_terminal": terminal, "terminal_replay": terminal}
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


def test_coordinator_runs_four_exact_checked_commands(
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
        (coordinator.RUNNER_ANCHOR_COMMAND, True),
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


# Task 4: pure mechanical adjudication.  The builder deliberately contains the
# whole successful input contract so every mutation below changes one rule.
_ADJUDICATION_PHASES = [
    "prepare",
    "interrupt_batch",
    "probe_active_lease",
    "resume",
    "adjudicate",
]
_ADJUDICATION_NODES = [
    "read",
    "provider",
    "approve",
    "apply",
    "tests",
    "evaluate",
    "done",
]
_ADJUDICATION_RESULT_KEYS = {
    "schema_version",
    "verdict",
    "reason_codes",
    "verified_case_count",
    "case_results",
    "input_sha256",
}


def _sha(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_sha(value: object) -> str:
    import hashlib

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _receipt(case_id: str, arm: str) -> dict[str, str]:
    return {
        "capability_id": "workspace.apply_patch",
        "idempotency_key": f"spine:{case_id}:{arm}:apply",
    }


def _terminal(
    case_id: str,
    *,
    workflow_sha256: str,
    target_sha256: str,
    arm: str,
    fence: int,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "task_sequence": 21,
        "task_status": "COMPLETED",
        "run_status": "SUCCEEDED",
        "outcome_status": "VERIFIED",
        "outcome_score": 1,
        "evaluator_type": "pytest",
        "evaluator_version": "1",
        "workflow_sha256": workflow_sha256,
        "completed_node_ids": list(_ADJUDICATION_NODES),
        "target_sha256": target_sha256,
        "pytest_exit_code": 0,
        "apply_receipts": [_receipt(case_id, arm)],
        "lease_fence": fence,
        "evidence_sha256": _sha(f"{case_id}:{arm}:terminal-evidence"),
        "workspace_tree_sha256": _sha(f"{case_id}:final-workspace"),
        "provider_request_count": 2,
        "normalized_projection": {
            "task_status": "COMPLETED",
            "run_status": "SUCCEEDED",
            "outcome_status": "VERIFIED",
            "completed_node_ids": list(_ADJUDICATION_NODES),
            "target_sha256": target_sha256,
        },
    }


def _successful_adjudication_payload() -> dict[str, object]:
    from copy import deepcopy

    case_ids = [
        case["case_id"]
        for case in json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    ]
    bindings = {
        "case_manifest_sha256": _sha("case-manifest"),
        "workflow_sha256": _sha("workflow"),
        "evaluator_sha256": _sha("evaluator"),
        "provider_bank_sha256": _sha("provider-bank"),
    }
    cases: dict[str, object] = {}
    for case_id in case_ids:
        target = _sha(f"{case_id}:target")
        uninterrupted = _terminal(
            case_id,
            workflow_sha256=bindings["workflow_sha256"],
            target_sha256=target,
            arm="uninterrupted",
            fence=1,
        )
        interrupted = {
            "case_id": case_id,
            "task_sequence": 14,
            "task_status": "ACTIVE",
            "run_status": "RUNNING",
            "workflow_sha256": bindings["workflow_sha256"],
            "target_sha256": target,
            "apply_receipts": [_receipt(case_id, "interrupted")],
            "lease_fence": 7,
            "evidence_sha256": _sha(f"{case_id}:interrupted-evidence"),
            "workspace_tree_sha256": _sha(f"{case_id}:final-workspace"),
            "provider_request_count": 2,
            "normalized_projection": {
                "task_status": "ACTIVE",
                "run_status": "RUNNING",
                "target_sha256": target,
            },
        }
        probe = {**deepcopy(interrupted), "denial_type": "ConcurrentWriteError"}
        resumed = _terminal(
            case_id,
            workflow_sha256=bindings["workflow_sha256"],
            target_sha256=target,
            arm="interrupted",
            fence=8,
        )
        # Cross-arm normalized semantic equality excludes random arm identity.
        uninterrupted["normalized_projection"] = deepcopy(
            resumed["normalized_projection"]
        )
        cases[case_id] = {
            "expected_final_target_sha256": target,
            "expected_workflow_sha256": bindings["workflow_sha256"],
            "provider_rejected_attempt_count": 0,
            "unexpected_policy_events": [],
            "unexpected_correction_events": [],
            "uninterrupted_terminal": uninterrupted,
            "interrupted_after_apply": interrupted,
            "probe": probe,
            "resumed_terminal": resumed,
            "terminal_replay": deepcopy(resumed),
        }
    context = _sha("phase-context")
    boot = _sha("boot-id")
    # Payload is written before adjudicate runs; completed and runner_anchors
    # cover only the four pre-adjudication phases.  finalize-result verifies
    # the adjudicate completion/anchor independently.
    _payload_phases = [p for p in _ADJUDICATION_PHASES if p != "adjudicate"]
    return {
        "schema_version": "spine-e2e-1-adjudication-input-v1",
        "expected_case_ids": case_ids,
        "bindings": {"expected": bindings, "observed": deepcopy(bindings)},
        "phases": {
            "expected_order": list(_ADJUDICATION_PHASES),
            "completed": list(_payload_phases),
            "context_sha256": context,
            "boot_id_sha256": boot,
            "runner_anchors": {
                phase: {
                    "context_sha256": context,
                    "boot_id_sha256": boot,
                    "anchor_sha256": _sha(f"anchor:{phase}"),
                }
                for phase in _payload_phases
            },
        },
        "recovery_configuration": [
            {"phase": "probe_active_lease", "recover_stale_lease": False},
            {"phase": "resume", "recover_stale_lease": False},
            {"phase": "terminal_replay", "recover_stale_lease": False},
        ],
        "cases": cases,
    }


def _adjudicate(payload: dict[str, object]) -> dict[str, object]:
    protocol = _module("product_evals.spine_e2e_1.protocol")
    return protocol.adjudicate_spine(payload)


def _assert_result_shape(
    result: dict[str, object], payload: dict[str, object], verdict: str
) -> None:
    assert set(result) == _ADJUDICATION_RESULT_KEYS
    assert result["schema_version"] == "spine-e2e-1-adjudication-result-v1"
    assert result["verdict"] == verdict
    assert result["input_sha256"] == _canonical_sha(payload)
    assert type(result["verified_case_count"]) is int
    reasons = result["reason_codes"]
    assert reasons == sorted(set(reasons))
    assert set(result["case_results"]) == set(payload["expected_case_ids"])


def test_adjudicate_spine_passes_only_complete_twelve_case_baseline() -> None:
    payload = _successful_adjudication_payload()
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "PASS")
    assert result["reason_codes"] == []
    assert result["verified_case_count"] == 12
    assert set(result["case_results"].values()) == {"PASS"}


def test_adjudicate_spine_rejects_any_provider_rejected_attempt() -> None:
    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    payload["cases"][case_id]["provider_rejected_attempt_count"] = 1
    result = _adjudicate(payload)
    assert result["verdict"] == "INVALID"
    assert f"CASE_INSTRUMENTATION:{case_id}" in result["reason_codes"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_status", "FAILED"),
        ("run_status", "FAILED"),
        ("outcome_status", "NOT_MET"),
        ("outcome_score", 0),
        ("evaluator_type", "unittest"),
        ("evaluator_version", "2"),
        ("workflow_sha256", _sha("wrong-workflow")),
        ("completed_node_ids", _ADJUDICATION_NODES[:-1]),
        ("target_sha256", _sha("wrong-target")),
        ("pytest_exit_code", 1),
    ],
)
def test_adjudicate_spine_intact_ordinary_product_failure_is_not_pass(
    field: str, value: object
) -> None:
    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    terminal = payload["cases"][case_id]["uninterrupted_terminal"]
    terminal[field] = value
    if field in terminal["normalized_projection"]:
        terminal["normalized_projection"][field] = value
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "NOT_PASS")
    assert result["verified_case_count"] == 11
    assert result["case_results"][case_id] == "NOT_PASS"


def test_adjudicate_spine_invalidity_wins_over_product_failure() -> None:
    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    payload["cases"][case_id]["uninterrupted_terminal"]["run_status"] = "FAILED"
    payload["bindings"]["observed"]["workflow_sha256"] = _sha("drift")
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "INVALID")
    assert result["case_results"][case_id] == "INVALID"


@pytest.mark.parametrize(
    "field", sorted(_successful_adjudication_payload()["bindings"]["observed"])
)
def test_adjudicate_spine_rejects_each_binding_drift(field: str) -> None:
    payload = _successful_adjudication_payload()
    payload["bindings"]["observed"][field] = _sha(f"drift:{field}")
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "INVALID")
    assert set(result["case_results"].values()) == {"INVALID"}
    assert result["verified_case_count"] == 0


def test_adjudicate_spine_cross_arm_semantic_mismatch_is_not_pass() -> None:
    from copy import deepcopy

    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    case = payload["cases"][case_id]
    wrong_target = _sha("self-consistent-cross-arm-target")
    case["resumed_terminal"]["target_sha256"] = wrong_target
    case["resumed_terminal"]["normalized_projection"]["target_sha256"] = wrong_target
    case["terminal_replay"] = deepcopy(case["resumed_terminal"])
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "NOT_PASS")
    assert result["case_results"][case_id] == "NOT_PASS"
    assert result["verified_case_count"] == 11


def test_adjudicate_spine_snapshot_projection_contradiction_is_invalid() -> None:
    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    payload["cases"][case_id]["uninterrupted_terminal"]["run_status"] = "FAILED"
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "INVALID")
    assert result["case_results"][case_id] == "INVALID"
    assert result["verified_case_count"] == 11


@pytest.mark.parametrize(
    "mutation",
    ["terminal_missing", "terminal_extra", "interrupted_missing", "probe_extra"],
)
def test_adjudicate_spine_normalized_projection_schema_is_exact(
    mutation: str,
) -> None:
    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    case = payload["cases"][case_id]
    if mutation == "terminal_missing":
        del case["uninterrupted_terminal"]["normalized_projection"]["run_status"]
    elif mutation == "terminal_extra":
        case["resumed_terminal"]["normalized_projection"]["extra"] = "forbidden"
        case["terminal_replay"]["normalized_projection"]["extra"] = "forbidden"
    elif mutation == "interrupted_missing":
        del case["interrupted_after_apply"]["normalized_projection"]["task_status"]
    else:
        case["probe"]["normalized_projection"]["extra"] = "forbidden"
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "INVALID")
    assert result["case_results"][case_id] == "INVALID"
    assert result["verified_case_count"] == 11


def test_adjudicate_spine_intact_recovery_failure_is_not_pass() -> None:
    from copy import deepcopy

    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    case = payload["cases"][case_id]
    resumed = case["resumed_terminal"]
    resumed.update(
        {
            "task_status": "FAILED",
            "run_status": "FAILED",
            "outcome_status": "NOT_MET",
            "pytest_exit_code": 1,
        }
    )
    resumed["normalized_projection"].update(
        {
            "task_status": "FAILED",
            "run_status": "FAILED",
            "outcome_status": "NOT_MET",
        }
    )
    case["terminal_replay"] = deepcopy(resumed)
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "NOT_PASS")
    assert result["case_results"][case_id] == "NOT_PASS"
    assert result["verified_case_count"] == 11


@pytest.mark.parametrize(
    "mutation",
    [
        "interrupted_workflow",
        "probe_workflow",
        "interrupted_target",
        "probe_target",
        "resumed_workspace",
        "replay_workspace",
    ],
)
def test_adjudicate_spine_cross_phase_evidence_relation_drift_is_invalid(
    mutation: str,
) -> None:
    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    case = payload["cases"][case_id]
    if mutation == "interrupted_workflow":
        case["interrupted_after_apply"]["workflow_sha256"] = _sha("drift")
    elif mutation == "probe_workflow":
        case["probe"]["workflow_sha256"] = _sha("drift")
    elif mutation == "interrupted_target":
        case["interrupted_after_apply"]["target_sha256"] = _sha("drift")
        case["interrupted_after_apply"]["normalized_projection"]["target_sha256"] = (
            case["interrupted_after_apply"]["target_sha256"]
        )
    elif mutation == "probe_target":
        case["probe"]["target_sha256"] = _sha("drift")
        case["probe"]["normalized_projection"]["target_sha256"] = case["probe"][
            "target_sha256"
        ]
    elif mutation == "resumed_workspace":
        case["resumed_terminal"]["workspace_tree_sha256"] = _sha("drift")
    else:
        case["terminal_replay"]["workspace_tree_sha256"] = _sha("drift")
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "INVALID")
    assert result["case_results"][case_id] == "INVALID"
    assert result["verified_case_count"] == 11


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_case",
        "extra_case",
        "wrong_case_id",
        "binding_drift",
        "phase_order_drift",
        "incomplete_phase",
        "phase_context_drift",
        "phase_boot_drift",
        "missing_anchor",
        "anchor_context_drift",
        "anchor_boot_drift",
        "forced_takeover",
        "probe_wrong_denial",
        "probe_state_mutation",
        "provider_count_drift",
        "lease_fence_drift",
        "duplicate_receipt",
        "duplicate_idempotency_key",
        "terminal_replay_mismatch",
        "policy_event",
        "correction_event",
    ],
)
def test_adjudicate_spine_protocol_and_instrumentation_mutations_are_invalid(
    mutation: str,
) -> None:
    from copy import deepcopy

    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    case = payload["cases"][case_id]
    if mutation == "missing_case":
        del payload["cases"][case_id]
    elif mutation == "extra_case":
        payload["cases"]["extra"] = deepcopy(case)
    elif mutation == "wrong_case_id":
        case["probe"]["case_id"] = "wrong"
    elif mutation == "binding_drift":
        payload["bindings"]["observed"]["provider_bank_sha256"] = _sha("drift")
    elif mutation == "phase_order_drift":
        payload["phases"]["expected_order"] = list(reversed(_ADJUDICATION_PHASES))
    elif mutation == "incomplete_phase":
        payload["phases"]["completed"].pop()
    elif mutation == "phase_context_drift":
        payload["phases"]["context_sha256"] = _sha("drift")
    elif mutation == "phase_boot_drift":
        payload["phases"]["boot_id_sha256"] = _sha("drift")
    elif mutation == "missing_anchor":
        del payload["phases"]["runner_anchors"]["probe_active_lease"]
    elif mutation == "anchor_context_drift":
        payload["phases"]["runner_anchors"]["resume"]["context_sha256"] = _sha("drift")
    elif mutation == "anchor_boot_drift":
        payload["phases"]["runner_anchors"]["resume"]["boot_id_sha256"] = _sha("drift")
    elif mutation == "forced_takeover":
        payload["recovery_configuration"][1]["recover_stale_lease"] = True
    elif mutation == "probe_wrong_denial":
        case["probe"]["denial_type"] = "TimeoutError"
    elif mutation == "probe_state_mutation":
        case["probe"]["task_sequence"] += 1
    elif mutation == "provider_count_drift":
        case["resumed_terminal"]["provider_request_count"] = 3
        case["terminal_replay"] = deepcopy(case["resumed_terminal"])
    elif mutation == "lease_fence_drift":
        case["resumed_terminal"]["lease_fence"] += 1
        case["terminal_replay"] = deepcopy(case["resumed_terminal"])
    elif mutation == "duplicate_receipt":
        case["resumed_terminal"]["apply_receipts"].append(
            _receipt(case_id, "duplicate")
        )
        case["terminal_replay"] = deepcopy(case["resumed_terminal"])
    elif mutation == "duplicate_idempotency_key":
        receipt = deepcopy(case["resumed_terminal"]["apply_receipts"][0])
        case["resumed_terminal"]["apply_receipts"].append(receipt)
        case["terminal_replay"] = deepcopy(case["resumed_terminal"])
    elif mutation == "terminal_replay_mismatch":
        case["terminal_replay"]["task_sequence"] += 1
    elif mutation == "policy_event":
        case["unexpected_policy_events"].append({"type": "POLICY_DENIED"})
    elif mutation == "correction_event":
        case["unexpected_correction_events"].append({"type": "PAUSED"})
    result = _adjudicate(payload)
    _assert_result_shape(result, payload, "INVALID")
    assert result["case_results"][case_id] == "INVALID"
    global_mutations = {
        "missing_case",
        "extra_case",
        "binding_drift",
        "phase_order_drift",
        "incomplete_phase",
        "phase_context_drift",
        "phase_boot_drift",
        "missing_anchor",
        "anchor_context_drift",
        "anchor_boot_drift",
        "forced_takeover",
    }
    if mutation in global_mutations:
        assert result["verified_case_count"] == 0
        assert set(result["case_results"].values()) == {"INVALID"}
    else:
        assert result["verified_case_count"] == 11
        assert set(result["case_results"].values()) == {"PASS", "INVALID"}


@pytest.mark.parametrize(
    "mutation",
    [
        "top_unknown_field",
        "case_unknown_field",
        "wrong_integer_bool",
        "duplicate_expected_case",
        "duplicate_completed_phase",
        "non_json_value",
        "missing_evidence",
        "malformed_evidence",
        "wrong_receipt_capability",
        "blank_idempotency",
        "receipt_missing_field",
        "receipt_extra_field",
        "nested_missing_field",
        "nested_wrong_type",
    ],
)
def test_adjudicate_spine_exact_schema_rejects_unknown_wrong_and_duplicate_values(
    mutation: str,
) -> None:
    payload = _successful_adjudication_payload()
    case_id = payload["expected_case_ids"][0]
    if mutation == "top_unknown_field":
        payload["unknown"] = "forbidden"
    elif mutation == "case_unknown_field":
        payload["cases"][case_id]["unknown"] = "forbidden"
    elif mutation == "wrong_integer_bool":
        payload["cases"][case_id]["probe"]["provider_request_count"] = True
    elif mutation == "duplicate_expected_case":
        payload["expected_case_ids"].append(case_id)
    elif mutation == "duplicate_completed_phase":
        payload["phases"]["completed"].append("adjudicate")
    elif mutation == "non_json_value":
        payload["cases"][case_id]["probe"]["normalized_projection"] = {case_id}
    elif mutation == "missing_evidence":
        del payload["cases"][case_id]["probe"]["evidence_sha256"]
    elif mutation == "malformed_evidence":
        payload["cases"][case_id]["probe"]["evidence_sha256"] = "not-a-digest"
    elif mutation == "wrong_receipt_capability":
        payload["cases"][case_id]["resumed_terminal"]["apply_receipts"][0][
            "capability_id"
        ] = "workspace.read"
    elif mutation == "blank_idempotency":
        payload["cases"][case_id]["resumed_terminal"]["apply_receipts"][0][
            "idempotency_key"
        ] = ""
    elif mutation == "receipt_missing_field":
        del payload["cases"][case_id]["resumed_terminal"]["apply_receipts"][0][
            "idempotency_key"
        ]
    elif mutation == "receipt_extra_field":
        payload["cases"][case_id]["resumed_terminal"]["apply_receipts"][0]["extra"] = (
            "forbidden"
        )
    elif mutation == "nested_missing_field":
        del payload["phases"]["runner_anchors"]["resume"]["anchor_sha256"]
    elif mutation == "nested_wrong_type":
        payload["cases"][case_id]["resumed_terminal"]["lease_fence"] = "8"
    result = _adjudicate(payload)
    assert set(result) == _ADJUDICATION_RESULT_KEYS
    assert result["verdict"] == "INVALID"
