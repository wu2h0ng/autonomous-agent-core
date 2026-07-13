"""Fail-closed formal CLI for the runner-contract-qualified SPINE successor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime  # noqa: F401 - public test/fixture clock constructor
from pathlib import Path
from typing import Any, Mapping, Sequence

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
for _source_root in (
    _BOOTSTRAP_ROOT / "packages/os_core/src",
    _BOOTSTRAP_ROOT / "packages/contracts/src",
):
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from product_evals.common.artifacts import (  # noqa: E402
    SCHEMA,
    canonical_sha256,
    phase_context_sha256,
    phase_guard,
    read_phases,
    sha256_file,
    write_json_once,
)
from product_evals.common.authority_binding import (  # noqa: E402
    AuthorityBinding,
    verify_authority_binding,
)
from product_evals.common.instrument_qualification import (  # noqa: E402
    identity_bound_provider_server,
)
from product_evals.common.json_schema_contract import (  # noqa: E402
    canonical_schema_sha256,
    validate_closed_record,
)
from product_evals.common.provider_bank import FrozenProviderServer  # noqa: E402

from .identity import IDENTITY  # noqa: E402
from .prefreeze import (  # noqa: E402
    PERMISSION_ACTION,
    PERMISSION_PATH,
    validate_prefreeze_permission,
)
from .qualification import verify_combined_qualification_receipt  # noqa: E402

RUN_ID = IDENTITY.run_id
EXPERIMENT_ID = IDENTITY.experiment_id
RUNNER_HEAD = "3a3224a7af7da724d8b6ec82d34ed47d938620e4"
RUNNER_BRANCH = "codex/team-event-contract-v1-20260713"
RUNNER_WORKTREE_REL = (
    "ai-agent-engineering-workflow/.worktrees/team-event-contract-v1-20260713"
)
RUNNER_COMMON_DIR = "ai-agent-engineering-workflow/.git"
SPEC_REL = f"docs/research/{IDENTITY.experiment_id}-preregistration-spec.yaml"
PHASES = ("prepare", "interrupt_batch", "probe_active_lease", "resume", "adjudicate")
ANCHOR_REFS = tuple(f"evaluation/anchor_requests/{phase}.json" for phase in PHASES)
_PENDING = hashlib.sha256(
    f"{IDENTITY.experiment_id}-PAYLOAD-PENDING-v1".encode()
).hexdigest()
TARGET_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = TARGET_ROOT.parents[2]
RUNNER_ROOT = WORKSPACE_ROOT / RUNNER_WORKTREE_REL
PRODUCT_INTERPRETER = (TARGET_ROOT / ".venv/bin/python").resolve()
RUNNER_INTERPRETER = Path(
    os.path.abspath(WORKSPACE_ROOT / "ai-agent-engineering-workflow/.venv/bin/python")
)
PRODUCT_IMPORT_CHECK = (
    "import sys; "
    "sys.path[:0]=['packages/os_core/src','packages/contracts/src']; "
    "import agent_os_core, agent_os_contracts"
)


@dataclass(frozen=True)
class _TimingGate:
    """Phase guard timing input with explicit test-facing names."""

    anchor_phase: str
    anchor_record: str
    min_seconds: float | None = None
    max_seconds: float | None = None

    @property
    def start_phase(self) -> str:
        return self.anchor_phase

    @property
    def start_state(self) -> str:
        return self.anchor_record


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
    template_path: Path
    qualification_receipt_path: Path
    runner_schema_path: Path
    qualification_scratch_root: Path
    evaluator_path: Path
    authority_source_path: Path
    phase_ledger: Path
    provider_ledger: Path
    event_ledger: Path
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
    return _json_no_duplicates(Path(path).read_bytes())


def _jsonl(path: Path) -> list[dict[str, Any]]:
    raw = Path(path).read_bytes()
    if not raw or not raw.endswith(b"\n") or raw.startswith(b"\n") or b"\n\n" in raw:
        raise ValueError(f"invalid JSONL framing: {Path(path).name}")
    rows = [_json_no_duplicates(line) for line in raw.splitlines()]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"invalid JSONL row: {Path(path).name}")
    return rows


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ("git", *args), cwd=path, text=True, stderr=subprocess.DEVNULL
    ).strip()


def _verify_runner(workspace: Path, runner: Path) -> None:
    if Path(runner).resolve() != (Path(workspace) / RUNNER_WORKTREE_REL).resolve():
        raise ValueError("INVALID_GIT_STATE")
    common = Path(_git(runner, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (Path(runner) / common).resolve()
    if common.resolve() != (Path(workspace) / RUNNER_COMMON_DIR).resolve():
        raise ValueError("INVALID_GIT_STATE")
    if _git(runner, "rev-parse", "--abbrev-ref", "HEAD") != RUNNER_BRANCH:
        raise ValueError("INVALID_GIT_STATE")
    if _git(runner, "rev-parse", "HEAD") != RUNNER_HEAD:
        raise ValueError("INVALID_GIT_STATE")
    if _git(runner, "status", "--porcelain"):
        raise ValueError("INVALID_GIT_STATE")


def _authority_binding(run: FrozenRun) -> AuthorityBinding:
    binding = verify_authority_binding(
        run.run_root,
        run_id=RUN_ID,
        action=PERMISSION_ACTION,
        affected_path=PERMISSION_PATH,
    )
    if (
        binding.decision != "approved_session"
        or binding.decided_by != "founder"
        or binding.evidence_refs != ANCHOR_REFS
    ):
        raise ValueError("INVALID_AUTHORITY_BINDING")
    return binding


def _verify_frozen_permission_binding(
    spec: Mapping[str, Any], authority: AuthorityBinding
) -> None:
    """Bind frozen permission bytes to the one currently verified authority."""

    validate_prefreeze_permission(spec.get("permission_binding"), authority)


def evaluation_genesis_preflight(run: FrozenRun) -> None:
    """Requalify both producers before any dependency or formal output."""

    verify_combined_qualification_receipt(
        IDENTITY,
        template_path=run.template_path,
        bank_path=run.bank_path,
        receipt_path=run.qualification_receipt_path,
        formal_phase_ledger=run.phase_ledger,
        formal_provider_ledger=run.provider_ledger,
        formal_event_ledger=run.event_ledger,
        runner_worktree=run.runner,
        runner_python=RUNNER_INTERPRETER,
        expected_runner_branch=RUNNER_BRANCH,
        expected_runner_head=RUNNER_HEAD,
        runner_schema_path=run.runner_schema_path,
        scratch_root=run.qualification_scratch_root,
        consumer_source_path=Path(__file__).resolve().parents[1]
        / "common/json_schema_contract.py",
        authority_source_path=Path(__file__).resolve().parents[1]
        / "common/authority_binding.py",
    )
    if (
        run.phase_ledger.exists()
        or run.provider_ledger.exists()
        or run.event_ledger.exists()
    ):
        raise ValueError("INVALID_EVALUATION_GENESIS")
    commands = (
        (str(PRODUCT_INTERPRETER), "-c", PRODUCT_IMPORT_CHECK),
        (str(RUNNER_INTERPRETER), "-c", "import yaml"),
    )
    try:
        for command in commands:
            subprocess.run(command, check=True, cwd=TARGET_ROOT)
    except (OSError, subprocess.CalledProcessError) as exc:
        if (
            run.phase_ledger.exists()
            or run.provider_ledger.exists()
            or run.event_ledger.exists()
        ):
            raise ValueError("INVALID_EVALUATION_GENESIS") from exc
        raise ValueError("INVALID_DEPENDENCY_PREFLIGHT") from exc


def _context_algorithm(bindings: Mapping[str, str]) -> str:
    return f"canonical_sha256(exact_{len(bindings)}_key_mapping)"


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
    evaluation_root = target / "product_evals" / IDENTITY.module_slug
    cases_path = evaluation_root / "frozen_cases.json"
    bank_path = evaluation_root / "provider_responses.json"
    template_path = evaluation_root / "request_template.json"
    receipt_path = evaluation_root / "instrument_qualification_receipt.json"
    schema_path = evaluation_root / "runner_team_event_schema.json"
    evaluator_path = evaluation_root / "protocol.py"
    authority_source_path = target / "product_evals/common/authority_binding.py"
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
    authority = verify_authority_binding(
        run_root,
        run_id=RUN_ID,
        action=PERMISSION_ACTION,
        affected_path=PERMISSION_PATH,
    )
    _verify_frozen_permission_binding(spec, authority)
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
        "provider_template_sha256": sha256_file(template_path),
        "qualification_receipt_sha256": sha256_file(receipt_path),
        "runner_schema_sha256": canonical_schema_sha256(_json_file(schema_path)),
        "evaluator_sha256": sha256_file(evaluator_path),
        "runner_common_dir": RUNNER_COMMON_DIR,
        "runner_head": RUNNER_HEAD,
        "request_row_sha256": authority.request_sha256,
        "approval_row_sha256": authority.approval_sha256,
    }
    context = phase_context_sha256(bindings)
    frozen_context = spec.get("context_binding", {})
    if (
        not isinstance(frozen_context, dict)
        or frozen_context.get("algorithm") != _context_algorithm(bindings)
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
        template_path=template_path,
        qualification_receipt_path=receipt_path,
        runner_schema_path=schema_path,
        qualification_scratch_root=workspace / ".agent_runs/.qualification" / RUN_ID,
        evaluator_path=evaluator_path,
        authority_source_path=authority_source_path,
        phase_ledger=data_root / "phases.jsonl",
        provider_ledger=data_root / "provider_calls.jsonl",
        event_ledger=run_root / "agent_events.jsonl",
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


def _completed_record(run: FrozenRun, phase: str) -> Any:
    records = read_phases(run.phase_ledger, run.context_sha256)
    matches = [record for record in records if record.phase == f"{phase}_completed"]
    if len(matches) != 1:
        raise ValueError("INVALID_PARTIAL_PHASE")
    return matches[0]


def _provider_ledger_rows(run: FrozenRun) -> list[dict[str, Any]]:
    rows = _jsonl(run.provider_ledger)
    if not rows:
        raise ValueError("INVALID_PROVIDER")
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
    rejected_reasons = {
        "METHOD_NOT_ALLOWED",
        "PATH_NOT_FOUND",
        "UNAUTHORIZED",
        "UNSUPPORTED_MEDIA_TYPE",
        "INVALID_JSON",
        "UNKNOWN_REQUEST_DIGEST",
        "EXPECTED_CALLS_EXCEEDED",
    }
    previous = hashlib.sha256(
        b"agent-os-provider-call-ledger-v1\0" + bytes.fromhex(run.context_sha256)
    ).hexdigest()
    for ordinal, row in enumerate(rows):
        unsigned = {key: value for key, value in row.items() if key != "record_sha256"}
        if (
            row.keys() != fields
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
        previous = str(row["record_sha256"])
    return rows


def _expected_anchor(
    run: FrozenRun,
    phase: str,
    binding: AuthorityBinding | None = None,
) -> dict[str, Any]:
    authority = binding if binding is not None else _authority_binding(run)
    record = _completed_record(run, phase)
    provider_rows = _provider_ledger_rows(run)
    phase_lines = run.phase_ledger.read_bytes().splitlines(keepends=True)
    ordinal = getattr(record, "ordinal", len(phase_lines) - 1)
    prefix_sha = hashlib.sha256(b"".join(phase_lines[: ordinal + 1])).hexdigest()
    return {
        "schema_version": IDENTITY.schema("anchor-request"),
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
        "approval_request_id": authority.request_id,
        "permission_action": authority.action,
        "request_row_sha256": authority.request_sha256,
        "approval_row_sha256": authority.approval_sha256,
        "source_decision_id": authority.source_decision_id,
        "source_goal_id": authority.source_goal_id,
        "source_decision_type": authority.source_decision_type,
    }


def _phase_anchor(run: FrozenRun, phase: str) -> dict[str, Any]:
    try:
        binding = _authority_binding(run)
        value = _json_file(run.run_root / _anchor_ref(phase))
        expected = _expected_anchor(run, phase, binding)
        if value != expected:
            raise ValueError("anchor request mismatch")
        request_sha = canonical_sha256(value)
        expected_summary = (
            f"SPINE_PHASE_ANCHOR phase={phase} request_sha256={request_sha}"
        )
        schema = _json_file(run.runner_schema_path)
        matches: list[dict[str, Any]] = []
        for row in _jsonl(run.event_ledger):
            validate_closed_record(row, schema)
            if (
                row.get("type") == "EVIDENCE_APPENDED"
                and row.get("agent_id") == "codex-cto"
                and row.get("task_id") is None
                and row.get("summary") == expected_summary
                and row.get("artifact") == _anchor_ref(phase)
                and row.get("stream_file") is None
                and row.get("evidence_refs") == [_anchor_ref(phase)]
                and row.get("approval_request_id") == binding.request_id
                and row.get("permission_action") == binding.action
                and row.get("source_decision_id") == binding.source_decision_id
                and row.get("source_goal_id") == binding.source_goal_id
                and row.get("source_decision_type") == binding.source_decision_type
            ):
                matches.append(row)
        if len(matches) != 1:
            raise ValueError("anchor event cardinality")
        if _authority_binding(run) != binding:
            raise ValueError("authority drift")
        _verify_runner(run.workspace, run.runner)
        return value
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "INVALID_RUNNER_ANCHOR":
            raise
        raise ValueError("INVALID_RUNNER_ANCHOR") from exc


def _prior_anchor(run: FrozenRun, phase: str) -> None:
    index = PHASES.index(phase)
    if index:
        _phase_anchor(run, PHASES[index - 1])


def _load_phase(run: FrozenRun, phase: str) -> dict[str, Any]:
    value = _json_file(_phase_payload_path(run, phase))
    if (
        not isinstance(value, dict)
        or canonical_sha256(value) != _completed_record(run, phase).payload_sha256
    ):
        raise ValueError("INVALID_BINDING")
    return value


def _cases(run: FrozenRun) -> list[dict[str, Any]]:
    value = _json_file(run.cases_path)
    if (
        not isinstance(value, dict)
        or list(value) != ["cases"]
        or not isinstance(value["cases"], list)
    ):
        raise ValueError("INVALID_BINDING")
    return value["cases"]


def _provider(run: FrozenRun) -> FrozenProviderServer:
    from .public_surface import configure_provider_environment

    server = identity_bound_provider_server(
        IDENTITY,
        run.bank_path,
        ledger_path=run.provider_ledger,
        context_sha256=run.context_sha256,
    )
    server.start()
    configure_provider_environment(server.base_url)
    return server


def _execute_phase(run: FrozenRun, phase: str) -> dict[str, Any]:
    from .protocol import interrupt_batch, probe_active_lease, resume_spine
    from .public_surface import open_application, prepare_case, public_evidence

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
        return {"schema_version": IDENTITY.schema("prepare"), "cases": results}
    prepared = _load_phase(run, "prepare")
    server = _provider(run)
    try:
        results: dict[str, Any] = {}
        for case in cases:
            case_id = case["case_id"]
            item = prepared["cases"][case_id]
            paths = item["paths"]["interrupted"]
            app = open_application(Path(paths["database"]), Path(paths["workspace"]))
            task_id = item["task_ids"]["interrupted"]

            def reader(application: Any, ignored: str) -> dict[str, Any]:
                return public_evidence(
                    application,
                    task_id,
                    Path(paths["workspace"]),
                    run.provider_ledger,
                )

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
        return {"schema_version": IDENTITY.schema(phase), "cases": results}
    finally:
        server.close(validate_counts=True)


def _phase_gates(phase: str) -> tuple[_TimingGate, ...]:
    if phase == "probe_active_lease":
        return (_TimingGate("interrupt_batch", "started", max_seconds=60),)
    if phase == "resume":
        return (
            _TimingGate("interrupt_batch", "completed", min_seconds=360),
            _TimingGate("prepare", "started", max_seconds=1800),
        )
    return ()


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


def _unexpected_events(
    *evidence_values: Mapping[str, Any],
) -> tuple[list[Any], list[Any]]:
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
            if event_type == "CORRECTION_WRITTEN" or event_type in correction_types:
                correction.append(event)
            elif event_type == "POLICY_DECIDED":
                verdict = event.get("payload", {}).get("decision", {}).get("verdict")
                if verdict != "ALLOW":
                    policy.append(event)
    return policy, correction


def _snapshot(
    evidence: Mapping[str, Any],
    case_id: str,
    workspace: Path,
    provider_count: int,
    *,
    terminal: bool,
    probe: bool = False,
) -> dict[str, Any]:
    task = evidence["projection"]["task"]
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
                receipts.append(
                    {
                        "capability_id": "workspace.apply_patch",
                        "idempotency_key": receipt["idempotency_key"],
                    }
                )
    common = {
        "case_id": case_id,
        "task_sequence": task["sequence"],
        "task_status": task["status"],
        "run_status": run["status"],
        "workflow_sha256": run["workflow_digest"],
        "target_sha256": sha256_file(workspace / "subject.py"),
        "apply_receipts": receipts,
        "lease_fence": run["lease_fence"],
        "evidence_sha256": canonical_sha256(evidence["projection"]),
        "workspace_tree_sha256": evidence["workspace_tree_sha256"],
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
    common.update(
        {
            "outcome_status": outcome["status"],
            "outcome_score": outcome["score"],
            "evaluator_type": outcome["evaluator_type"],
            "evaluator_version": outcome["evaluator_version"],
            "completed_node_ids": completed,
            "pytest_exit_code": pytest_exit,
        }
    )
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
            counts[case_id],
            terminal=True,
        )
        interrupted_snapshot = _snapshot(
            interrupted["cases"][case_id],
            case_id,
            Path(paths["interrupted"]["workspace"]),
            counts[case_id],
            terminal=False,
        )
        probe_snapshot = _snapshot(
            probed["cases"][case_id],
            case_id,
            Path(paths["interrupted"]["workspace"]),
            counts[case_id],
            terminal=False,
            probe=True,
        )
        resumed_evidence = resumed["cases"][case_id]["resumed_terminal"]
        replay_evidence = resumed["cases"][case_id]["terminal_replay"]
        terminal = _snapshot(
            resumed_evidence,
            case_id,
            Path(paths["interrupted"]["workspace"]),
            counts[case_id],
            terminal=True,
        )
        replay = _snapshot(
            replay_evidence,
            case_id,
            Path(paths["interrupted"]["workspace"]),
            counts[case_id],
            terminal=True,
        )
        expected_workflow = prepared["cases"][case_id]["expected_workflow_sha256"]
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
            "expected_final_target_sha256": hashlib.sha256(
                case["patched_content"].encode()
            ).hexdigest(),
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
        "schema_version": IDENTITY.schema("adjudication-input"),
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


def _run_phase(run: FrozenRun, phase: str) -> None:
    if phase == "prepare":
        evaluation_genesis_preflight(run)
    if phase not in PHASES:
        raise ValueError("INVALID_INTERNAL_ERROR")
    _prior_anchor(run, phase)
    output = _build_adjudication_payload(run) if phase == "adjudicate" else None
    with phase_guard(
        run.phase_ledger,
        phase,
        _PENDING,
        expected_context_sha256=run.context_sha256,
        elapsed_gates=_phase_gates(phase),
        require_bound_payload=True,
    ) as guard:
        if output is None:
            output = _execute_phase(run, phase)
        payload_sha = write_json_once(_phase_payload_path(run, phase), output)
        guard.bind_payload(payload_sha)


def _record_runner_anchor(run: FrozenRun) -> None:
    records = read_phases(run.phase_ledger, run.context_sha256)
    completed = [
        record.phase.removesuffix("_completed")
        for record in records
        if record.phase.endswith("_completed")
    ]
    unanchored = [
        phase for phase in completed if not (run.run_root / _anchor_ref(phase)).exists()
    ]
    if len(unanchored) != 1 or unanchored[0] != completed[-1]:
        raise ValueError("INVALID_RUNNER_ANCHOR")
    phase = unanchored[0]
    binding = _authority_binding(run)
    payload = _expected_anchor(run, phase, binding)
    relative = _anchor_ref(phase)
    request_sha = write_json_once(run.run_root / relative, payload)
    summary = f"SPINE_PHASE_ANCHOR phase={phase} request_sha256={request_sha}"
    command = (
        str(RUNNER_INTERPRETER),
        "-m",
        "agent_workflow_runner.cli",
        "team",
        "event",
        "--workspace-root",
        str(run.workspace),
        "--run-id",
        RUN_ID,
        "--type",
        "EVIDENCE_APPENDED",
        "--agent-id",
        "codex-cto",
        "--summary",
        summary,
        "--artifact",
        relative,
        "--evidence-ref",
        relative,
        "--approval-request-id",
        binding.request_id,
        "--source-decision-id",
        binding.source_decision_id,
        "--source-goal-id",
        binding.source_goal_id,
        "--source-decision-type",
        binding.source_decision_type,
    )
    subprocess.run(
        command,
        cwd=run.runner,
        env={**os.environ, "PYTHONPATH": str(run.runner / "src")},
        check=True,
    )
    _phase_anchor(run, phase)


def adjudicate_spine(payload: Mapping[str, Any]) -> dict[str, Any]:
    from .protocol import adjudicate_spine as implementation

    return implementation(payload)


def _finalize_result(run: FrozenRun) -> None:
    records = read_phases(run.phase_ledger, run.context_sha256)
    expected = [
        f"{phase}_{suffix}" for phase in PHASES for suffix in ("started", "completed")
    ]
    if [record.phase for record in records] != expected:
        raise ValueError("INVALID_PARTIAL_PHASE")
    anchors = {phase: _phase_anchor(run, phase) for phase in PHASES}
    payload = _json_file(run.data_root / "phases/adjudication_payload.json")
    if (
        not isinstance(payload, dict)
        or canonical_sha256(payload)
        != _completed_record(run, "adjudicate").payload_sha256
    ):
        raise ValueError("INVALID_BINDING")
    adjudication = adjudicate_spine(payload)
    result = {
        **adjudication,
        "schema_version": IDENTITY.schema("result"),
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "spec_sha256": run.context_bindings["spec_sha256"],
        "prereg_lock_sha256": run.context_bindings["prereg_lock_sha256"],
        "context_sha256": run.context_sha256,
        "adjudication_payload_sha256": canonical_sha256(payload),
        "phase_ledger_sha256": sha256_file(run.phase_ledger),
        "provider_ledger_sha256": sha256_file(run.provider_ledger),
        "runner_anchors": {
            phase: canonical_sha256(anchor) for phase, anchor in anchors.items()
        },
        "adjudication_schema_version": adjudication["schema_version"],
    }
    write_json_once(run.data_root / "result.json", result)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=IDENTITY.slug)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in (
        "prepare",
        "interrupt-batch",
        "probe-active-lease",
        "resume",
        "adjudicate",
        "record-runner-anchor",
        "finalize-result",
    ):
        commands.add_parser(command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    command = _parser().parse_args(argv).command
    run = resolve_frozen_run()
    if command == "record-runner-anchor":
        _record_runner_anchor(run)
    elif command == "finalize-result":
        _finalize_result(run)
    else:
        _run_phase(run, command.replace("-", "_"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
