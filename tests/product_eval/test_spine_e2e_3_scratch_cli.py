"""Scratch-only behavioral coverage for the SPINE-E2E-3 CLI boundary."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from product_evals.common.artifacts import canonical_sha256, sha256_file
from product_evals.spine_e2e_3 import cli, protocol
from product_evals.spine_e2e_3.identity import IDENTITY


FORMAL_EVALUATION = (
    Path(__file__).resolve().parents[2].parents[2]
    / ".agent_runs"
    / IDENTITY.run_id
    / "evaluation"
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _scratch_run(tmp_path: Path) -> SimpleNamespace:
    data_root = tmp_path / "scratch" / "evaluation"
    return SimpleNamespace(
        workspace=tmp_path / "workspace",
        target=tmp_path / "target",
        run_root=tmp_path / "scratch",
        data_root=data_root,
        runner=tmp_path / "runner",
        phase_ledger=data_root / "phases.jsonl",
        provider_ledger=data_root / "provider_calls.jsonl",
        context_sha256="c" * 64,
        context_bindings={
            "spec_sha256": "s" * 64,
            "prereg_lock_sha256": "l" * 64,
            "corpus_sha256": "a" * 64,
            "evaluator_sha256": "b" * 64,
            "provider_bank_sha256": "d" * 64,
        },
    )


def test_resolve_frozen_run_uses_only_scratch_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "target"
    common = target / ".git"
    run_root = workspace / ".agent_runs" / IDENTITY.run_id
    runner = workspace / cli.RUNNER_WORKTREE_REL
    target.mkdir(parents=True)
    runner.mkdir(parents=True)

    spec_path = target / cli.SPEC_REL
    canonical_spec = run_root / "prereg.json"
    lock_path = run_root / "prereg.lock"
    evaluation_root = target / "product_evals" / IDENTITY.module_slug
    files = {
        "cases": evaluation_root / "frozen_cases.json",
        "bank": evaluation_root / "provider_responses.json",
        "template": evaluation_root / "request_template.json",
        "receipt": evaluation_root / "instrument_qualification_receipt.json",
        "evaluator": evaluation_root / "protocol.py",
        "mechanism": target / "scratch_mechanism.py",
    }
    for name, path in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n", encoding="utf-8")
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text("frozen-spec\n", encoding="utf-8")
    _write_json(canonical_spec, {"placeholder": True})
    lock = {
        "target_head": "h" * 40,
        "spec_file_sha256": sha256_file(spec_path),
        "spec_sha256": sha256_file(canonical_spec),
        "mechanism_files": {
            "scratch_mechanism.py": sha256_file(files["mechanism"]),
        },
    }
    binding_keys = [
        "schema",
        "experiment_id",
        "run_id",
        "target_head",
        "prereg_lock_sha256",
        "spec_sha256",
        "mechanism_manifest_sha256",
        "corpus_sha256",
        "provider_bank_sha256",
        "provider_template_sha256",
        "qualification_receipt_sha256",
        "evaluator_sha256",
        "runner_common_dir",
        "runner_head",
        "request_row_sha256",
        "approval_row_sha256",
    ]
    _write_json(
        canonical_spec,
        {
            "context_binding": {
                "algorithm": "canonical_sha256(exact_16_key_mapping)",
                "keys": binding_keys,
            }
        },
    )
    lock["spec_sha256"] = sha256_file(canonical_spec)
    _write_json(lock_path, lock)

    def fake_git(path: Path, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(target)
        if args == ("rev-parse", "--git-common-dir"):
            return str(common)
        if args == ("rev-parse", "HEAD"):
            return "h" * 40
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError((path, args))

    monkeypatch.setattr(cli, "_git", fake_git)
    monkeypatch.setattr(cli, "_verify_runner", lambda ws, value: None)
    monkeypatch.setattr(cli, "_verify_permission_rows", lambda value: None)
    monkeypatch.setattr(cli, "phase_context_sha256", lambda value: "f" * 64)

    resolved = cli.resolve_frozen_run()

    assert resolved.run_root == run_root
    assert resolved.data_root == run_root / "evaluation"
    assert resolved.target == target
    assert resolved.runner == runner
    assert resolved.context_sha256 == "f" * 64
    assert list(resolved.context_bindings) == binding_keys
    assert resolved.data_root != FORMAL_EVALUATION


def test_verify_runner_accepts_exact_scratch_anchor_and_rejects_head_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    runner = workspace / cli.RUNNER_WORKTREE_REL
    runner.mkdir(parents=True)

    def exact_git(path: Path, *args: str) -> str:
        values = {
            ("rev-parse", "--git-common-dir"): str(workspace / cli.RUNNER_COMMON_DIR),
            ("rev-parse", "--abbrev-ref", "HEAD"): cli.RUNNER_BRANCH,
            ("rev-parse", "HEAD"): cli.RUNNER_HEAD,
            ("status", "--porcelain"): "",
        }
        return values[args]

    monkeypatch.setattr(cli, "_git", exact_git)
    cli._verify_runner(workspace, runner)

    monkeypatch.setattr(
        cli,
        "_git",
        lambda path, *args: (
            "0" * 40 if args == ("rev-parse", "HEAD") else exact_git(path, *args)
        ),
    )
    with pytest.raises(ValueError, match="INVALID_GIT_STATE"):
        cli._verify_runner(workspace, runner)


def test_phase_anchor_verifies_exact_schema_and_event_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _scratch_run(tmp_path)
    run.phase_ledger.parent.mkdir(parents=True)
    run.phase_ledger.write_bytes(b"started\ncompleted\n")
    run.provider_ledger.write_text("provider\n", encoding="utf-8")
    record = SimpleNamespace(
        ordinal=1,
        record_sha256="a" * 64,
        payload_sha256="b" * 64,
        clock=SimpleNamespace(boot_hash="d" * 64, host_hash="e" * 64),
    )
    provider_rows = [{"record_sha256": "f" * 64}]
    prefix_sha = cli.hashlib.sha256(run.phase_ledger.read_bytes()).hexdigest()
    anchor = {
        "schema_version": IDENTITY.schema("anchor-request"),
        "phase": "prepare",
        "phase_record_head_sha256": record.record_sha256,
        "phase_ledger_sha256": prefix_sha,
        "provider_ledger_head_sha256": "f" * 64,
        "provider_ledger_sha256": sha256_file(run.provider_ledger),
        "payload_sha256": record.payload_sha256,
        "boot_id_sha256": "d" * 64,
        "host_id_sha256": "e" * 64,
        "context_sha256": run.context_sha256,
        "runner_common_dir": cli.RUNNER_COMMON_DIR,
        "runner_branch": cli.RUNNER_BRANCH,
        "runner_head": cli.RUNNER_HEAD,
        "approval_request_id": cli.APPROVAL_REQUEST_ID,
        "permission_action": "team.event.record",
        "request_row_sha256": cli.REQUEST_ROW_SHA256,
        "approval_row_sha256": cli.APPROVAL_ROW_SHA256,
    }
    anchor_path = run.run_root / cli._anchor_ref("prepare")
    _write_json(anchor_path, anchor)
    request_sha = canonical_sha256(anchor)
    _write_json(
        run.run_root / "agent_events.jsonl",
        {
            "ts": "2026-07-13T00:00:00Z",
            "type": "EVIDENCE_APPENDED",
            "agent_id": "codex-cto",
            "task_id": None,
            "summary": (
                f"SPINE_PHASE_ANCHOR phase=prepare request_sha256={request_sha}"
            ),
            "artifact": cli._anchor_ref("prepare"),
            "stream_file": None,
            "permission_action": "team.event.record",
            "approval_request_id": cli.APPROVAL_REQUEST_ID,
            "evidence_refs": [cli._anchor_ref("prepare")],
            "source_decision_type": "founder_authorization",
        },
    )
    monkeypatch.setattr(cli, "_completed_record", lambda value, phase: record)
    monkeypatch.setattr(cli, "_provider_ledger_rows", lambda value: provider_rows)
    monkeypatch.setattr(cli, "_verify_permission_rows", lambda value: None)
    monkeypatch.setattr(cli, "_verify_runner", lambda workspace, runner: None)

    assert cli._phase_anchor(run, "prepare") == anchor

    anchor["runner_head"] = "0" * 40
    _write_json(anchor_path, anchor)
    with pytest.raises(ValueError, match="INVALID_RUNNER_ANCHOR"):
        cli._phase_anchor(run, "prepare")


def test_run_phase_writes_only_scratch_payload_and_binds_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _scratch_run(tmp_path)
    bound: list[str] = []

    class Guard:
        def bind_payload(self, digest: str) -> None:
            bound.append(digest)

    @contextmanager
    def guard(*args: object, **kwargs: object):
        assert args[0] == run.phase_ledger
        assert kwargs["expected_context_sha256"] == run.context_sha256
        yield Guard()

    output = {"schema_version": IDENTITY.schema("prepare"), "cases": {}}
    monkeypatch.setattr(cli, "evaluation_genesis_preflight", lambda value: None)
    monkeypatch.setattr(cli, "_prior_anchor", lambda value, phase: None)
    monkeypatch.setattr(cli, "_execute_phase", lambda value, phase: output)
    monkeypatch.setattr(cli, "phase_guard", guard)

    cli._run_phase(run, "prepare")

    payload_path = run.data_root / "phases" / "prepare.json"
    assert json.loads(payload_path.read_text()) == output
    assert bound == [canonical_sha256(output)]
    assert payload_path.is_relative_to(tmp_path)
    assert not payload_path.is_relative_to(FORMAL_EVALUATION)


def test_build_adjudication_payload_binds_scratch_anchors_and_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _scratch_run(tmp_path)
    case = {"case_id": "case-1", "patched_content": "patched"}
    prepared = {
        "cases": {
            "case-1": {
                "paths": {
                    "uninterrupted": {"workspace": str(tmp_path / "u")},
                    "interrupted": {"workspace": str(tmp_path / "i")},
                },
                "public_evidence": {"uninterrupted": {}},
                "expected_workflow_sha256": "w" * 64,
            }
        }
    }
    phase_values = {
        "prepare": prepared,
        "interrupt_batch": {"cases": {"case-1": {}}},
        "probe_active_lease": {"cases": {"case-1": {}}},
        "resume": {
            "cases": {"case-1": {"resumed_terminal": {}, "terminal_replay": {}}}
        },
    }
    monkeypatch.setattr(cli, "_load_phase", lambda value, phase: phase_values[phase])
    monkeypatch.setattr(
        cli,
        "_phase_anchor",
        lambda value, phase: {
            "context_sha256": run.context_sha256,
            "boot_id_sha256": "z" * 64,
            "phase": phase,
        },
    )
    monkeypatch.setattr(cli, "_provider_counts", lambda value: ({"case-1": 2}, 0))
    monkeypatch.setattr(cli, "_cases", lambda value: [case])
    monkeypatch.setattr(
        cli,
        "_snapshot",
        lambda *args, **kwargs: {"workflow_sha256": "w" * 64},
    )
    monkeypatch.setattr(cli, "_unexpected_events", lambda *values: ([], []))
    monkeypatch.setattr(
        cli,
        "read_phases",
        lambda *args: [SimpleNamespace(clock=SimpleNamespace(boot_hash="z" * 64))],
    )

    payload = cli._build_adjudication_payload(run)

    assert payload["schema_version"] == IDENTITY.schema("adjudication-input")
    assert payload["expected_case_ids"] == ["case-1"]
    assert payload["phases"]["completed"] == list(cli.PHASES[:-1])
    assert set(payload["phases"]["runner_anchors"]) == set(cli.PHASES[:-1])
    assert payload["bindings"]["expected"] == payload["bindings"]["observed"]
    assert payload["cases"]["case-1"]["expected_final_target_sha256"] == (
        cli.hashlib.sha256(b"patched").hexdigest()
    )


def _sha(label: str) -> str:
    return cli.hashlib.sha256(label.encode("utf-8")).hexdigest()


def _receipt(case_id: str, arm: str) -> dict[str, str]:
    return {
        "capability_id": "workspace.apply_patch",
        "idempotency_key": f"{IDENTITY.slug}:{case_id}:{arm}:apply",
    }


def _terminal(
    case_id: str,
    *,
    workflow_sha256: str,
    target_sha256: str,
    arm: str,
    fence: int,
) -> dict[str, object]:
    nodes = list(protocol._ADJUDICATION_NODES)
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
        "completed_node_ids": nodes,
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
            "completed_node_ids": nodes,
            "target_sha256": target_sha256,
        },
    }


def _successful_e2e3_payload() -> dict[str, object]:
    case_ids = list(protocol._ADJUDICATION_CASE_IDS)
    phases = list(protocol._ADJUDICATION_PHASES)
    payload_phases = list(protocol._PAYLOAD_PHASES)
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
    return {
        "schema_version": IDENTITY.schema("adjudication-input"),
        "expected_case_ids": case_ids,
        "bindings": {"expected": bindings, "observed": deepcopy(bindings)},
        "phases": {
            "expected_order": phases,
            "completed": payload_phases,
            "context_sha256": context,
            "boot_id_sha256": boot,
            "runner_anchors": {
                phase: {
                    "context_sha256": context,
                    "boot_id_sha256": boot,
                    "anchor_sha256": _sha(f"anchor:{phase}"),
                }
                for phase in payload_phases
            },
        },
        "recovery_configuration": [
            {"phase": "probe_active_lease", "recover_stale_lease": False},
            {"phase": "resume", "recover_stale_lease": False},
            {"phase": "terminal_replay", "recover_stale_lease": False},
        ],
        "cases": cases,
    }


def test_adjudication_precedence_is_pass_then_not_pass_then_invalid() -> None:
    passing = _successful_e2e3_payload()
    assert protocol.adjudicate_spine(passing)["verdict"] == "PASS"

    not_pass = deepcopy(passing)
    case_id = not_pass["expected_case_ids"][0]
    terminal = not_pass["cases"][case_id]["uninterrupted_terminal"]
    terminal["run_status"] = "FAILED"
    terminal["normalized_projection"]["run_status"] = "FAILED"
    assert protocol.adjudicate_spine(not_pass)["verdict"] == "NOT_PASS"

    invalid = deepcopy(not_pass)
    invalid["bindings"]["observed"]["workflow_sha256"] = "0" * 64
    result = protocol.adjudicate_spine(invalid)
    assert result["verdict"] == "INVALID"
    assert set(result["case_results"].values()) == {"INVALID"}


def test_finalize_result_is_write_once_and_binds_scratch_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _scratch_run(tmp_path)
    run.phase_ledger.parent.mkdir(parents=True)
    run.phase_ledger.write_text("phase-ledger\n", encoding="utf-8")
    run.provider_ledger.write_text("provider-ledger\n", encoding="utf-8")
    phases = [
        f"{phase}_{suffix}"
        for phase in cli.PHASES
        for suffix in ("started", "completed")
    ]
    payload = {"payload": "scratch-frozen"}
    payload_path = run.data_root / "phases" / "adjudication_payload.json"
    _write_json(payload_path, payload)
    monkeypatch.setattr(
        cli,
        "read_phases",
        lambda path, context: [SimpleNamespace(phase=phase) for phase in phases],
    )
    monkeypatch.setattr(cli, "_phase_anchor", lambda value, phase: {"phase": phase})
    monkeypatch.setattr(
        cli,
        "_completed_record",
        lambda value, phase: SimpleNamespace(payload_sha256=canonical_sha256(payload)),
    )
    monkeypatch.setattr(
        cli,
        "adjudicate_spine",
        lambda value: {
            "schema_version": IDENTITY.schema("adjudication-result"),
            "verdict": "PASS",
        },
    )

    cli._finalize_result(run)

    result_path = run.data_root / "result.json"
    result = json.loads(result_path.read_text())
    assert result["schema_version"] == IDENTITY.schema("result")
    assert result["experiment_id"] == IDENTITY.experiment_id
    assert result["run_id"] == IDENTITY.run_id
    assert result["adjudication_payload_sha256"] == canonical_sha256(payload)
    assert result["phase_ledger_sha256"] == sha256_file(run.phase_ledger)
    assert result["provider_ledger_sha256"] == sha256_file(run.provider_ledger)
    with pytest.raises(FileExistsError):
        cli._finalize_result(run)
    assert result_path.is_relative_to(tmp_path)
    assert not result_path.is_relative_to(FORMAL_EVALUATION)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("prepare", ("phase", "prepare")),
        ("interrupt-batch", ("phase", "interrupt_batch")),
        ("probe-active-lease", ("phase", "probe_active_lease")),
        ("resume", ("phase", "resume")),
        ("adjudicate", ("phase", "adjudicate")),
        ("record-runner-anchor", ("anchor", None)),
        ("finalize-result", ("finalize", None)),
    ],
)
def test_cli_dispatches_only_to_the_resolved_scratch_run(
    command: str,
    expected: tuple[str, str | None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _scratch_run(tmp_path)
    calls: list[tuple[str, str | None, object]] = []
    monkeypatch.setattr(cli, "resolve_frozen_run", lambda: run)
    monkeypatch.setattr(
        cli,
        "_run_phase",
        lambda value, phase: calls.append(("phase", phase, value)),
    )
    monkeypatch.setattr(
        cli,
        "_record_runner_anchor",
        lambda value: calls.append(("anchor", None, value)),
    )
    monkeypatch.setattr(
        cli,
        "_finalize_result",
        lambda value: calls.append(("finalize", None, value)),
    )

    assert cli.main([command]) == 0
    assert calls == [(expected[0], expected[1], run)]
    assert not run.data_root.is_relative_to(FORMAL_EVALUATION)
