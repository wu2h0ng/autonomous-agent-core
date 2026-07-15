from __future__ import annotations

import ast
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from product_evals.lh_recovery_1a.combined_contract import (
    PUBLIC_API_ALLOWLIST,
    ArmCaseInput,
    validate_public_api_source,
)
from product_evals.common.artifacts import canonical_sha256
from product_evals.lh_recovery_1a.regimes import FAILURE_MODES, REGIMES
from product_evals.lh_recovery_1a.evaluator import (
    checkpoint_disposition,
    restart_disposition,
)

from agent_os_contracts import Commitment, ExpectedOutcome, Goal, WorkflowGraph


REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = REPO_ROOT / "product_evals/lh_recovery_1a/protocol.py"
CLI_PATH = REPO_ROOT / "product_evals/lh_recovery_1a/cli.py"


def _protocol() -> Any:
    return importlib.import_module("product_evals.lh_recovery_1a.protocol")


class _RecordingApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.task_snapshot: dict[str, object] = {}
        self.evidence_snapshot: list[dict[str, object]] = []
        self.recovery_snapshot: dict[str, object] = {}
        self.task_snapshots: dict[str, dict[str, object]] = {}
        self.evidence_snapshots: dict[str, list[dict[str, object]]] = {}
        self.recovery_snapshots: dict[str, dict[str, object]] = {}
        self.created_task_id = "task:new"

    def create_task(self, payload: dict[str, object]) -> SimpleNamespace:
        self.calls.append(("create_task", "", payload))
        return SimpleNamespace(task_id=self.created_task_id)

    def commit_task(self, task_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("commit_task", task_id, payload))

    def signal_task(self, task_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("signal_task", task_id, payload))

    def pause_task(self, task_id: str) -> None:
        self.calls.append(("pause_task", task_id, None))

    def replan_task(self, task_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("replan_task", task_id, payload))

    def run_task(
        self,
        task_id: str,
        inputs: dict[str, object],
        **kwargs: object,
    ) -> None:
        self.calls.append(("run_task", task_id, {"inputs": inputs, **kwargs}))

    def task_json(self, task_id: str) -> dict[str, object]:
        self.calls.append(("task_json", task_id, None))
        return self.task_snapshots.get(task_id, self.task_snapshot)

    def evidence_json(self, task_id: str) -> list[dict[str, object]]:
        self.calls.append(("evidence_json", task_id, None))
        return self.evidence_snapshots.get(task_id, self.evidence_snapshot)

    def recovery_json(self, task_id: str) -> dict[str, object]:
        self.calls.append(("recovery_json", task_id, None))
        return self.recovery_snapshots.get(task_id, self.recovery_snapshot)

    def record_approval(self, task_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("record_approval", task_id, payload))


def _call_names(app: _RecordingApplication) -> tuple[str, ...]:
    return tuple(call[0] for call in app.calls)


def _execute_change(regime: str, arm: str = "C") -> _RecordingApplication:
    protocol = _protocol()
    app = _RecordingApplication()
    secondary_wait_node = {
        "R1_DEPENDENCY_BEFORE_PROVIDER": "wait_dependency",
        "R2_RELEASE_BEFORE_APPLY": "wait_release",
    }.get(regime)
    if arm == "C" and secondary_wait_node is not None:
        app.task_snapshot = {
            "task_id": "task:case-1",
            "run": {"run_id": "run:case-1", "status": "RUNNING"},
            "events": [
                {
                    "event_id": "event:secondary-satisfied",
                    "sequence": 1,
                    "event_type": "WAIT_SATISFIED",
                    "payload": {"node_id": secondary_wait_node},
                }
            ],
        }
        app.recovery_snapshot = {
            "task_id": "task:case-1",
            "run_id": "run:case-1",
            "signal_satisfied_count": 2,
        }
    protocol.execute_change_phase(
        app,
        arm=arm,
        regime=regime,
        task_id="task:case-1",
        change_signal={"signal_id": "signal:case-1:change"},
        secondary_signal={"signal_id": "signal:case-1:secondary"},
        rebound_workflow={"workflow_id": "workflow:case-1", "version": 2},
        inputs={"prompt": "public prompt"},
    )
    return app


