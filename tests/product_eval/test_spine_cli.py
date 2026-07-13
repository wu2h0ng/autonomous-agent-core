"""Frozen RED contract for the SPINE-E2E-1 production phase CLI."""

from __future__ import annotations

import ast
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "product_evals/spine_e2e_1/cli.py"
COORDINATOR = "product_evals.spine_e2e_1.coordinator"
COMMANDS = {
    "prepare",
    "interrupt-batch",
    "probe-active-lease",
    "resume",
    "adjudicate",
    "record-runner-anchor",
    "finalize-result",
}
PHASES = {
    "prepare",
    "interrupt_batch",
    "probe_active_lease",
    "resume",
    "adjudicate",
}
CONTEXT_BINDINGS = {
    "schema",
    "experiment_id",
    "run_id",
    "target_head",
    "prereg_lock_sha256",
    "spec_sha256",
    "mechanism_manifest_sha256",
    "corpus_sha256",
    "provider_bank_sha256",
    "evaluator_sha256",
    "runner_common_dir",
    "runner_head",
    "request_row_sha256",
    "approval_row_sha256",
}
ANCHOR_FIELDS = {
    "schema_version",
    "phase",
    "phase_record_head_sha256",
    "phase_ledger_sha256",
    "provider_ledger_head_sha256",
    "provider_ledger_sha256",
    "payload_sha256",
    "boot_id_sha256",
    "host_id_sha256",
    "context_sha256",
    "runner_common_dir",
    "runner_branch",
    "runner_head",
    "approval_request_id",
    "permission_action",
    "request_row_sha256",
    "approval_row_sha256",
}


def _cli():
    return importlib.import_module("product_evals.spine_e2e_1.cli")


def _tree() -> ast.Module:
    assert CLI_PATH.exists(), "Task 5 production CLI is not implemented"
    return ast.parse(CLI_PATH.read_text(encoding="utf-8"), filename=str(CLI_PATH))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected one {name} function"
    return matches[0]


