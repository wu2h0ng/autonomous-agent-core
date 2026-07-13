"""Fresh successor public-application protocol bound to one identity source."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from agent_os_contracts import WorkflowGraph
from agent_os_core import ConcurrentWriteError, WorkerInterrupted

from .identity import IDENTITY
from .public_surface import normalize_projection


INPUTS = {"target_path": "subject.py", "test_command": "python -m pytest"}
EvidenceReader = Callable[[Any, str], Mapping[str, Any]]

_ADJUDICATION_CASE_IDS = (
    "st_reverse",
    "st_title",
    "st_trim_lower",
    "nr_sum",
    "nr_max",
    "nr_factorial",
    "val_email",
    "val_palindrome",
    "val_positive_int",
    "fmt_json",
    "fmt_csv",
    "fmt_table",
)
_ADJUDICATION_PHASES = (
    "prepare",
    "interrupt_batch",
    "probe_active_lease",
    "resume",
    "adjudicate",
)
# Phases completed when the adjudication payload is written (before adjudicate runs).
# adjudicate must not be claimed here; finalize-result verifies it independently.
_PAYLOAD_PHASES = (
    "prepare",
    "interrupt_batch",
    "probe_active_lease",
    "resume",
)
_ADJUDICATION_NODES = (
    "read",
    "provider",
    "approve",
    "apply",
    "tests",
    "evaluate",
    "done",
)
_DIGEST_FIELDS = {
    "case_manifest_sha256",
    "workflow_sha256",
    "evaluator_sha256",
    "provider_bank_sha256",
}
_TERMINAL_FIELDS = {
    "case_id",
    "task_sequence",
    "task_status",
    "run_status",
    "outcome_status",
    "outcome_score",
    "evaluator_type",
    "evaluator_version",
    "workflow_sha256",
    "completed_node_ids",
    "target_sha256",
    "pytest_exit_code",
    "apply_receipts",
    "lease_fence",
    "evidence_sha256",
    "workspace_tree_sha256",
    "provider_request_count",
    "normalized_projection",
}
_INTERRUPTED_FIELDS = {
    "case_id",
    "task_sequence",
    "task_status",
    "run_status",
    "workflow_sha256",
    "target_sha256",
    "apply_receipts",
    "lease_fence",
    "evidence_sha256",
    "workspace_tree_sha256",
    "provider_request_count",
    "normalized_projection",
}
_CASE_FIELDS = {
    "expected_final_target_sha256",
    "expected_workflow_sha256",
    "provider_rejected_attempt_count",
    "unexpected_policy_events",
    "unexpected_correction_events",
    "uninterrupted_terminal",
    "interrupted_after_apply",
    "probe",
    "resumed_terminal",
    "terminal_replay",
}
_TERMINAL_PROJECTION_FIELDS = {
    "task_status",
    "run_status",
    "outcome_status",
    "completed_node_ids",
    "target_sha256",
}
_INTERRUPTED_PROJECTION_FIELDS = {
    "task_status",
    "run_status",
    "target_sha256",
}


def build_case_contracts(
    case: Mapping[str, Any], contract_time: datetime
) -> dict[str, Any]:
    if contract_time.tzinfo is None:
        raise ValueError("contract_time must be timezone-aware")
    case_id = str(case["case_id"])
    goal_id = f"goal:{IDENTITY.slug}:{case_id}"
    task_ref = f"task:{IDENTITY.slug}:{case_id}"
    nodes = [
        {
            "node_id": "read",
            "kind": "tool",
            "capability": "workspace.read",
            "idempotency": "idempotent",
        },
        {"node_id": "provider", "kind": "provider", "capability": "provider.chat"},
        {"node_id": "approve", "kind": "approval"},
        {
            "node_id": "apply",
            "kind": "tool",
            "capability": "workspace.apply_patch",
            "idempotency": "compensatable",
            "risk_tier": 1,
        },
        {
            "node_id": "tests",
            "kind": "tool",
            "capability": "workspace.run_tests",
            "idempotency": "idempotent",
        },
        {"node_id": "evaluate", "kind": "evaluation"},
        {"node_id": "done", "kind": "terminal"},
    ]
    edge_pairs = zip(
        ("read", "provider", "approve", "apply", "tests", "evaluate"),
        ("provider", "approve", "apply", "tests", "evaluate", "done"),
        strict=True,
    )
    return {
        "goal": {
            "goal_id": goal_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": contract_time,
            "statement": str(case["goal"]),
        },
        "commitment": {
            "commitment_id": f"commitment:{IDENTITY.slug}:{case_id}",
            "task_id": task_ref,
            "goal_id": goal_id,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "accepted_by": "user:local",
            "accepted_at": contract_time,
            "deliverables": ["subject.py patch"],
            "acceptance_criteria": ["python -m pytest exits 0"],
            "authority_scopes": ["workspace:read", "workspace:write"],
            "budget": {
                "max_cost_usd": "10",
                "max_duration_seconds": 3600,
                "max_provider_tokens": 100000,
                "max_tool_calls": 100,
            },
            "risk_tier": 1,
            "exit_conditions": ["verified"],
            "expires_at": contract_time + timedelta(seconds=3600),
        },
        "workflow": {
            "workflow_id": f"workflow:{IDENTITY.slug}:{case_id}",
            "version": 1,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": contract_time,
            "policy_version": "policy-1",
            "evaluator_refs": ["evaluator:pytest:1"],
            "nodes": nodes,
            "edges": [
                {"source": source, "target": target} for source, target in edge_pairs
            ],
            "max_replans": 0,
        },
        "expected_outcome": {
            "expected_outcome_id": f"expected:{IDENTITY.slug}:{case_id}",
            "task_id": task_ref,
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "evaluator_type": "pytest",
            "evaluator_version": "1",
            "evidence_requirements": [
                "pytest-report",
                "apply-receipt",
                "final-workspace-digest",
            ],
            "failure_semantics": [
                "non-zero pytest exit",
                "missing evidence",
                "final digest mismatch",
            ],
            "threshold": 1.0,
            "observation_window_seconds": 3600,
            "frozen_at": contract_time,
        },
        "inputs": dict(INPUTS),
    }


def expected_workflow_sha256(case: Mapping[str, Any], contract_time: datetime) -> str:
    payload = build_case_contracts(case, contract_time)
    return WorkflowGraph.model_validate(payload["workflow"]).canonical_digest()


def _projection(application: Any, task_id: str) -> dict[str, Any]:
    application.provider_status()
    return normalize_projection(
        {
            "task": application.task_json(task_id),
            "evidence": application.evidence_json(task_id),
            "recovery": application.recovery_json(task_id),
        }
    )


def _prepare_arm(
    application: Any,
    payload: Mapping[str, Any],
    *,
    complete: bool,
) -> tuple[str, dict[str, Any]]:
    application.provider_status()
    created = application.create_task(payload["goal"])
    task_id = created.task_id
    commitment = dict(payload["commitment"])
    expected = dict(payload["expected_outcome"])
    commitment["task_id"] = task_id
    expected["task_id"] = task_id
    application.commit_task(
        task_id,
        {
            "commitment": commitment,
            "workflow": payload["workflow"],
            "expected_outcome": expected,
        },
    )
    waiting = application.run_task(task_id, dict(INPUTS))
    if waiting.run is None or waiting.run.status.value != "WAITING_APPROVAL":
        raise RuntimeError("prepare did not reach approval")
    application.record_approval(
        task_id,
        {
            "disposition": "APPROVE",
            "reason": f"{IDENTITY.experiment_id} frozen approval",
        },
    )
    if complete:
        terminal = application.run_task(task_id, dict(INPUTS))
        if terminal.observed_outcome is None:
            raise RuntimeError("uninterrupted arm did not produce an outcome")
    return task_id, _projection(application, task_id)


def prepare(
    uninterrupted_application: Any,
    interrupted_application: Any,
    case: Mapping[str, Any],
    contract_time: datetime | None = None,
) -> dict[str, Any]:
    payload = build_case_contracts(case, contract_time or datetime.now(timezone.utc))
    uninterrupted_id, uninterrupted_projection = _prepare_arm(
        uninterrupted_application, payload, complete=True
    )
    interrupted_id, interrupted_projection = _prepare_arm(
        interrupted_application, payload, complete=False
    )
    return {
        "contract_time": payload["goal"]["created_at"].isoformat(),
        "expected_workflow_sha256": WorkflowGraph.model_validate(
            payload["workflow"]
        ).canonical_digest(),
        "task_ids": {
            "uninterrupted": uninterrupted_id,
            "interrupted": interrupted_id,
        },
        "projections": {
            "uninterrupted": uninterrupted_projection,
            "interrupted": interrupted_projection,
        },
    }


def interrupt_batch(
    application: Any, task_ids: tuple[str, ...], evidence: EvidenceReader
) -> list[dict[str, Any]]:
    results = []
    for task_id in task_ids:
        before = dict(evidence(application, task_id))
        try:
            application.run_task(task_id, dict(INPUTS), **{"stop_after_node": "apply"})
        except WorkerInterrupted:
            after = dict(evidence(application, task_id))
            before_keys = before["apply_receipt_idempotency_keys"]
            after_keys = after["apply_receipt_idempotency_keys"]
            if (
                not isinstance(before_keys, list)
                or not isinstance(after_keys, list)
                or len(after_keys) != len(before_keys) + 1
                or after_keys[:-1] != before_keys
                or not isinstance(after_keys[-1], str)
                or not after_keys[-1]
            ):
                raise RuntimeError(
                    "interrupt did not persist exactly one new apply receipt"
                )
            if after["workspace_tree_sha256"] == before["workspace_tree_sha256"]:
                raise RuntimeError("interrupt did not persist the workspace patch")
            if after["provider_ledger_sha256"] != before["provider_ledger_sha256"]:
                raise RuntimeError("interrupt unexpectedly called the provider")
            results.append(after)
        else:
            raise RuntimeError("interrupt seam returned normally")
    return results


def probe_active_lease(
    application: Any, task_ids: tuple[str, ...], evidence: EvidenceReader
) -> list[dict[str, Any]]:
    results = []
    for task_id in task_ids:
        before = dict(evidence(application, task_id))
        try:
            application.run_task(task_id, dict(INPUTS), recover_stale_lease=False)
        except ConcurrentWriteError:
            after = dict(evidence(application, task_id))
            if after != before:
                raise RuntimeError("active-lease probe mutated public state")
            results.append(after)
        else:
            raise RuntimeError("active lease was not denied")
    return results


def resume_spine(
    application: Any, task_ids: tuple[str, ...], evidence: EvidenceReader
) -> list[dict[str, Any]]:
    results = []
    for task_id in task_ids:
        before = dict(evidence(application, task_id))
        resumed = application.run_task(task_id, dict(INPUTS), recover_stale_lease=False)
        if resumed.observed_outcome is None:
            raise RuntimeError("resume did not produce an outcome")
        terminal = dict(evidence(application, task_id))
        if terminal["lease_fence"] != before["lease_fence"] + 1:
            raise RuntimeError("resume did not advance the lease fence exactly once")
        if (
            terminal["apply_receipt_idempotency_keys"]
            != before["apply_receipt_idempotency_keys"]
        ):
            raise RuntimeError("resume changed the apply receipt sequence")
        if terminal["provider_ledger_sha256"] != before["provider_ledger_sha256"]:
            raise RuntimeError("resume unexpectedly called the provider")
        application.run_task(task_id, dict(INPUTS), recover_stale_lease=False)
        replay = dict(evidence(application, task_id))
        if replay != terminal:
            raise RuntimeError("terminal replay mutated public state")
        results.append({"resumed_terminal": terminal, "terminal_replay": replay})
    return results


def _canonical_input_sha256(value: Any) -> tuple[str, bool]:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return hashlib.sha256(
            f"{IDENTITY.slug}-invalid-non-json".encode()
        ).hexdigest(), False
    return hashlib.sha256(encoded).hexdigest(), True


def _exact_mapping(value: Any, fields: set[str]) -> bool:
    return isinstance(value, Mapping) and set(value) == fields


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_integer(value: Any) -> bool:
    return type(value) is int


def _is_number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _json_value(item) for key, item in value.items()
        )
    return False


def _valid_receipts(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 1:
        return False
    receipt = value[0]
    return (
        _exact_mapping(receipt, {"capability_id", "idempotency_key"})
        and receipt["capability_id"] == "workspace.apply_patch"
        and isinstance(receipt["idempotency_key"], str)
        and bool(receipt["idempotency_key"])
    )


def _valid_terminal_schema(snapshot: Any, case_id: str) -> bool:
    if not _exact_mapping(snapshot, _TERMINAL_FIELDS):
        return False
    return (
        snapshot["case_id"] == case_id
        and _is_integer(snapshot["task_sequence"])
        and isinstance(snapshot["task_status"], str)
        and isinstance(snapshot["run_status"], str)
        and isinstance(snapshot["outcome_status"], str)
        and _is_number(snapshot["outcome_score"])
        and isinstance(snapshot["evaluator_type"], str)
        and isinstance(snapshot["evaluator_version"], str)
        and _is_sha256(snapshot["workflow_sha256"])
        and isinstance(snapshot["completed_node_ids"], list)
        and all(isinstance(item, str) for item in snapshot["completed_node_ids"])
        and len(snapshot["completed_node_ids"])
        == len(set(snapshot["completed_node_ids"]))
        and _is_sha256(snapshot["target_sha256"])
        and _is_integer(snapshot["pytest_exit_code"])
        and _valid_receipts(snapshot["apply_receipts"])
        and _is_integer(snapshot["lease_fence"])
        and _is_sha256(snapshot["evidence_sha256"])
        and _is_sha256(snapshot["workspace_tree_sha256"])
        and _is_integer(snapshot["provider_request_count"])
        and _exact_mapping(
            snapshot["normalized_projection"], _TERMINAL_PROJECTION_FIELDS
        )
        and all(
            snapshot["normalized_projection"][field] == snapshot[field]
            for field in _TERMINAL_PROJECTION_FIELDS
        )
    )


def _valid_interrupted_schema(snapshot: Any, case_id: str, *, probe: bool) -> bool:
    fields = _INTERRUPTED_FIELDS | ({"denial_type"} if probe else set())
    if not _exact_mapping(snapshot, fields):
        return False
    return (
        snapshot["case_id"] == case_id
        and _is_integer(snapshot["task_sequence"])
        and isinstance(snapshot["task_status"], str)
        and isinstance(snapshot["run_status"], str)
        and _is_sha256(snapshot["workflow_sha256"])
        and _is_sha256(snapshot["target_sha256"])
        and _valid_receipts(snapshot["apply_receipts"])
        and _is_integer(snapshot["lease_fence"])
        and _is_sha256(snapshot["evidence_sha256"])
        and _is_sha256(snapshot["workspace_tree_sha256"])
        and _is_integer(snapshot["provider_request_count"])
        and _exact_mapping(
            snapshot["normalized_projection"], _INTERRUPTED_PROJECTION_FIELDS
        )
        and all(
            snapshot["normalized_projection"][field] == snapshot[field]
            for field in _INTERRUPTED_PROJECTION_FIELDS
        )
        and (not probe or snapshot["denial_type"] == "ConcurrentWriteError")
    )


def _terminal_product_passes(
    snapshot: Mapping[str, Any], expected_workflow: str, expected_target: str
) -> bool:
    return (
        snapshot["task_status"] == "COMPLETED"
        and snapshot["run_status"] == "SUCCEEDED"
        and snapshot["outcome_status"] == "VERIFIED"
        and snapshot["outcome_score"] == 1
        and snapshot["evaluator_type"] == "pytest"
        and snapshot["evaluator_version"] == "1"
        and snapshot["workflow_sha256"] == expected_workflow
        and snapshot["completed_node_ids"] == list(_ADJUDICATION_NODES)
        and snapshot["target_sha256"] == expected_target
        and snapshot["pytest_exit_code"] == 0
    )


def _case_verdict(case_id: str, value: Any) -> tuple[str, set[str]]:
    reasons: set[str] = set()
    if not _exact_mapping(value, _CASE_FIELDS):
        return "INVALID", {f"CASE_SCHEMA:{case_id}"}
    expected_target = value["expected_final_target_sha256"]
    expected_workflow = value["expected_workflow_sha256"]
    if (
        not _is_sha256(expected_target)
        or not _is_sha256(expected_workflow)
        or not _is_integer(value["provider_rejected_attempt_count"])
        or value["provider_rejected_attempt_count"] != 0
        or not isinstance(value["unexpected_policy_events"], list)
        or not isinstance(value["unexpected_correction_events"], list)
        or value["unexpected_policy_events"]
        or value["unexpected_correction_events"]
    ):
        return "INVALID", {f"CASE_INSTRUMENTATION:{case_id}"}
    uninterrupted = value["uninterrupted_terminal"]
    interrupted = value["interrupted_after_apply"]
    probe = value["probe"]
    resumed = value["resumed_terminal"]
    replay = value["terminal_replay"]
    if not (
        _valid_terminal_schema(uninterrupted, case_id)
        and _valid_interrupted_schema(interrupted, case_id, probe=False)
        and _valid_interrupted_schema(probe, case_id, probe=True)
        and _valid_terminal_schema(resumed, case_id)
        and _valid_terminal_schema(replay, case_id)
    ):
        return "INVALID", {f"SNAPSHOT_SCHEMA:{case_id}"}
    probe_comparable = set(_INTERRUPTED_FIELDS)
    if any(probe[field] != interrupted[field] for field in probe_comparable):
        reasons.add(f"PROBE_MUTATION:{case_id}")
    if any(
        snapshot["provider_request_count"] != 2
        for snapshot in (uninterrupted, interrupted, probe, resumed, replay)
    ):
        reasons.add(f"PROVIDER_COUNT:{case_id}")
    if any(
        snapshot["workflow_sha256"] != expected_workflow
        for snapshot in (interrupted, probe)
    ):
        reasons.add(f"WORKFLOW_RELATION:{case_id}")
    if any(
        snapshot["target_sha256"] != expected_target
        for snapshot in (interrupted, probe)
    ):
        reasons.add(f"TARGET_RELATION:{case_id}")
    if (
        len(
            {
                snapshot["workspace_tree_sha256"]
                for snapshot in (interrupted, probe, resumed, replay)
            }
        )
        != 1
    ):
        reasons.add(f"WORKSPACE_RELATION:{case_id}")
    if resumed["lease_fence"] != interrupted["lease_fence"] + 1:
        reasons.add(f"LEASE_FENCE:{case_id}")
    if resumed["apply_receipts"] != interrupted["apply_receipts"]:
        reasons.add(f"DUPLICATE_EFFECT:{case_id}")
    if replay != resumed:
        reasons.add(f"TERMINAL_REPLAY:{case_id}")
    if reasons:
        return "INVALID", reasons
    product_passes = uninterrupted["normalized_projection"] == resumed[
        "normalized_projection"
    ] and all(
        _terminal_product_passes(snapshot, expected_workflow, expected_target)
        for snapshot in (uninterrupted, resumed)
    )
    return (
        ("PASS", set())
        if product_passes
        else ("NOT_PASS", {f"PRODUCT_FAILURE:{case_id}"})
    )


def _global_invalid_reasons(payload: Mapping[str, Any]) -> set[str]:
    reasons: set[str] = set()
    if payload["schema_version"] != IDENTITY.schema("adjudication-input"):
        reasons.add("INPUT_SCHEMA_VERSION")
    case_ids = payload["expected_case_ids"]
    if not isinstance(case_ids, list) or tuple(case_ids) != _ADJUDICATION_CASE_IDS:
        reasons.add("CASE_MANIFEST")
    cases = payload["cases"]
    if not isinstance(cases, Mapping) or set(cases) != set(_ADJUDICATION_CASE_IDS):
        reasons.add("CASE_COVERAGE")
    bindings = payload["bindings"]
    if not _exact_mapping(bindings, {"expected", "observed"}):
        reasons.add("BINDINGS_SCHEMA")
    else:
        expected = bindings["expected"]
        observed = bindings["observed"]
        if not (
            _exact_mapping(expected, _DIGEST_FIELDS)
            and _exact_mapping(observed, _DIGEST_FIELDS)
            and all(_is_sha256(expected[field]) for field in _DIGEST_FIELDS)
            and all(_is_sha256(observed[field]) for field in _DIGEST_FIELDS)
            and expected == observed
        ):
            reasons.add("BINDING_DRIFT")
    phases = payload["phases"]
    phase_fields = {
        "expected_order",
        "completed",
        "context_sha256",
        "boot_id_sha256",
        "runner_anchors",
    }
    if not _exact_mapping(phases, phase_fields):
        reasons.add("PHASE_SCHEMA")
    else:
        if (
            phases["expected_order"] != list(_ADJUDICATION_PHASES)
            or phases["completed"] != list(_PAYLOAD_PHASES)
            or not _is_sha256(phases["context_sha256"])
            or not _is_sha256(phases["boot_id_sha256"])
        ):
            reasons.add("PHASE_DRIFT")
        anchors = phases["runner_anchors"]
        if not isinstance(anchors, Mapping) or set(anchors) != set(_PAYLOAD_PHASES):
            reasons.add("RUNNER_ANCHOR_COVERAGE")
        else:
            anchor_fields = {"context_sha256", "boot_id_sha256", "anchor_sha256"}
            if any(
                not _exact_mapping(anchor, anchor_fields)
                or anchor["context_sha256"] != phases["context_sha256"]
                or anchor["boot_id_sha256"] != phases["boot_id_sha256"]
                or not _is_sha256(anchor["anchor_sha256"])
                for anchor in anchors.values()
            ):
                reasons.add("RUNNER_ANCHOR_DRIFT")
    recovery = payload["recovery_configuration"]
    expected_recovery = [
        {"phase": "probe_active_lease", "recover_stale_lease": False},
        {"phase": "resume", "recover_stale_lease": False},
        {"phase": "terminal_replay", "recover_stale_lease": False},
    ]
    if recovery != expected_recovery:
        reasons.add("RECOVERY_CONFIGURATION")
    return reasons


def adjudicate_spine(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanically adjudicate a fully materialized successor payload."""
    input_sha256, json_valid = _canonical_input_sha256(payload)
    case_results = {case_id: "INVALID" for case_id in _ADJUDICATION_CASE_IDS}
    reasons: set[str] = set()
    global_reasons: set[str] = set()
    top_fields = {
        "schema_version",
        "expected_case_ids",
        "bindings",
        "phases",
        "recovery_configuration",
        "cases",
    }
    if (
        not json_valid
        or not _json_value(payload)
        or not _exact_mapping(payload, top_fields)
    ):
        global_reasons.add("INPUT_SCHEMA")
    else:
        global_reasons.update(_global_invalid_reasons(payload))
        cases = payload["cases"]
        for case_id in _ADJUDICATION_CASE_IDS:
            if not isinstance(cases, Mapping) or case_id not in cases:
                reasons.add(f"MISSING_CASE:{case_id}")
                continue
            verdict, case_reasons = _case_verdict(case_id, cases[case_id])
            case_results[case_id] = verdict
            reasons.update(case_reasons)
    reasons.update(global_reasons)
    if global_reasons:
        verdict = "INVALID"
        case_results = {case_id: "INVALID" for case_id in _ADJUDICATION_CASE_IDS}
    elif any(result == "INVALID" for result in case_results.values()):
        verdict = "INVALID"
    elif any(result == "NOT_PASS" for result in case_results.values()):
        verdict = "NOT_PASS"
    elif all(result == "PASS" for result in case_results.values()):
        verdict = "PASS"
    else:
        verdict = "INVALID"
    verified_case_count = sum(result == "PASS" for result in case_results.values())
    return {
        "schema_version": IDENTITY.schema("adjudication-result"),
        "verdict": verdict,
        "reason_codes": sorted(reasons),
        "verified_case_count": verified_case_count,
        "case_results": case_results,
        "input_sha256": input_sha256,
    }