def _case_input() -> ArmCaseInput:
    values = {
        "case_id": "case-1",
        "family": "string_transform",
        "fixture_id": "fixture-1",
        "fixture_version_v1": 1,
        "fixture_version_v2": 2,
        "requirement_v1": "return OLD",
        "requirement_v2": "return NEW",
        "initial_content": "OLD\n",
        "prompt": "Implement the public requirement.",
    }
    return ArmCaseInput(
        **values,
        projection_sha256=canonical_sha256(values),
    )


def test_protocol_and_cli_modules_exist_with_public_entrypoints() -> None:
    protocol = _protocol()
    cli = importlib.import_module("product_evals.lh_recovery_1a.cli")
    assert callable(protocol.execute_change_phase)
    assert callable(cli.main)


@pytest.mark.parametrize("path", (PROTOCOL_PATH, CLI_PATH))
def test_protocol_sources_call_only_frozen_public_application_surface(
    path: Path,
) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_tokens = {
        "_composition",
        "provider_bank",
        "provider_responses",
        "private_store",
        "run_store",
        "task_store",
        "approval_store",
        "event_store",
    }
    calls: list[str] = []
    violations: list[str] = []
    for node in ast.walk(tree):
        candidate: str | None = None
        if isinstance(node, ast.Name):
            candidate = node.id
        elif isinstance(node, ast.Attribute):
            candidate = node.attr
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            candidate = node.value
        if candidate is not None and any(
            token in candidate.lower() for token in forbidden_tokens
        ):
            violations.append(candidate)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id in {
            "app",
            "application",
        }:
            calls.append(node.func.attr)
            if node.func.attr not in PUBLIC_API_ALLOWLIST:
                violations.append(node.func.attr)
    assert calls
    assert not violations


def test_candidate_r0_signals_twice_then_runs_without_replan() -> None:
    app = _execute_change("R0_DIRECT_REFRESH")
    assert _call_names(app) == ("signal_task", "signal_task", "run_task")
    assert app.calls[0][2] == app.calls[1][2]


@pytest.mark.parametrize(
    "regime",
    ("R1_DEPENDENCY_BEFORE_PROVIDER", "R2_RELEASE_BEFORE_APPLY"),
)
def test_candidate_r1_r2_signal_twice_pause_then_replan_exactly_once(
    regime: str,
) -> None:
    app = _execute_change(regime)
    names = _call_names(app)
    assert names[:4] == (
        "signal_task",
        "signal_task",
        "pause_task",
        "replan_task",
    )
    assert names.count("replan_task") == 1
    assert app.calls[0][2] == app.calls[1][2]


@pytest.mark.parametrize(
    ("regime", "node_id"),
    (
        ("R1_DEPENDENCY_BEFORE_PROVIDER", "wait_dependency"),
        ("R2_RELEASE_BEFORE_APPLY", "wait_release"),
    ),
)
def test_candidate_secondary_signal_persists_satisfied_public_projection(
    regime: str,
    node_id: str,
) -> None:
    protocol = _protocol()
    app = _RecordingApplication()
    app.task_snapshot = {
        "task_id": "task:case-1",
        "run": {"run_id": "run:case-1", "status": "RUNNING"},
        "events": [
            {
                "event_id": "event:secondary-satisfied",
                "sequence": 1,
                "event_type": "WAIT_SATISFIED",
                "payload": {"node_id": node_id},
            }
        ],
    }
    app.recovery_snapshot = {
        "task_id": "task:case-1",
        "run_id": "run:case-1",
        "signal_satisfied_count": 2,
    }
    receipt = protocol.execute_change_phase(
        app,
        arm="C",
        regime=regime,
        task_id="task:case-1",
        change_signal={"signal_id": "signal:case-1:change"},
        secondary_signal={"signal_id": "signal:case-1:secondary"},
        rebound_workflow={"workflow_id": "workflow:case-1", "version": 2},
        inputs={"prompt": "public prompt"},
    )
    assert receipt.secondary_wait is not None
    assert receipt.secondary_wait.disposition == "DELIVERED"
    assert receipt.public_calls[-3:] == ("task_json", "recovery_json", "run_task")


@pytest.mark.parametrize(
    "regime",
    (
        "R0_DIRECT_REFRESH",
        "R1_DEPENDENCY_BEFORE_PROVIDER",
        "R2_RELEASE_BEFORE_APPLY",
    ),
)
def test_fixed_arm_never_replans(regime: str) -> None:
    app = _execute_change(regime, arm="F")
    assert "replan_task" not in _call_names(app)