def _string_constants(node: ast.AST) -> set[str]:
    return {
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.add(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.add(item.func.attr)
    return names


def test_cli_exposes_only_fixed_commands_and_minimal_public_interface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _cli()
    assert tuple(inspect.signature(cli.resolve_frozen_run).parameters) == ()
    assert tuple(inspect.signature(cli.main).parameters) == ("argv",)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--help"])
    assert stopped.value.code == 0
    help_text = capsys.readouterr().out
    for command in COMMANDS:
        assert command in help_text


def test_cli_parser_and_ast_forbid_clock_threshold_test_and_authority_inputs() -> None:
    source = CLI_PATH.read_text(encoding="utf-8") if CLI_PATH.exists() else ""
    forbidden = {
        "--now",
        "--clock",
        "--min-seconds",
        "--test-mode",
        "allow_short_timing",
        "--context",
        "--run-root",
        "--ledger-path",
        "--spec-path",
        "--lock-path",
        "--phase",
    }
    assert not (forbidden & _string_constants(_tree()))
    assert "SPINE_MIN_SECONDS" not in source
    assert "SPINE_MAX_SECONDS" not in source
    assert "os.environ" not in source


def test_resolver_is_sole_context_authority_and_binds_every_frozen_source() -> None:
    tree = _tree()
    resolver = _function(tree, "resolve_frozen_run")
    module_strings = _string_constants(tree)
    assert CONTEXT_BINDINGS <= module_strings
    assert {
        "804c8d54bf5b78d9d850edb452db4affe3c1cd22",
        "codex/agent-os-product-prereg-target-20260712",
        "spine-e2e-1-20260712",
    } <= module_strings
    assert {
        "phase_context_sha256",
        "sha256_file",
    } <= _called_names(resolver)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name != "resolve_frozen_run":
            assert "phase_context_sha256" not in _called_names(node)


def test_resolver_validates_runner_git_and_canonical_permission_rows() -> None:
    source = CLI_PATH.read_text(encoding="utf-8")
    for required in (
        "rev-parse",
        "status",
        "--porcelain",
        "approval_requests.jsonl",
        "approvals.jsonl",
        "approved_session",
        "team.event.record",
        "request_row_sha256",
        "approval_row_sha256",
    ):
        assert required in source
    assert "approved_once" in source
    assert "approved_until_expiry" in source


def test_phase_dispatch_freezes_sequence_timing_and_resolver_derived_context() -> None:
    tree = _tree()
    runner = _function(tree, "_run_phase")
    strings = _string_constants(runner)
    assert PHASES <= strings
    assert {"prepare", "interrupt_batch", "probe_active_lease", "resume"} <= strings
    assert {"phase_guard", "write_json_once"} <= _called_names(runner)
    source = ast.unparse(runner)
    assert "60" in source
    assert "360" in source
    assert "1800" in source
    assert "expected_context_sha256" in source
    assert "resolve_frozen_run" not in source


def test_phase_failures_and_replays_are_gated_before_product_side_effects() -> None:
    function = _function(_tree(), "_run_phase")
    source = ast.unparse(function)
    guard_at = source.index("phase_guard")
    write_at = source.index("write_json_once")
    for product_call in (
        "prepare_case",
        "interrupt_batch",
        "probe_active_lease",
        "resume_spine",
    ):
        calls = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == product_call
        ]
        for call in calls:
            call_source = ast.unparse(call)
            assert guard_at < source.index(call_source) < write_at


def test_anchor_request_schema_summary_and_runner_event_are_exact_and_write_once() -> None:
    anchor = _function(_tree(), "_record_runner_anchor")
    strings = _string_constants(anchor)
    assert ANCHOR_FIELDS <= strings
    assert "spine-e2e-1-anchor-request-v1" in strings
    source = ast.unparse(anchor)
    assert "write_json_once" in source
    assert "EVIDENCE_APPENDED" in source
    assert "team.event.record" in source
    assert "SPINE_PHASE_ANCHOR phase=" in source
    assert "request_sha256=" in source
    assert source.count("evidence-ref") >= 1
    assert "artifact" in source


def test_provider_accounting_preserves_rejected_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _cli()
    run = SimpleNamespace(bank_path=Path("unused"))
    monkeypatch.setattr(
        cli,
        "_json_file",
        lambda _path: {
            "entries": [
                {"case_id": "st_reverse", "digest": "a" * 64},
            ]
        },
    )
    monkeypatch.setattr(
        cli,
        "_provider_ledger_rows",
        lambda _run: [
            {"accepted": True, "request_digest": "a" * 64},
            {"accepted": False, "request_digest": "b" * 64},
        ],
    )
    counts, rejected = cli._provider_counts(run)
    assert counts == {"st_reverse": 1}
    assert rejected == 1


def test_unexpected_event_extraction_consumes_public_events() -> None:
    cli = _cli()
    evidence = {
        "projection": {
            "task": {
                "events": [
                    {
                        "event_type": "POLICY_DECIDED",
                        "payload": {"decision": {"verdict": "DENY"}},
                    },
                    {"event_type": "CORRECTION_WRITTEN", "payload": {}},
                    {"event_type": "COMPENSATION_STARTED", "payload": {}},
                ]
            }
        }
    }
    policy, correction = cli._unexpected_events(evidence)
    assert [event["event_type"] for event in policy] == ["POLICY_DECIDED"]
    assert [event["event_type"] for event in correction] == [
        "CORRECTION_WRITTEN",
        "COMPENSATION_STARTED",
    ]


def test_finalize_is_pure_packaging_and_result_is_write_once() -> None:
    finalize = _function(_tree(), "_finalize_result")
    calls = _called_names(finalize)
    assert "adjudicate_spine" in calls
    assert "write_json_once" in calls
    assert "read_phases" in calls
    forbidden_calls = {
        "phase_guard",
        "prepare_case",
        "interrupt_batch",
        "probe_active_lease",
        "resume_spine",
        "FrozenProviderServer",
        "open_application",
        "run",
        "Popen",
    }
    assert not (calls & forbidden_calls)
    source = ast.unparse(finalize)
    assert "adjudication_payload.json" in source
    assert "result.json" in source
    assert "runner_anchors" in source


def test_finalize_preserves_wrapper_schema_behaviorally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = _cli()
    phase_ledger = tmp_path / "phases.jsonl"
    provider_ledger = tmp_path / "provider.jsonl"
    phase_ledger.write_text("phase-ledger\n")
    provider_ledger.write_text("provider-ledger\n")
    phases = [
        f"{phase}_{suffix}"
        for phase in ("prepare", "interrupt_batch", "probe_active_lease", "resume", "adjudicate")
        for suffix in ("started", "completed")
    ]
    monkeypatch.setattr(
        cli,
        "read_phases",
        lambda _path, _context: [SimpleNamespace(phase=phase) for phase in phases],
    )
    monkeypatch.setattr(cli, "_phase_anchor", lambda _run, phase: {"phase": phase})
    payload = {"payload": "frozen"}
    monkeypatch.setattr(cli, "_json_file", lambda _path: payload)
    monkeypatch.setattr(
        cli,
        "_completed_record",
        lambda _run, _phase: SimpleNamespace(payload_sha256=cli.canonical_sha256(payload)),
    )
    monkeypatch.setattr(
        cli,
        "adjudicate_spine",
        lambda _payload: {
            "schema_version": "spine-e2e-1-adjudication-result-v1",
            "verdict": "PASS",
        },
    )
    run = SimpleNamespace(
        data_root=tmp_path / "evaluation",
        context_sha256="c" * 64,
        context_bindings={
            "spec_sha256": "s" * 64,
            "prereg_lock_sha256": "l" * 64,
        },
        phase_ledger=phase_ledger,
        provider_ledger=provider_ledger,
    )
    cli._finalize_result(run)
    result = json.loads((run.data_root / "result.json").read_text())
    assert result["schema_version"] == "spine-e2e-1-result-v1"
    assert result["adjudication_schema_version"] == (
        "spine-e2e-1-adjudication-result-v1"
    )


def test_coordinator_records_runner_anchor_after_interrupt_and_after_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = importlib.import_module(COORDINATOR)
    calls: list[tuple[str, ...]] = []

    def capture(command: tuple[str, ...], *, check: bool) -> None:
        assert check is True
        calls.append(command)

    monkeypatch.setattr(coordinator.subprocess, "run", capture)
    coordinator.run_interrupt_and_probe()
    assert calls == [
        coordinator.INTERRUPT_COMMAND,
        coordinator.RUNNER_ANCHOR_COMMAND,
        coordinator.PROBE_COMMAND,
        coordinator.RUNNER_ANCHOR_COMMAND,
    ]
