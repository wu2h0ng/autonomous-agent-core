from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

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
    RunExecutionError,
    TaskConfigurationNotBound,
)
from apps.api_server.app import AgentOSApplication


NOW = datetime.now(timezone.utc)
TARGET = "src/widget.py"
ORIGINAL = "alpha = 1\nbeta = 2\n"
DIFF = """\
--- a/src/widget.py
+++ b/src/widget.py
@@ -1,2 +1,3 @@
 alpha = 1
 beta = 2
+gamma = 3
"""
PATCHED = "alpha = 1\nbeta = 2\ngamma = 3\n"


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
        workflow_id="workflow:diff-mode-test",
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


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    target = workspace / TARGET
    target.parent.mkdir(parents=True)
    target.write_text(ORIGINAL, encoding="utf-8")
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_widget.py").write_text(
        "from pathlib import Path\n\n"
        "def test_widget_patched():\n"
        "    text = Path('src/widget.py').read_text(encoding='utf-8')\n"
        "    assert 'gamma = 3' in text\n",
        encoding="utf-8",
    )
    return workspace


def _binding(app: AgentOSApplication) -> ProviderInvocationBinding:
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
    return ProviderInvocationBinding(
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


def _provider(app: AgentOSApplication, arguments: dict[str, object]) -> None:
    app.provider = DeterministicProvider(
        text="",
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:diff-mode-1",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(arguments),
            ),
        ),
        invocation_binding=_binding(app),
    )
    app.provider_configured = True


def _committed_task(app: AgentOSApplication) -> str:
    created = app.create_task(
        {
            "goal_id": "goal:diff-mode-test",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "Apply a unified diff to the widget",
        }
    )
    app.commit_task(
        created.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:diff-mode-test",
                "task_id": created.task_id,
                "goal_id": "goal:diff-mode-test",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["Agent OS repository patch"],
                "acceptance_criteria": ["exact-digest approval is recorded"],
                "authority_scopes": [
                    "workspace:read",
                    "workspace:write",
                    "task.configuration.snapshot",
                ],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 3600,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["verified"],
                "expires_at": NOW + timedelta(hours=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:diff-mode-test",
                "task_id": created.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "pytest",
                "evaluator_version": "1",
                "evidence_requirements": ["test-report"],
                "failure_semantics": ["non-zero exit"],
                "threshold": 1,
                "observation_window_seconds": 3600,
                "frozen_at": NOW,
            },
        },
    )
    return created.task_id


def _diff_inputs() -> dict[str, object]:
    return {
        "target_path": TARGET,
        "test_command": "python -m pytest",
        "patch_format": "unified_diff",
    }


