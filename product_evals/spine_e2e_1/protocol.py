"""Frozen SPINE-E2E-1 public-application protocol."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from agent_os_core import ConcurrentWriteError, WorkerInterrupted

from product_evals.common.public_surface import normalize_projection


INPUTS = {"target_path": "subject.py", "test_command": "python -m pytest"}
EvidenceReader = Callable[[Any, str], Mapping[str, Any]]


def build_case_contracts(
    case: Mapping[str, Any], contract_time: datetime
) -> dict[str, Any]:
    if contract_time.tzinfo is None:
        raise ValueError("contract_time must be timezone-aware")
    case_id = str(case["case_id"])
    goal_id = f"goal:spine-e2e-1:{case_id}"
    task_ref = f"task:spine-e2e-1:{case_id}"
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
            "commitment_id": f"commitment:spine-e2e-1:{case_id}",
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
            "workflow_id": f"workflow:spine-e2e-1:{case_id}",
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
            "expected_outcome_id": f"expected:spine-e2e-1:{case_id}",
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
        task_id, {"disposition": "APPROVE", "reason": "SPINE-E2E-1 frozen approval"}
    )
    if complete:
        terminal = application.run_task(task_id, dict(INPUTS))
        if (
            terminal.observed_outcome is None
            or terminal.observed_outcome.status.value != "VERIFIED"
        ):
            raise RuntimeError("uninterrupted arm did not verify")
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
            application.run_task(task_id, dict(INPUTS), stop_after_node="apply")
        except WorkerInterrupted:
            after = dict(evidence(application, task_id))
            if after["action_receipt_count"] != before["action_receipt_count"] + 1:
                raise RuntimeError(
                    "interrupt did not persist exactly one apply receipt"
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
        if (
            resumed.observed_outcome is None
            or resumed.observed_outcome.status.value != "VERIFIED"
        ):
            raise RuntimeError("resume did not reach VERIFIED")
        terminal = dict(evidence(application, task_id))
        if terminal["lease_fence"] != before["lease_fence"] + 1:
            raise RuntimeError("resume did not advance the lease fence exactly once")
        if terminal["action_receipt_count"] != before["action_receipt_count"]:
            raise RuntimeError("resume duplicated the completed apply receipt")
        if terminal["provider_ledger_sha256"] != before["provider_ledger_sha256"]:
            raise RuntimeError("resume unexpectedly called the provider")
        application.run_task(task_id, dict(INPUTS), recover_stale_lease=False)
        if dict(evidence(application, task_id)) != terminal:
            raise RuntimeError("terminal replay mutated public state")
        results.append(terminal)
    return results
