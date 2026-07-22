from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderInvocationBinding,
    ProviderToolProposal,
    RunStatus,
    TaskStatus,
    WorkflowGraph,
    content_digest,
)
from agent_os_core import (
    DeterministicProvider,
    INVALID_SELFDEV_TARGET,
    RUN_DENIED,
    SelfDevelopmentTaskSpec,
    SelfDevelopmentValidationError,
    TaskConfigurationNotBound,
    WorkerInterrupted,
    build_self_development_baseline_record,
    build_self_development_comparison_receipt,
    build_self_development_run_record,
    prepare_self_development_task_package,
    validate_self_development_task,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime.now(timezone.utc)
AGENT_OS_TARGET = "packages/os_core/src/agent_os_core/recovery.py"


def _workflow() -> WorkflowGraph:
    nodes = (
        NodeSpec(
            node_id="read",
            kind=NodeKind.TOOL,
            capability="workspace.read",
            idempotency=IdempotencyMode.IDEMPOTENT,
        ),
        NodeSpec(
            node_id="provider",
            kind=NodeKind.PROVIDER,
            capability="provider.chat",
        ),
        NodeSpec(node_id="approve", kind=NodeKind.APPROVAL),
        NodeSpec(
            node_id="apply",
            kind=NodeKind.TOOL,
            capability="workspace.apply_patch",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(
            node_id="tests",
            kind=NodeKind.TOOL,
            capability="workspace.run_tests",
            idempotency=IdempotencyMode.COMPENSATABLE,
        ),
        NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
        NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
    )
    edges = tuple(
        EdgeSpec(source=source, target=target)
        for source, target in (
            ("read", "provider"),
            ("provider", "approve"),
            ("approve", "apply"),
            ("apply", "tests"),
            ("tests", "evaluate"),
            ("evaluate", "done"),
        )
    )
    return WorkflowGraph(
        workflow_id="workflow:selfdev-s1",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=nodes,
        edges=edges,
    )


def test_selfdev_s1_agent_os_repo_patch_requires_approval_evidence_and_rollback(
    tmp_path,
) -> None:
    source_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "agent-os-copy"
    target = workspace / AGENT_OS_TARGET
    target.parent.mkdir(parents=True)
    original = (source_root / AGENT_OS_TARGET).read_text(encoding="utf-8")
    target.write_text(original, encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_selfdev_marker.py").write_text(
        "from pathlib import Path\n\n"
        "def test_selfdev_marker_present():\n"
        "    text = Path('packages/os_core/src/agent_os_core/recovery.py')"
        ".read_text(encoding='utf-8')\n"
        "    assert '# SELFDEV-S1 verified marker' in text\n",
        encoding="utf-8",
    )
    repository_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    receipt = validate_self_development_task(
        SelfDevelopmentTaskSpec(
            mandate_id="META-SHADOW-MANDATE-0",
            repository_id="autonomous-agent-core",
            repository_head=repository_head,
            isolated_workspace=str(workspace),
            isolated_branch="codex/selfdev-s1-test",
            target_path=AGENT_OS_TARGET,
            verifier_commands=("python -m pytest",),
            expected_outcome_id="expected:selfdev-s1",
            rollback_strategy="compensate_task",
            operator_intervention_count=1,
            hcw_minutes=0.5,
            baseline_assignment_id="baseline:selfdev-s1-founder-tools",
        )
    )
    assert receipt.target_path == AGENT_OS_TARGET
    assert receipt.verifier_commands == ("python -m pytest",)
    assert len(receipt.receipt_digest) == 64

    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=workspace)
    app.provider = DeterministicProvider(
        text="",
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:selfdev-s1",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {
                        "path": AGENT_OS_TARGET,
                        "content": f"{original}\n# SELFDEV-S1 verified marker\n",
                    }
                ),
            ),
        ),
    )
    app.provider_configured = True
    task = app.create_task(
        {
            "goal_id": "goal:selfdev-s1",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "Improve Agent OS by adding a bounded SELFDEV marker",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:selfdev-s1",
                "task_id": task.task_id,
                "goal_id": "goal:selfdev-s1",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["Agent OS repository patch"],
                "acceptance_criteria": [
                    "SELFDEV target contract is admitted",
                    "pytest evidence is durable",
                    "compensation restores pre-change bytes",
                ],
                "authority_scopes": ["workspace:read", "workspace:write"],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": NOW + timedelta(hours=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:selfdev-s1",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": NOW,
            },
        },
    )

    inputs = {"target_path": AGENT_OS_TARGET, "test_command": "python -m pytest"}
    try:
        app.run_task(task.task_id, inputs, stop_after_node="read")
    except WorkerInterrupted:
        pass
    restarted = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=workspace,
    )
    restarted.provider = app.provider
    restarted.provider_configured = True
    waiting = restarted.run_task(
        task.task_id,
        inputs,
        recover_stale_lease=True,
    )
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    assert target.read_text(encoding="utf-8") == original

    restarted.record_approval(
        task.task_id,
        {"disposition": "APPROVE", "reason": "Exact SELFDEV-S1 patch approved"},
    )
    result = restarted.run_task(task.task_id, inputs)
    assert result.status is TaskStatus.COMPLETED
    assert result.observed_outcome is not None
    assert result.observed_outcome.status.value == "VERIFIED"
    assert "# SELFDEV-S1 verified marker" in target.read_text(encoding="utf-8")
    assert len(result.artifacts) == 1
    assert result.run is not None

    reader = AgentOSApplication(
        database=tmp_path / "agent-os.sqlite3",
        workspace=workspace,
    )
    assert reader.task_json(task.task_id)["outcome_evidence_valid"] is True
    report = reader.tasks.validated_test_report(task.task_id, result.run.run_id)
    assert report is not None
    report_path = reader.sandbox.artifacts / report.artifact_ids[0].removeprefix(
        "artifact:"
    )
    report_path.unlink()
    assert reader.task_json(task.task_id)["outcome_evidence_valid"] is False
    projected = reader.task_json(task.task_id)
    assert projected["status"] == "FAILED"
    assert projected["run"]["status"] == "FAILED"
    assert projected["observed_outcome"]["status"] == "UNRESOLVED"
    assert projected["historical_observed_outcome"]["status"] == "VERIFIED"

    compensated = reader.compensate_task(task.task_id)
    assert target.read_text(encoding="utf-8") == original
    assert compensated.compensations[-1].status.value == "COMPENSATED"
    requests = app.provider.requests
    assert len(requests) == 1
    assert requests[0].allowed_capability_ids == ("workspace.apply_patch",)


