"""Fail-closed production CLI for the frozen SPINE-E2E-1 run."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from product_evals.common.artifacts import (
    SCHEMA,
    ElapsedGate,
    canonical_sha256,
    phase_context_sha256,
    phase_guard,
    read_phases,
    sha256_file,
    write_json_once,
)
from product_evals.common.provider_bank import FrozenProviderServer
from product_evals.common.public_surface import (
    configure_provider_environment,
    open_application,
    prepare_case,
    public_evidence,
)
from product_evals.spine_e2e_1.protocol import (
    adjudicate_spine,
    interrupt_batch,
    probe_active_lease,
    resume_spine,
)

RUN_ID = "spine-e2e-1-20260712"
EXPERIMENT_ID = "SPINE-E2E-1"
RUNNER_HEAD = "804c8d54bf5b78d9d850edb452db4affe3c1cd22"
RUNNER_BRANCH = "codex/agent-os-product-prereg-target-20260712"
RUNNER_COMMON_DIR = "ai-agent-engineering-workflow/.git"
APPROVAL_REQUEST_ID = "perm_60811960d502c9a0"
REQUEST_ROW_SHA256 = "c9654fa8e00dff4b09ac3fa651b60bf9a074cd4a6d815687234739dceb0d98fb"
APPROVAL_ROW_SHA256 = "43849a6d5a04e3e4f3cd67113aff8ab5cc7f3a6bdbbe2c72cd1c0a83cc70004b"
RUNNER_WORKTREE_REL = "ai-agent-engineering-workflow/.worktrees/lh-prereg-target-fix-20260712"
SPEC_REL = "docs/research/SPINE-E2E-1-preregistration-spec.yaml"
PHASES = ("prepare", "interrupt_batch", "probe_active_lease", "resume", "adjudicate")
ANCHOR_REFS = tuple(f"evaluation/anchor_requests/{phase}.json" for phase in PHASES)
PERMISSION_PATH = f".agent_runs/{RUN_ID}/agent_events.jsonl"
_PENDING = hashlib.sha256(b"SPINE-E2E-1-PAYLOAD-PENDING-v1").hexdigest()


@dataclass(frozen=True)
class FrozenRun:
    workspace: Path
    target: Path
    run_root: Path
    data_root: Path
    runner: Path
    spec_path: Path
    lock_path: Path
    cases_path: Path
    bank_path: Path
    evaluator_path: Path
    phase_ledger: Path
    provider_ledger: Path
    context_bindings: dict[str, str]
    context_sha256: str
    spec: dict[str, Any]
    lock: dict[str, Any]


def _json_no_duplicates(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON number: {token}")
        ),
    )


def _json_file(path: Path) -> Any:
    return _json_no_duplicates(path.read_bytes())


def _jsonl(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n") or raw.startswith(b"\n") or b"\n\n" in raw:
        raise ValueError(f"invalid JSONL framing: {path.name}")
    rows = [_json_no_duplicates(line) for line in raw.splitlines()]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"invalid JSONL row: {path.name}")
    return rows


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ("git", *args), cwd=path, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _verify_runner(workspace: Path, runner: Path) -> None:
    if runner.resolve() != (workspace / RUNNER_WORKTREE_REL).resolve():
        raise ValueError("INVALID_GIT_STATE")
    common = Path(_git(runner, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (runner / common).resolve()
    expected_common = (workspace / RUNNER_COMMON_DIR).resolve()
    if common.resolve() != expected_common:
        raise ValueError("INVALID_GIT_STATE")
    if _git(runner, "rev-parse", "--abbrev-ref", "HEAD") != RUNNER_BRANCH:
        raise ValueError("INVALID_GIT_STATE")
    if _git(runner, "rev-parse", "HEAD") != RUNNER_HEAD:
        raise ValueError("INVALID_GIT_STATE")
    if _git(runner, "status", "--porcelain"):
        raise ValueError("INVALID_GIT_STATE")


def _verify_permission_rows(run_root: Path) -> None:
    requests = [
        row
        for row in _jsonl(run_root / "approval_requests.jsonl")
        if row.get("request_id") == APPROVAL_REQUEST_ID
    ]
    approvals = [
        row
        for row in _jsonl(run_root / "approvals.jsonl")
        if row.get("request_id") == APPROVAL_REQUEST_ID
    ]
    if len(requests) != 1 or len(approvals) != 1:
        raise ValueError("INVALID_PERMISSION")
    request, approval = requests[0], approvals[0]
    if canonical_sha256(request) != REQUEST_ROW_SHA256:
        raise ValueError("INVALID_PERMISSION")
    if canonical_sha256(approval) != APPROVAL_ROW_SHA256:
        raise ValueError("INVALID_PERMISSION")
    if (
        request.get("run_id") != RUN_ID
        or request.get("agent_id") != "codex-cto"
        or request.get("action") != "team.event.record"
        or request.get("affected_paths") != [PERMISSION_PATH]
        or request.get("evidence_refs") != list(ANCHOR_REFS)
        or approval.get("decision") != "approved_session"
        or approval.get("decided_by") != "founder"
    ):
        raise ValueError("INVALID_PERMISSION")
    forbidden = {"approved_once", "approved_until_expiry"}
    if any(row.get("decision") in forbidden for row in approvals):
        raise ValueError("INVALID_PERMISSION")


def resolve_frozen_run() -> FrozenRun:
    target = Path(_git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel"))
    common = Path(_git(target, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (target / common).resolve()
    workspace = common.resolve().parent.parent
    run_root = workspace / ".agent_runs" / RUN_ID
    runner = workspace / RUNNER_WORKTREE_REL
    spec_path = target / SPEC_REL
    lock_path = run_root / "prereg.lock"
    canonical_spec = run_root / "prereg.json"
    cases_path = target / "product_evals/spine_e2e_1/frozen_cases.json"
    bank_path = target / "product_evals/spine_e2e_1/provider_responses.json"
    evaluator_path = target / "product_evals/spine_e2e_1/protocol.py"
    lock = _json_file(lock_path)
    spec = _json_file(canonical_spec)
    if not isinstance(lock, dict) or not isinstance(spec, dict):
        raise ValueError("INVALID_BINDING")
    if lock.get("target_head") != _git(target, "rev-parse", "HEAD"):
        raise ValueError("INVALID_GIT_STATE")
    if _git(target, "status", "--porcelain"):
        raise ValueError("INVALID_GIT_STATE")
    if sha256_file(spec_path) != lock.get("spec_file_sha256"):
        raise ValueError("INVALID_BINDING")
    if sha256_file(canonical_spec) != lock.get("spec_sha256"):
        raise ValueError("INVALID_BINDING")
    mechanism = lock.get("mechanism_files")
    if not isinstance(mechanism, dict) or not mechanism:
        raise ValueError("INVALID_BINDING")
    observed = {
        str(relative): sha256_file(target / str(relative))
        for relative in sorted(mechanism)
    }
    if observed != mechanism:
        raise ValueError("INVALID_BINDING")
    _verify_runner(workspace, runner)
    _verify_permission_rows(run_root)
    bindings = {
        "schema": SCHEMA,
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "target_head": str(lock["target_head"]),
        "prereg_lock_sha256": sha256_file(lock_path),
        "spec_sha256": str(lock["spec_sha256"]),
        "mechanism_manifest_sha256": canonical_sha256(observed),
        "corpus_sha256": sha256_file(cases_path),
        "provider_bank_sha256": sha256_file(bank_path),
        "evaluator_sha256": sha256_file(evaluator_path),
        "runner_common_dir": RUNNER_COMMON_DIR,
        "runner_head": RUNNER_HEAD,
        "request_row_sha256": REQUEST_ROW_SHA256,
        "approval_row_sha256": APPROVAL_ROW_SHA256,
    }
    context = phase_context_sha256(bindings)
    frozen_context = spec.get("context_binding", {})
    if (
        not isinstance(frozen_context, dict)
        or frozen_context.get("algorithm") != "canonical_sha256(exact_14_key_mapping)"
        or frozen_context.get("keys") != list(bindings)
    ):
        raise ValueError("INVALID_CONTEXT")
    data_root = run_root / "evaluation"
    return FrozenRun(
        workspace=workspace,
        target=target,
        run_root=run_root,
        data_root=data_root,
        runner=runner,
        spec_path=spec_path,
        lock_path=lock_path,
        cases_path=cases_path,
        bank_path=bank_path,
        evaluator_path=evaluator_path,
        phase_ledger=data_root / "phases.jsonl",
        provider_ledger=data_root / "provider_calls.jsonl",
        context_bindings=bindings,
        context_sha256=context,
        spec=spec,
        lock=lock,
    )


def _phase_payload_path(run: FrozenRun, phase: str) -> Path:
    name = "adjudication_payload.json" if phase == "adjudicate" else f"{phase}.json"
    return run.data_root / "phases" / name


def _anchor_ref(phase: str) -> str:
    return f"evaluation/anchor_requests/{phase}.json"


def _phase_anchor(run: FrozenRun, phase: str) -> dict[str, Any]:
    path = run.run_root / _anchor_ref(phase)
    value = _json_file(path)
    record = _completed_record(run, phase)
    provider_rows = _provider_ledger_rows(run)
    phase_lines = run.phase_ledger.read_bytes().splitlines(keepends=True)
    prefix_sha = hashlib.sha256(b"".join(phase_lines[: record.ordinal + 1])).hexdigest()
    expected = {
        "schema_version": "spine-e2e-1-anchor-request-v1",
        "phase": phase,
        "phase_record_head_sha256": record.record_sha256,
        "phase_ledger_sha256": prefix_sha,
        "provider_ledger_head_sha256": provider_rows[-1]["record_sha256"],
        "provider_ledger_sha256": sha256_file(run.provider_ledger),
        "payload_sha256": record.payload_sha256,
        "boot_id_sha256": record.clock.boot_hash,
        "host_id_sha256": record.clock.host_hash,
        "context_sha256": run.context_sha256,
        "runner_common_dir": RUNNER_COMMON_DIR,
        "runner_branch": RUNNER_BRANCH,
        "runner_head": RUNNER_HEAD,
        "approval_request_id": APPROVAL_REQUEST_ID,
        "permission_action": "team.event.record",
        "request_row_sha256": REQUEST_ROW_SHA256,
        "approval_row_sha256": APPROVAL_ROW_SHA256,
    }
    if value != expected:
        raise ValueError("INVALID_RUNNER_ANCHOR")
    request_sha = canonical_sha256(value)
    expected_summary = f"SPINE_PHASE_ANCHOR phase={phase} request_sha256={request_sha}"
    matches = []
    for row in _jsonl(run.run_root / "agent_events.jsonl"):
        event_fields = {
            "ts",
            "type",
            "agent_id",
            "task_id",
            "summary",
            "artifact",
            "stream_file",
            "permission_action",
            "approval_request_id",
            "evidence_refs",
            "source_decision_type",
        }
        if (
            set(row) == event_fields
            and isinstance(row.get("ts"), str)
            and bool(row["ts"])
            and row.get("type") == "EVIDENCE_APPENDED"
            and row.get("agent_id") == "codex-cto"
            and row.get("task_id") is None
            and row.get("summary") == expected_summary
            and row.get("artifact") == _anchor_ref(phase)
            and row.get("stream_file") is None
            and row.get("evidence_refs") == [_anchor_ref(phase)]
            and row.get("approval_request_id") == APPROVAL_REQUEST_ID
            and row.get("permission_action") == "team.event.record"
            and row.get("source_decision_type") == "founder_authorization"
        ):
            matches.append(row)
    if len(matches) != 1:
        raise ValueError("INVALID_RUNNER_ANCHOR")
    _verify_permission_rows(run.run_root)
    _verify_runner(run.workspace, run.runner)
    return value


def _completed_record(run: FrozenRun, phase: str):
    records = read_phases(run.phase_ledger, run.context_sha256)
    matches = [record for record in records if record.phase == f"{phase}_completed"]
    if len(matches) != 1:
        raise ValueError("INVALID_PARTIAL_PHASE")
    return matches[0]


def _load_phase(run: FrozenRun, phase: str) -> dict[str, Any]:
    value = _json_file(_phase_payload_path(run, phase))
    if not isinstance(value, dict) or canonical_sha256(value) != _completed_record(run, phase).payload_sha256:
        raise ValueError("INVALID_BINDING")
    return value


def _prior_anchor(run: FrozenRun, phase: str) -> None:
    index = PHASES.index(phase)
    if index:
        _phase_anchor(run, PHASES[index - 1])


def _cases(run: FrozenRun) -> list[dict[str, Any]]:
    value = _json_file(run.cases_path)
    if not isinstance(value, dict) or set(value) != {"cases"} or not isinstance(value["cases"], list):
        raise ValueError("INVALID_BINDING")
    return value["cases"]


def _provider(run: FrozenRun) -> FrozenProviderServer:
    server = FrozenProviderServer(
        run.bank_path, ledger_path=run.provider_ledger, context_sha256=run.context_sha256
    )
    server.start()
    configure_provider_environment(server.base_url)
    return server


def _open_interrupted(run: FrozenRun, prepared: Mapping[str, Any], case_id: str):
    item = prepared["cases"][case_id]
    paths = item["paths"]["interrupted"]
    return open_application(Path(paths["database"]), Path(paths["workspace"]))


def _case_evidence(run: FrozenRun, prepared: Mapping[str, Any], case_id: str, app: Any) -> dict[str, Any]:
    item = prepared["cases"][case_id]
    return public_evidence(
        app,
        item["task_ids"]["interrupted"],
        Path(item["paths"]["interrupted"]["workspace"]),
        run.provider_ledger,
    )


def _execute_phase(run: FrozenRun, phase: str) -> dict[str, Any]:
    cases = _cases(run)
    if phase == "prepare":
        server = _provider(run)
        try:
            results = {
                case["case_id"]: prepare_case(
                    run.data_root, case, server.base_url, run.provider_ledger
                )
                for case in cases
            }
        finally:
            server.close(validate_counts=True)
        return {"schema_version": "spine-e2e-1-prepare-v1", "cases": results}
    prepared = _load_phase(run, "prepare")
    server = _provider(run)
    try:
        results: dict[str, Any] = {}
        for case in cases:
            case_id = case["case_id"]
            app = _open_interrupted(run, prepared, case_id)
            task_id = prepared["cases"][case_id]["task_ids"]["interrupted"]
            def reader(application: Any, ignored: str, cid: str = case_id) -> dict[str, Any]:
                return _case_evidence(run, prepared, cid, application)
            if phase == "interrupt_batch":
                result = interrupt_batch(app, (task_id,), reader)[0]
            elif phase == "probe_active_lease":
                result = probe_active_lease(app, (task_id,), reader)[0]
                result = {**result, "denial_type": "ConcurrentWriteError"}
            elif phase == "resume":
                result = resume_spine(app, (task_id,), reader)[0]
            else:
                raise ValueError("INVALID_INTERNAL_ERROR")
            results[case_id] = result
        return {"schema_version": f"spine-e2e-1-{phase}-v1", "cases": results}
    finally:
        server.close(validate_counts=True)


def _phase_gates(phase: str) -> tuple[ElapsedGate, ...]:
    if phase == "probe_active_lease":
        return (ElapsedGate("interrupt_batch", "started", max_seconds=60),)
    if phase == "resume":
        return (
            ElapsedGate("interrupt_batch", "completed", min_seconds=360),
            ElapsedGate("prepare", "started", max_seconds=1800),
        )
    return ()


def _run_phase(run: FrozenRun, phase: str) -> None:
    if phase not in {"prepare", "interrupt_batch", "probe_active_lease", "resume", "adjudicate"}:
        raise ValueError("INVALID_INTERNAL_ERROR")
    _prior_anchor(run, phase)
    output = _build_adjudication_payload(run) if phase == "adjudicate" else None
    if phase == "probe_active_lease":
        gates = (ElapsedGate("interrupt_batch", "started", max_seconds=60),)
    elif phase == "resume":
        gates = (
            ElapsedGate("interrupt_batch", "completed", min_seconds=360),
            ElapsedGate("prepare", "started", max_seconds=1800),
        )
    else:
        gates = ()
    with phase_guard(
        run.phase_ledger,
        phase,
        _PENDING,
        expected_context_sha256=run.context_sha256,
        elapsed_gates=gates,
        require_bound_payload=True,
    ) as guard:
        if output is None:
            output = _execute_phase(run, phase)
        payload_sha = write_json_once(_phase_payload_path(run, phase), output)
        guard.bind_payload(payload_sha)


def _provider_counts(run: FrozenRun) -> tuple[dict[str, int], int]:
    bank = _json_file(run.bank_path)
    rows = _provider_ledger_rows(run)
    accepted = {
        entry["case_id"]: sum(
            row.get("accepted") is True and row.get("request_digest") == entry["digest"]
            for row in rows
        )
        for entry in bank["entries"]
    }
    rejected = sum(row.get("accepted") is not True for row in rows)
    return accepted, rejected


def _provider_ledger_rows(run: FrozenRun) -> list[dict[str, Any]]:
    rows = _jsonl(run.provider_ledger)
    fields = {
        "schema_version",
        "ordinal",
        "request_digest",
        "accepted",
        "reason",
        "chain_context_sha256",
        "previous_record_sha256",
        "record_sha256",
    }
    previous = hashlib.sha256(
        b"agent-os-provider-call-ledger-v1\0" + bytes.fromhex(run.context_sha256)
    ).hexdigest()
    rejected_reasons = {
        "METHOD_NOT_ALLOWED",
        "PATH_NOT_FOUND",
        "UNAUTHORIZED",
        "UNSUPPORTED_MEDIA_TYPE",
        "INVALID_JSON",
        "UNKNOWN_REQUEST_DIGEST",
        "EXPECTED_CALLS_EXCEEDED",
    }
    for ordinal, row in enumerate(rows):
        unsigned = {key: item for key, item in row.items() if key != "record_sha256"}
        if (
            set(row) != fields
            or row.get("schema_version") != "agent-os-provider-call-ledger-v1"
            or row.get("ordinal") != ordinal
            or row.get("chain_context_sha256") != run.context_sha256
            or row.get("previous_record_sha256") != previous
            or type(row.get("accepted")) is not bool
            or not isinstance(row.get("reason"), str)
            or canonical_sha256(unsigned) != row.get("record_sha256")
            or (row.get("accepted") is True) != (row.get("reason") == "ACCEPTED")
            or (
                row.get("accepted") is False
                and row.get("reason") not in rejected_reasons
            )
        ):
            raise ValueError("INVALID_PROVIDER")
        previous = row["record_sha256"]
    return rows


def _unexpected_events(*evidence_values: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    policy: list[Any] = []
    correction: list[Any] = []
    correction_types = {
        "COMPENSATION_STARTED",
        "ACTION_COMPENSATED",
        "COMPENSATION_FAILED",
        "COMPENSATION_BLOCKED",
    }
    for evidence in evidence_values:
        for event in evidence["projection"]["task"]["events"]:
            event_type = event.get("event_type")
            if event_type == "CORRECTION_WRITTEN":
                correction.append(event)
            elif event_type in correction_types:
                correction.append(event)
            elif event_type == "POLICY_DECIDED":
                verdict = event.get("payload", {}).get("decision", {}).get("verdict")
                if verdict != "ALLOW":
                    policy.append(event)
    return policy, correction


def _snapshot(ev: Mapping[str, Any], case_id: str, workspace: Path, provider_count: int, *, terminal: bool, probe: bool = False) -> dict[str, Any]:
    task = ev["projection"]["task"]
    run = task["run"]
    events = task["events"]
    receipts = []
    completed = []
    pytest_exit = 1
    for event in events:
        payload = event.get("payload", {})
        if event.get("event_type") == "NODE_COMPLETED":
            completed.append(payload.get("node_id"))
            if payload.get("node_id") == "tests":
                pytest_exit = int(payload.get("output", {}).get("exit_code", 1))
        if event.get("event_type") == "ACTION_RECEIPT_RECORDED":
            receipt = payload.get("receipt", {})
            if receipt.get("connector_id") == "workspace.apply_patch":
                receipts.append({
                    "capability_id": "workspace.apply_patch",
                    "idempotency_key": receipt["idempotency_key"],
                })
    common = {
        "case_id": case_id,
        "task_sequence": task["sequence"],
        "task_status": task["status"],
        "run_status": run["status"],
        "workflow_sha256": run["workflow_digest"],
        "target_sha256": sha256_file(workspace / "subject.py"),
        "apply_receipts": receipts,
        "lease_fence": run["lease_fence"],
        "evidence_sha256": canonical_sha256(ev["projection"]),
        "workspace_tree_sha256": ev["workspace_tree_sha256"],
        "provider_request_count": provider_count,
    }
    if not terminal:
        common["normalized_projection"] = {
            "task_status": common["task_status"],
            "run_status": common["run_status"],
            "target_sha256": common["target_sha256"],
        }
        if probe:
            common["denial_type"] = "ConcurrentWriteError"
        return common
    outcome = task["observed_outcome"]
    common.update({
        "outcome_status": outcome["status"],
        "outcome_score": outcome["score"],
        "evaluator_type": outcome["evaluator_type"],
        "evaluator_version": outcome["evaluator_version"],
        "completed_node_ids": completed,
        "pytest_exit_code": pytest_exit,
    })
    common["normalized_projection"] = {
        "task_status": common["task_status"],
        "run_status": common["run_status"],
        "outcome_status": common["outcome_status"],
        "completed_node_ids": completed,
        "target_sha256": common["target_sha256"],
    }
    return common


def _build_adjudication_payload(run: FrozenRun) -> dict[str, Any]:
    prepared = _load_phase(run, "prepare")
    interrupted = _load_phase(run, "interrupt_batch")
    probed = _load_phase(run, "probe_active_lease")
    resumed = _load_phase(run, "resume")
    anchors = {phase: _phase_anchor(run, phase) for phase in PHASES[:-1]}
    counts, rejected_attempts = _provider_counts(run)
    cases_out: dict[str, Any] = {}
    cases = _cases(run)
    expected_workflows: dict[str, str] = {}
    observed_workflows: dict[str, str] = {}
    for case in cases:
        case_id = case["case_id"]
        paths = prepared["cases"][case_id]["paths"]
        uninterrupted = _snapshot(
            prepared["cases"][case_id]["public_evidence"]["uninterrupted"],
            case_id,
            Path(paths["uninterrupted"]["workspace"]),
            counts[case_id], terminal=True,
        )
        interrupted_snapshot = _snapshot(
            interrupted["cases"][case_id], case_id,
            Path(paths["interrupted"]["workspace"]), counts[case_id], terminal=False,
        )
        probe_snapshot = _snapshot(
            probed["cases"][case_id], case_id,
            Path(paths["interrupted"]["workspace"]), counts[case_id], terminal=False, probe=True,
        )
        resumed_evidence = resumed["cases"][case_id]["resumed_terminal"]
        replay_evidence = resumed["cases"][case_id]["terminal_replay"]
        terminal = _snapshot(
            resumed_evidence, case_id,
            Path(paths["interrupted"]["workspace"]), counts[case_id], terminal=True,
        )
        replay = _snapshot(
            replay_evidence, case_id,
            Path(paths["interrupted"]["workspace"]), counts[case_id], terminal=True,
        )
        expected_workflow = prepared["cases"][case_id][
            "expected_workflow_sha256"
        ]
        expected_workflows[case_id] = expected_workflow
        observed_workflows[case_id] = terminal["workflow_sha256"]
        unexpected_policy, unexpected_correction = _unexpected_events(
            prepared["cases"][case_id]["public_evidence"]["uninterrupted"],
            interrupted["cases"][case_id],
            probed["cases"][case_id],
            resumed_evidence,
            replay_evidence,
        )
        cases_out[case_id] = {
            "expected_final_target_sha256": hashlib.sha256(case["patched_content"].encode()).hexdigest(),
            "expected_workflow_sha256": expected_workflow,
            "provider_rejected_attempt_count": rejected_attempts,
            "unexpected_policy_events": unexpected_policy,
            "unexpected_correction_events": unexpected_correction,
            "uninterrupted_terminal": uninterrupted,
            "interrupted_after_apply": interrupted_snapshot,
            "probe": probe_snapshot,
            "resumed_terminal": terminal,
            "terminal_replay": replay,
        }
    expected_bindings = {
        "case_manifest_sha256": run.context_bindings["corpus_sha256"],
        "workflow_sha256": canonical_sha256(expected_workflows),
        "evaluator_sha256": run.context_bindings["evaluator_sha256"],
        "provider_bank_sha256": run.context_bindings["provider_bank_sha256"],
    }
    observed_bindings = {
        **expected_bindings,
        "workflow_sha256": canonical_sha256(observed_workflows),
    }
    records = read_phases(run.phase_ledger, run.context_sha256)
    boot = records[0].clock.boot_hash
    return {
        "schema_version": "spine-e2e-1-adjudication-input-v1",
        "expected_case_ids": [case["case_id"] for case in cases],
        "bindings": {"expected": expected_bindings, "observed": observed_bindings},
        "phases": {
            "expected_order": list(PHASES),
            "completed": list(PHASES[:-1]),
            "context_sha256": run.context_sha256,
            "boot_id_sha256": boot,
            "runner_anchors": {
                phase: {
                    "context_sha256": anchor["context_sha256"],
                    "boot_id_sha256": anchor["boot_id_sha256"],
                    "anchor_sha256": canonical_sha256(anchor),
                }
                for phase, anchor in anchors.items()
            },
        },
        "recovery_configuration": [
            {"phase": "probe_active_lease", "recover_stale_lease": False},
            {"phase": "resume", "recover_stale_lease": False},
            {"phase": "terminal_replay", "recover_stale_lease": False},
        ],
        "cases": cases_out,
    }


def _record_runner_anchor(run: FrozenRun) -> None:
    records = read_phases(run.phase_ledger, run.context_sha256)
    completed = [record.phase.removesuffix("_completed") for record in records if record.phase.endswith("_completed")]
    unanchored = [phase for phase in completed if not (run.run_root / _anchor_ref(phase)).exists()]
    if len(unanchored) != 1 or unanchored[0] != completed[-1]:
        raise ValueError("INVALID_RUNNER_ANCHOR")
    phase = unanchored[0]
    record = _completed_record(run, phase)
    provider_rows = _provider_ledger_rows(run)
    payload = {
        "schema_version": "spine-e2e-1-anchor-request-v1",
        "phase": phase,
        "phase_record_head_sha256": record.record_sha256,
        "phase_ledger_sha256": sha256_file(run.phase_ledger),
        "provider_ledger_head_sha256": provider_rows[-1]["record_sha256"],
        "provider_ledger_sha256": sha256_file(run.provider_ledger),
        "payload_sha256": record.payload_sha256,
        "boot_id_sha256": record.clock.boot_hash,
        "host_id_sha256": record.clock.host_hash,
        "context_sha256": run.context_sha256,
        "runner_common_dir": RUNNER_COMMON_DIR,
        "runner_branch": RUNNER_BRANCH,
        "runner_head": RUNNER_HEAD,
        "approval_request_id": APPROVAL_REQUEST_ID,
        "permission_action": "team.event.record",
        "request_row_sha256": REQUEST_ROW_SHA256,
        "approval_row_sha256": APPROVAL_ROW_SHA256,
    }
    relative = _anchor_ref(phase)
    request_sha = write_json_once(run.run_root / relative, payload)
    summary = f"SPINE_PHASE_ANCHOR phase={phase} request_sha256={request_sha}"
    command = (
        sys.executable, "-m", "agent_workflow_runner.cli", "team", "event",
        "--workspace-root", str(run.workspace), "--run-id", RUN_ID,
        "--type", "EVIDENCE_APPENDED", "--agent-id", "codex-cto",
        "--summary", summary, "--artifact", relative, "--evidence-ref", relative,
        "--approval-request-id", APPROVAL_REQUEST_ID,
    )
    env_command = ("env", f"PYTHONPATH={run.runner / 'src'}", *command)
    subprocess.run(env_command, cwd=run.runner, check=True)
    _phase_anchor(run, phase)


def _finalize_result(run: FrozenRun) -> None:
    records = read_phases(run.phase_ledger, run.context_sha256)
    expected = [f"{phase}_{suffix}" for phase in PHASES for suffix in ("started", "completed")]
    if [record.phase for record in records] != expected:
        raise ValueError("INVALID_PARTIAL_PHASE")
    runner_anchors = {phase: _phase_anchor(run, phase) for phase in PHASES}
    adjudication_payload_path = run.data_root / "phases/adjudication_payload.json"
    payload = _json_file(adjudication_payload_path)
    if not isinstance(payload, dict) or canonical_sha256(payload) != _completed_record(run, "adjudicate").payload_sha256:
        raise ValueError("INVALID_BINDING")
    adjudication = adjudicate_spine(payload)
    result = {
        **adjudication,
        "schema_version": "spine-e2e-1-result-v1",
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "spec_sha256": run.context_bindings["spec_sha256"],
        "prereg_lock_sha256": run.context_bindings["prereg_lock_sha256"],
        "context_sha256": run.context_sha256,
        "adjudication_payload_sha256": canonical_sha256(payload),
        "phase_ledger_sha256": sha256_file(run.phase_ledger),
        "provider_ledger_sha256": sha256_file(run.provider_ledger),
        "runner_anchors": {phase: canonical_sha256(anchor) for phase, anchor in runner_anchors.items()},
        "adjudication_schema_version": adjudication["schema_version"],
    }
    write_json_once(run.data_root / "result.json", result)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spine-e2e-1")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in (
        "prepare", "interrupt-batch", "probe-active-lease", "resume", "adjudicate",
        "record-runner-anchor", "finalize-result",
    ):
        sub.add_parser(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    command = _parser().parse_args(argv).command
    run = resolve_frozen_run()
    if command == "record-runner-anchor":
        _record_runner_anchor(run)
    elif command == "finalize-result":
        _finalize_result(run)
    else:
        phase = command.replace("-", "_")
        _run_phase(run, phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