def test_diff_mode_sealed_run_applies_diff_end_to_end(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    app = AgentOSApplication(database=tmp_path / "db.sqlite3", workspace=workspace)
    _provider(app, {"path": TARGET, "diff": DIFF})
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})

    with pytest.raises(TaskConfigurationNotBound):
        app.run_task(task_id, _diff_inputs())

    waiting = app.run_task(
        task_id,
        _diff_inputs(),
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    assert (workspace / TARGET).read_text(encoding="utf-8") == ORIGINAL

    app.record_approval(
        task_id,
        {"disposition": "APPROVE", "reason": "exact diff approved"},
    )
    result = app.run_task(
        task_id,
        _diff_inputs(),
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert result.status is TaskStatus.COMPLETED
    assert (workspace / TARGET).read_text(encoding="utf-8") == PATCHED

    reader = AgentOSApplication(database=tmp_path / "db.sqlite3", workspace=workspace)
    assert result.run is not None
    report = reader.tasks.validated_test_report(task_id, result.run.run_id)
    assert report is not None
    report_path = reader.sandbox.artifacts / report.artifact_ids[0].removeprefix(
        "artifact:"
    )
    report_path.unlink()
    compensated = reader.compensate_task(task_id)
    assert compensated.compensations[-1].status.value == "COMPENSATED"
    assert (workspace / TARGET).read_text(encoding="utf-8") == ORIGINAL


def test_diff_mode_proposal_cannot_apply_without_approval(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    app = AgentOSApplication(database=tmp_path / "db.sqlite3", workspace=workspace)
    _provider(app, {"path": TARGET, "diff": DIFF})
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})

    waiting = app.run_task(
        task_id,
        _diff_inputs(),
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    assert waiting.status is not TaskStatus.COMPLETED
    assert (workspace / TARGET).read_text(encoding="utf-8") == ORIGINAL


def test_diff_mode_text_response_extracts_and_applies(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    app = AgentOSApplication(database=tmp_path / "db.sqlite3", workspace=workspace)
    fenced = f"Here is the fix.\n```diff\n{DIFF}```\n"
    app.provider = DeterministicProvider(
        text=fenced,
        tool_proposals=(),
        invocation_binding=_binding(app),
    )
    app.provider_configured = True
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})

    waiting = app.run_task(
        task_id,
        _diff_inputs(),
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL

    app.record_approval(
        task_id,
        {"disposition": "APPROVE", "reason": "exact diff approved"},
    )
    result = app.run_task(
        task_id,
        _diff_inputs(),
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert result.status is TaskStatus.COMPLETED
    assert (workspace / TARGET).read_text(encoding="utf-8") == PATCHED


def test_diff_mode_text_response_cannot_apply_without_approval(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    app = AgentOSApplication(database=tmp_path / "db.sqlite3", workspace=workspace)
    app.provider = DeterministicProvider(
        text=DIFF,
        tool_proposals=(),
        invocation_binding=_binding(app),
    )
    app.provider_configured = True
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})

    waiting = app.run_task(
        task_id,
        _diff_inputs(),
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert waiting.run is not None
    assert waiting.run.status is RunStatus.WAITING_APPROVAL
    assert waiting.status is not TaskStatus.COMPLETED
    assert (workspace / TARGET).read_text(encoding="utf-8") == ORIGINAL


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        (f"```diff\n{DIFF}```\n", DIFF),
        (DIFF, DIFF),
        (f"Some explanation first.\n{DIFF}", DIFF),
        ("no diff here at all", None),
        ("", None),
    ),
)
def test_extract_unified_diff_matrix(text, expected) -> None:
    from agent_os_core import extract_unified_diff

    assert extract_unified_diff(text) == expected



@pytest.mark.parametrize(
    ("arguments", "inputs", "detail"),
    (
        (
            {"path": TARGET, "content": PATCHED},
            _diff_inputs(),
            "provider diff arguments must contain only path and diff",
        ),
        (
            {"path": TARGET, "diff": DIFF},
            {"target_path": TARGET, "test_command": "python -m pytest"},
            "provider patch arguments must contain only path and content",
        ),
        (
            {"path": TARGET, "diff": DIFF.replace("src/widget.py", "src/other.py")},
            _diff_inputs(),
            "provider diff path does not match the proposal path",
        ),
        (
            {"path": "src/other.py", "diff": DIFF},
            _diff_inputs(),
            "provider diff path does not match the proposal path",
        ),
        (
            {"path": TARGET, "diff": DIFF.replace("a/src/widget.py", "a//etc/passwd").replace("b/src/widget.py", "b//etc/passwd")},
            _diff_inputs(),
            "provider diff failed validation",
        ),
        (
            {"path": TARGET, "diff": DIFF.replace("a/src/widget.py", "a/../secret.py").replace("b/src/widget.py", "b/../secret.py")},
            _diff_inputs(),
            "provider diff failed validation",
        ),
        (
            {"path": TARGET, "diff": DIFF + "\nnot-a-hunk-line\n"},
            _diff_inputs(),
            "provider diff failed validation",
        ),
        (
            {"path": TARGET, "diff": ""},
            _diff_inputs(),
            "provider proposal requires string diff content",
        ),
        (
            {"path": TARGET, "diff": DIFF},
            {
                "target_path": TARGET,
                "test_command": "python -m pytest",
                "patch_format": "yaml",
            },
            "unsupported patch_format",
        ),
    ),
)
def test_diff_mode_validation_matrix(tmp_path, arguments, inputs, detail) -> None:
    workspace = _workspace(tmp_path)
    app = AgentOSApplication(database=tmp_path / "db.sqlite3", workspace=workspace)
    _provider(app, arguments)
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})

    with pytest.raises(RunExecutionError) as exc_info:
        app.run_task(
            task_id,
            inputs,
            configuration_snapshot_id=snapshot.snapshot_id,
        )
    assert detail in str(exc_info.value)
    assert (workspace / TARGET).read_text(encoding="utf-8") == ORIGINAL