def test_selfdev_sealed_provider_run_approves_and_resumes_in_one_process(
    tmp_path,
) -> None:
    source_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "agent-os-copy"
    target = workspace / AGENT_OS_TARGET
    target.parent.mkdir(parents=True)
    original = (source_root / AGENT_OS_TARGET).read_text(encoding="utf-8")
    target.write_text(original, encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_selfdev_marker.py").write_text(
        "from pathlib import Path\n\n"
        "def test_selfdev_marker_present():\n"
        "    text = Path('packages/os_core/src/agent_os_core/recovery.py')"
        ".read_text(encoding='utf-8')\n"
        "    assert '# SELFDEV-S1 verified marker' in text\n",
        encoding="utf-8",
    )
    repository_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    spec = SelfDevelopmentTaskSpec(
        mandate_id="META-SHADOW-MANDATE-0",
        repository_id="autonomous-agent-core",
        repository_head=repository_head,
        isolated_workspace=str(workspace),
        isolated_branch="codex/selfdev-seal-approve-test",
        target_path=AGENT_OS_TARGET,
        verifier_commands=("python -m pytest",),
        expected_outcome_id="expected:selfdev-seal-approve",
        rollback_strategy="compensate_task",
        operator_intervention_count=1,
        hcw_minutes=0.5,
        baseline_assignment_id="baseline:selfdev-seal-approve",
    )

    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=workspace)
    profile = app.provider_profile
    credential = CredentialRef(
        credential_ref_id=profile.credential_ref_id,
        owner_principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        provider_id=profile.provider_id,
        resolver_key="TEST_PROVIDER_SECRET",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    binding = ProviderInvocationBinding(
        provider_profile=profile,
        provider_id=profile.provider_id,
        endpoint_class=profile.endpoint_class,
        credential_ref_id=profile.credential_ref_id,
        credential_ref_digest=content_digest(credential),
        max_context_tokens=profile.max_context_tokens,
        adapter_kind="deterministic-test",
        transport="in-process",
        base_url="https://provider.invalid",
        endpoint_path="/chat/completions",
        model_id=profile.model_id,
        request_timeout_seconds=profile.request_timeout_seconds,
        temperature=Decimal("0"),
    )
    app.provider = DeterministicProvider(
        text="",
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:selfdev-seal-approve",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {
                        "path": AGENT_OS_TARGET,
                        "content": f"{original}\n# SELFDEV-S1 verified marker\n",
                    }
                ),
            ),
        ),
        invocation_binding=binding,
    )
    app.provider_configured = True
    receipt = validate_self_development_task(spec)
    created = app.create_task(
        {
            "goal_id": f"goal:selfdev:{receipt.receipt_digest[:12]}",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "Sealed SELFDEV provider run with in-process approval",
        }
    )
    package = prepare_self_development_task_package(
        spec,
        task_id=created.task_id,
        created_at=NOW,
        duration_seconds=3600,
    )
    app.commit_task(created.task_id, package.task_commit_payload)
    snapshot = app.seal_task_configuration(created.task_id, {})

    with pytest.raises(TaskConfigurationNotBound):
        app.run_task(created.task_id, package.run_inputs)

    waiting = app.run_task(
        created.task_id,
        package.run_inputs,
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    assert target.read_text(encoding="utf-8") == original

    app.record_approval(
        created.task_id,
        {
            "disposition": "APPROVE",
            "reason": "Exact-digest provider proposal approved in-process",
        },
    )
    result = app.run_task(
        created.task_id,
        package.run_inputs,
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert result.status is TaskStatus.COMPLETED
    assert result.observed_outcome is not None
    assert result.observed_outcome.status.value == "VERIFIED"
    assert "# SELFDEV-S1 verified marker" in target.read_text(encoding="utf-8")
    assert result.run is not None
    assert result.run.configuration_snapshot_id == snapshot.snapshot_id


def test_selfdev_s1_rejects_generic_fixture_target() -> None:
    with pytest.raises(SelfDevelopmentValidationError) as exc_info:
        validate_self_development_task(
            SelfDevelopmentTaskSpec(
                mandate_id="META-SHADOW-MANDATE-0",
                repository_id="autonomous-agent-core",
                repository_head="0123456789abcdef",
                isolated_workspace="/tmp/agent-os-copy",
                isolated_branch="codex/selfdev-s1-test",
                target_path="fixture.txt",
                verifier_commands=("python -m pytest",),
                expected_outcome_id="expected:selfdev-s1",
                rollback_strategy="compensate_task",
                operator_intervention_count=1,
                hcw_minutes=0.5,
                baseline_assignment_id="baseline:selfdev-s1-founder-tools",
            )
        )
    assert exc_info.value.code == INVALID_SELFDEV_TARGET


def test_selfdev_comparison_receipt_binds_matched_baseline_and_hcw_verdict() -> None:
    spec = SelfDevelopmentTaskSpec(
        mandate_id="META-SHADOW-MANDATE-0",
        repository_id="autonomous-agent-core",
        repository_head="0123456789abcdef",
        isolated_workspace="/tmp/agent-os-selfdev",
        isolated_branch="codex/selfdev-compare",
        target_path=AGENT_OS_TARGET,
        verifier_commands=("python -m pytest",),
        expected_outcome_id="expected:selfdev-compare",
        rollback_strategy="compensate_task",
        operator_intervention_count=1,
        hcw_minutes=2.0,
        baseline_assignment_id="baseline:selfdev-compare",
    )
    baseline = build_self_development_baseline_record(
        baseline_assignment_id="baseline:selfdev-compare",
        repository_id="autonomous-agent-core",
        target_path=AGENT_OS_TARGET,
        operator_intervention_count=2,
        hcw_minutes=5.0,
        outcome_status="VERIFIED",
        evidence_refs=("baseline:run",),
    )
    run_record = build_self_development_run_record(
        spec,
        operator_intervention_count=1,
        hcw_minutes=2.0,
        outcome_status="VERIFIED",
        evidence_refs=("selfdev:run",),
    )

    receipt = build_self_development_comparison_receipt(
        spec,
        baseline_record=baseline,
        selfdev_run_record=run_record,
    )

    assert receipt.verdict == "SELFDEV_HCW_LOWER"
    assert receipt.hcw_delta_minutes == -3.0
    assert receipt.operator_intervention_delta == -1
    assert receipt.baseline_record.record_digest == baseline.record_digest
    assert receipt.selfdev_run_record.record_digest == run_record.record_digest
    assert len(receipt.receipt_digest) == 64


def test_selfdev_comparison_uses_post_run_record_not_spec_estimates() -> None:
    spec = SelfDevelopmentTaskSpec(
        mandate_id="META-SHADOW-MANDATE-0",
        repository_id="autonomous-agent-core",
        repository_head="0123456789abcdef",
        isolated_workspace="/tmp/agent-os-selfdev",
        isolated_branch="codex/selfdev-compare-run-record",
        target_path=AGENT_OS_TARGET,
        verifier_commands=("python -m pytest",),
        expected_outcome_id="expected:selfdev-compare-run-record",
        rollback_strategy="compensate_task",
        operator_intervention_count=0,
        hcw_minutes=0.25,
        baseline_assignment_id="baseline:selfdev-compare-run-record",
    )
    baseline = build_self_development_baseline_record(
        baseline_assignment_id="baseline:selfdev-compare-run-record",
        repository_id="autonomous-agent-core",
        target_path=AGENT_OS_TARGET,
        operator_intervention_count=2,
        hcw_minutes=3.5,
        outcome_status="VERIFIED",
        evidence_refs=("baseline:run",),
    )
    run_record = build_self_development_run_record(
        spec,
        operator_intervention_count=3,
        hcw_minutes=7.0,
        outcome_status="VERIFIED",
        evidence_refs=("selfdev:actual-run",),
    )

    receipt = build_self_development_comparison_receipt(
        spec,
        baseline_record=baseline,
        selfdev_run_record=run_record,
    )

    assert receipt.verdict == "SELFDEV_HCW_NOT_LOWER"
    assert receipt.selfdev_hcw_minutes == 7.0
    assert receipt.hcw_delta_minutes == 3.5
    assert receipt.selfdev_operator_intervention_count == 3
    assert receipt.operator_intervention_delta == 1


def test_selfdev_comparison_receipt_refuses_mismatched_baseline() -> None:
    spec = SelfDevelopmentTaskSpec(
        mandate_id="META-SHADOW-MANDATE-0",
        repository_id="autonomous-agent-core",
        repository_head="0123456789abcdef",
        isolated_workspace="/tmp/agent-os-selfdev",
        isolated_branch="codex/selfdev-compare",
        target_path=AGENT_OS_TARGET,
        verifier_commands=("python -m pytest",),
        expected_outcome_id="expected:selfdev-compare",
        rollback_strategy="compensate_task",
        operator_intervention_count=1,
        hcw_minutes=2.0,
        baseline_assignment_id="baseline:selfdev-compare",
    )
    baseline = build_self_development_baseline_record(
        baseline_assignment_id="baseline:selfdev-other",
        repository_id="autonomous-agent-core",
        target_path=AGENT_OS_TARGET,
        operator_intervention_count=2,
        hcw_minutes=5.0,
        outcome_status="VERIFIED",
        evidence_refs=("baseline:run",),
    )
    run_record = build_self_development_run_record(
        spec,
        operator_intervention_count=1,
        hcw_minutes=2.0,
        outcome_status="VERIFIED",
        evidence_refs=("selfdev:run",),
    )

    with pytest.raises(SelfDevelopmentValidationError):
        build_self_development_comparison_receipt(
            spec,
            baseline_record=baseline,
            selfdev_run_record=run_record,
        )


def test_selfdev_comparison_receipt_refuses_shared_evidence_refs() -> None:
    spec = SelfDevelopmentTaskSpec(
        mandate_id="META-SHADOW-MANDATE-0",
        repository_id="autonomous-agent-core",
        repository_head="0123456789abcdef",
        isolated_workspace="/tmp/agent-os-selfdev",
        isolated_branch="codex/selfdev-compare-evidence",
        target_path=AGENT_OS_TARGET,
        verifier_commands=("python -m pytest",),
        expected_outcome_id="expected:selfdev-compare-evidence",
        rollback_strategy="compensate_task",
        operator_intervention_count=1,
        hcw_minutes=2.0,
        baseline_assignment_id="baseline:selfdev-compare-evidence",
    )
    baseline = build_self_development_baseline_record(
        baseline_assignment_id="baseline:selfdev-compare-evidence",
        repository_id="autonomous-agent-core",
        target_path=AGENT_OS_TARGET,
        operator_intervention_count=2,
        hcw_minutes=5.0,
        outcome_status="VERIFIED",
        evidence_refs=("shared:evidence", "baseline:run"),
    )
    run_record = build_self_development_run_record(
        spec,
        operator_intervention_count=1,
        hcw_minutes=2.0,
        outcome_status="VERIFIED",
        evidence_refs=("shared:evidence", "selfdev:run"),
    )

    with pytest.raises(SelfDevelopmentValidationError) as exc_info:
        build_self_development_comparison_receipt(
            spec,
            baseline_record=baseline,
            selfdev_run_record=run_record,
        )

    assert exc_info.value.code == RUN_DENIED
    assert "EVIDENCE_REF_OVERLAP" in exc_info.value.detail