def test_episode_paths_are_isolated_and_reject_unsafe_components(
    tmp_path: Path,
) -> None:
    cli = importlib.import_module("product_evals.lh_recovery_1a.cli")
    paths = {
        arm: cli.episode_paths(tmp_path, "case-1", arm) for arm in ("C", "F", "R", "K")
    }
    assert len({item.database for item in paths.values()}) == 4
    assert len({item.workspace for item in paths.values()}) == 4
    assert all(item.database != item.workspace for item in paths.values())
    assert all(
        tmp_path.resolve() in item.workspace.resolve().parents
        for item in paths.values()
    )
    with pytest.raises(ValueError):
        cli.episode_paths(tmp_path, "../escape", "C")


def test_cli_main_consumes_only_the_derived_isolated_episode_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = importlib.import_module("product_evals.lh_recovery_1a.cli")
    opened: list[tuple[Path, Path]] = []

    class _PublicReader:
        def task_json(self, task_id: str) -> dict[str, str]:
            return {"task_id": task_id}

    def _open(*, database: Path, workspace: Path) -> _PublicReader:
        opened.append((database, workspace))
        return _PublicReader()

    monkeypatch.setattr(cli, "AgentOSApplication", _open)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lh-recovery-1a",
            "--root",
            str(tmp_path),
            "--case-id",
            "case-1",
            "--arm",
            "R",
            "task:new",
        ],
    )
    cli.main()
    expected = cli.episode_paths(tmp_path, "case-1", "R")
    assert opened == [(expected.database, expected.workspace)]
    assert json.loads(capsys.readouterr().out) == {"task_id": "task:new"}


@pytest.mark.parametrize("arm", ("C", "F", "R", "K"))
@pytest.mark.parametrize("regime", REGIMES)
def test_episode_contracts_are_exact_typed_and_canonical(
    arm: str,
    regime: str,
) -> None:
    protocol = _protocol()
    contract = protocol.build_episode_contract(
        _case_input(),
        arm=arm,
        regime=regime,
        failure=FAILURE_MODES[0],
        contract_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    Goal.model_validate(contract.goal)
    Commitment.model_validate({**contract.commitment, "task_id": "task:case-1"})
    ExpectedOutcome.model_validate(
        {**contract.expected_outcome, "task_id": "task:case-1"}
    )
    initial = WorkflowGraph.model_validate(contract.initial_workflow)
    recovery = WorkflowGraph.model_validate(contract.recovery_workflow)
    assert initial.max_replans == (1 if arm == "C" else 0)
    assert recovery.max_replans == (1 if arm == "C" else 0)
    encoded = protocol.serialize_episode_contract(contract)
    assert (
        json.dumps(
            json.loads(encoded),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        == encoded
    )
    assert set(json.loads(encoded)) == {field.name for field in fields(contract)}


@pytest.mark.parametrize("regime", REGIMES)
def test_all_arms_receive_identical_common_information_and_ceilings(
    regime: str,
) -> None:
    protocol = _protocol()
    contracts = {
        arm: protocol.build_episode_contract(
            _case_input(),
            arm=arm,
            regime=regime,
            failure=FAILURE_MODES[1],
            contract_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        for arm in ("C", "F", "R", "K")
    }
    common = {
        json.dumps(asdict(value.common_information), sort_keys=True)
        for value in contracts.values()
    }
    ceilings = {
        json.dumps(asdict(value.budget_ceiling), sort_keys=True)
        for value in contracts.values()
    }
    assert len(common) == len(ceilings) == 1
    assert contracts["C"].topology_selection_human_minutes == 2.0
    assert (
        contracts["C"].topology_selection_human_minutes
        == contracts["R"].topology_selection_human_minutes
    )


@pytest.mark.parametrize(
    ("regime", "event_type", "run_status", "expected"),
    (
        ("R1_DEPENDENCY_BEFORE_PROVIDER", "WAIT_SATISFIED", "RUNNING", "DELIVERED"),
        ("R2_RELEASE_BEFORE_APPLY", "WAIT_TIMED_OUT", "FAILED", "TIMED_OUT_TERMINAL"),
        ("R0_DIRECT_REFRESH", "RUN_SUCCEEDED", "SUCCEEDED", "TERMINAL_NO_SECONDARY"),
    ),
)
def test_secondary_wait_delivery_timeout_and_terminalization_are_distinct(
    regime: str,
    event_type: str,
    run_status: str,
    expected: str,
) -> None:
    protocol = _protocol()
    app = _RecordingApplication()
    node_id = {
        "R1_DEPENDENCY_BEFORE_PROVIDER": "wait_dependency",
        "R2_RELEASE_BEFORE_APPLY": "wait_release",
        "R0_DIRECT_REFRESH": "done",
    }[regime]
    app.task_snapshot = {
        "task_id": "task:case-1",
        "run": {"run_id": "run:case-1", "status": run_status},
        "events": [
            {
                "event_id": "event:proof",
                "sequence": 1,
                "event_type": event_type,
                "payload": {"node_id": node_id},
            }
        ],
    }
    app.recovery_snapshot = {
        "task_id": "task:case-1",
        "run_id": "run:case-1",
        "signal_satisfied_count": int(event_type == "WAIT_SATISFIED"),
    }
    proof = protocol.capture_secondary_wait(app, "task:case-1", regime)
    assert proof.disposition == expected
    assert proof.event_ids == ("event:proof",)


def test_secondary_wait_cannot_remain_waiting_at_terminalization() -> None:
    protocol = _protocol()
    app = _RecordingApplication()
    app.task_snapshot = {
        "task_id": "task:case-1",
        "run": {"run_id": "run:case-1", "status": "WAITING_EVENT"},
        "events": [],
    }
    app.recovery_snapshot = {
        "task_id": "task:case-1",
        "run_id": "run:case-1",
        "signal_satisfied_count": 0,
    }
    with pytest.raises(protocol.ProtocolEvidenceError, match="WAITING_EVENT"):
        protocol.capture_secondary_wait(
            app,
            "task:case-1",
            "R1_DEPENDENCY_BEFORE_PROVIDER",
        )


def _restart_application(contract: object) -> _RecordingApplication:
    app = _RecordingApplication()
    app.task_snapshots["task:old"] = {
        "task_id": "task:old",
        "run": {"run_id": "run:old"},
        "events": [{"event_id": "event:old", "event_type": "RUN_PAUSED"}],
    }
    app.evidence_snapshots["task:old"] = [
        {"event_id": "evidence:old", "event_type": "ARTIFACT_RECORDED"}
    ]
    app.recovery_snapshots["task:old"] = {
        "task_id": "task:old",
        "run_id": "run:old",
    }
    app.task_snapshots["task:new"] = {
        "task_id": "task:new",
        "run": {"run_id": "run:new"},
        "workflow": contract.recovery_workflow,
        "events": [{"event_id": "event:new", "event_type": "RUN_STARTED"}],
    }
    app.evidence_snapshots["task:new"] = [
        {"event_id": "evidence:new", "event_type": "ARTIFACT_RECORDED"}
    ]
    app.recovery_snapshots["task:new"] = {
        "task_id": "task:new",
        "run_id": "run:new",
    }
    return app


def test_adaptive_restart_recreates_only_through_public_api_with_exact_parity() -> None:
    protocol = _protocol()
    contract = protocol.build_episode_contract(
        _case_input(),
        arm="R",
        regime="R1_DEPENDENCY_BEFORE_PROVIDER",
        failure=FAILURE_MODES[0],
        contract_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    app = _restart_application(contract)
    receipt = protocol.execute_adaptive_restart(app, "task:old", contract)
    assert receipt.old_task_id == "task:old"
    assert receipt.new_task_id == "task:new"
    assert restart_disposition(receipt.evidence) == "VALID_RESTART"
    names = _call_names(app)
    assert names.count("create_task") == names.count("commit_task") == 1
    assert names.count("run_task") == 1
    commit_payload = next(call[2] for call in app.calls if call[0] == "commit_task")
    assert isinstance(commit_payload, dict)
    assert commit_payload["workflow"] == contract.recovery_workflow
    assert "task:old" not in json.dumps(commit_payload, sort_keys=True)


def test_adaptive_restart_rejects_reused_public_identity() -> None:
    protocol = _protocol()
    contract = protocol.build_episode_contract(
        _case_input(),
        arm="R",
        regime="R2_RELEASE_BEFORE_APPLY",
        failure=FAILURE_MODES[0],
        contract_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    app = _restart_application(contract)
    app.created_task_id = "task:old"
    with pytest.raises(protocol.ProtocolEvidenceError, match="fresh task"):
        protocol.execute_adaptive_restart(app, "task:old", contract)


def _checkpoint_application() -> _RecordingApplication:
    app = _RecordingApplication()
    app.task_snapshot = {
        "task_id": "task:checkpoint",
        "run": {"run_id": "run:checkpoint", "status": "FAILED"},
        "proposed_action": {"action_digest": "a" * 64},
        "events": [
            {
                "event_id": "event:checkpoint-reject",
                "sequence": 1,
                "event_type": "RUN_FAILED",
                "payload": {"error_code": "EXPECTED_SHA_MISMATCH"},
            }
        ],
    }
    app.evidence_snapshot = []
    app.recovery_snapshot = {
        "task_id": "task:checkpoint",
        "run_id": "run:checkpoint",
        "unique_logical_action_count": 0,
    }
    return app


@pytest.mark.parametrize(
    ("digest", "age_seconds", "expected_code"),
    (
        ("b" * 64, 30, "ACTION_SHA_MISMATCH"),
        ("a" * 64, 121, "STALE_APPROVAL"),
    ),
)
def test_checkpoint_rejects_wrong_sha_or_stale_approval_before_recording(
    digest: str,
    age_seconds: int,
    expected_code: str,
) -> None:
    protocol = _protocol()
    app = _checkpoint_application()
    now = datetime(2026, 7, 15, 0, 5, tzinfo=timezone.utc)
    approval = protocol.CheckpointApproval(
        action_digest=digest,
        decided_at=now - timedelta(seconds=age_seconds),
    )
    with pytest.raises(protocol.CheckpointApprovalRejected) as error:
        protocol.record_checkpoint_approval(
            app,
            "task:checkpoint",
            approval,
            change_occurred_at=now - timedelta(seconds=60),
            now=now,
        )
    assert error.value.code == expected_code
    assert "record_approval" not in _call_names(app)


def test_checkpoint_accepts_only_fresh_matching_approval_then_proves_sha_rejection() -> (
    None
):
    protocol = _protocol()
    app = _checkpoint_application()
    now = datetime(2026, 7, 15, 0, 5, tzinfo=timezone.utc)
    approval = protocol.CheckpointApproval(
        action_digest="a" * 64,
        decided_at=now - timedelta(seconds=30),
    )
    receipt = protocol.record_checkpoint_approval(
        app,
        "task:checkpoint",
        approval,
        change_occurred_at=now - timedelta(seconds=60),
        now=now,
    )
    assert _call_names(app).count("record_approval") == 1
    evidence = protocol.capture_checkpoint_evidence(
        app,
        "task:checkpoint",
        receipt,
        workspace_digest_before="1" * 64,
        workspace_digest_after="1" * 64,
    )
    assert checkpoint_disposition(evidence) == "VALID_NEGATIVE_CONTROL"
    assert evidence.rejection_code == "EXPECTED_SHA_MISMATCH"
    assert evidence.successful_apply_receipts == evidence.logical_effects == 0


def test_checkpoint_missing_expected_sha_failure_is_not_accepted() -> None:
    protocol = _protocol()
    app = _checkpoint_application()
    app.task_snapshot["events"] = []
    receipt = protocol.CheckpointApprovalReceipt(
        action_digest="a" * 64,
        approval_age_seconds=30,
        recorded_after_change=True,
    )
    with pytest.raises(protocol.ProtocolEvidenceError, match="EXPECTED_SHA_MISMATCH"):
        protocol.capture_checkpoint_evidence(
            app,
            "task:checkpoint",
            receipt,
            workspace_digest_before="1" * 64,
            workspace_digest_after="1" * 64,
        )


def test_actual_protocol_source_passes_frozen_public_ast_guard() -> None:
    calls = validate_public_api_source(
        PROTOCOL_PATH.read_text(encoding="utf-8"),
        application_receivers=("app",),
    )
    assert calls
    assert set(calls) <= set(PUBLIC_API_ALLOWLIST)


def _event(
    sequence: int,
    event_type: str,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "event_id": f"event:{sequence}",
        "sequence": sequence,
        "event_type": event_type,
        "payload": payload,
    }


def _apply_event(
    sequence: int, *, receipt_id: str = "receipt:apply"
) -> dict[str, object]:
    return _event(
        sequence,
        "ACTION_RECEIPT_RECORDED",
        {
            "receipt": {
                "receipt_id": receipt_id,
                "connector_id": "workspace.apply_patch",
                "status": "SUCCEEDED",
                "idempotency_key": "idem:one-logical-effect",
            }
        },
    )


def _failure_application(failure: str) -> _RecordingApplication:
    app = _RecordingApplication()
    if failure == "PRE_CONSEQUENCE_PROCESS_EXIT":
        events = [
            _event(1, "NODE_COMPLETED", {"node_id": "read_v2"}),
            _event(2, "RUN_RESUMED", {"recover_stale_lease": False}),
        ]
        evidence: list[dict[str, object]] = []
        logical_effects = 0
    elif failure == "POST_APPLY_WORKER_INTERRUPTED":
        events = [
            _apply_event(1),
            _event(2, "NODE_COMPLETED", {"node_id": "apply"}),
            _event(3, "RUN_RESUMED", {"recover_stale_lease": False}),
        ]
        evidence = [events[0]]
        logical_effects = 1
    else:
        events = [
            _event(1, "APPROVAL_RECORDED", {"fresh": True, "age_seconds": 10}),
            _event(2, "CORRECTION_WRITTEN", {"halted": True}),
            _event(
                3,
                "POLICY_DECIDED",
                {
                    "decision": {
                        "verdict": "DENY",
                        "reason_codes": ["CORRECTION_HALTED"],
                    }
                },
            ),
            _event(4, "CORRECTION_WRITTEN", {"halted": False}),
            _event(5, "APPROVAL_RECORDED", {"fresh": True, "age_seconds": 10}),
            _apply_event(6),
        ]
        evidence = [events[-1]]
        logical_effects = 1
    app.task_snapshot = {
        "task_id": "task:failure",
        "run": {"run_id": "run:failure", "status": "FAILED"},
        "events": events,
    }
    app.evidence_snapshot = evidence
    app.recovery_snapshot = {
        "task_id": "task:failure",
        "run_id": "run:failure",
        "run_resumed_count": int(failure != "CORRECTION_HALT_BEFORE_APPLY"),
        "unique_logical_action_count": logical_effects,
    }
    return app


@pytest.mark.parametrize("failure", FAILURE_MODES)
def test_all_assigned_failures_require_exact_public_proofs(failure: str) -> None:
    protocol = _protocol()
    app = _failure_application(failure)
    proof = protocol.capture_failure_proof(
        app,
        "task:failure",
        failure,
        before_process_id="process:before",
        after_process_id="process:after",
    )
    assert proof.valid
    assert proof.observed_public_proofs == proof.required_public_proofs
    assert proof.duplicate_logical_effects == 0


def test_post_apply_duplicate_logical_effect_is_detected() -> None:
    protocol = _protocol()
    app = _failure_application("POST_APPLY_WORKER_INTERRUPTED")
    duplicate = _apply_event(4, receipt_id="receipt:duplicate")
    app.task_snapshot["events"].append(duplicate)
    app.evidence_snapshot.append(duplicate)
    proof = protocol.capture_failure_proof(
        app,
        "task:failure",
        "POST_APPLY_WORKER_INTERRUPTED",
        before_process_id="process:before",
        after_process_id="process:after",
    )
    assert not proof.valid
    assert proof.duplicate_logical_effects == 1


def test_missing_correction_denial_proof_cannot_be_constant_return_success() -> None:
    protocol = _protocol()
    app = _failure_application("CORRECTION_HALT_BEFORE_APPLY")
    app.task_snapshot["events"] = [
        event
        for event in app.task_snapshot["events"]
        if event["event_type"] != "POLICY_DECIDED"
    ]
    proof = protocol.capture_failure_proof(
        app,
        "task:failure",
        "CORRECTION_HALT_BEFORE_APPLY",
        before_process_id="process:before",
        after_process_id="process:after",
    )
    assert not proof.valid
    assert (
        "halted_action_is_denied_with_zero_effect" not in proof.observed_public_proofs
    )
