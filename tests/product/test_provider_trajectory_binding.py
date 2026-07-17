from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from agent_os_contracts import (
    BindingStatus,
    CredentialRef,
    CredentialStatus,
    EdgeSpec,
    IdempotencyMode,
    NodeKind,
    NodeSpec,
    ProviderExecutionReceipt,
    ProviderInvocationBinding,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
    TaskEventDraft,
    TaskEventType,
    TaskConfigurationSnapshot,
    WorkflowGraph,
    content_digest,
    provider_execution_receipt_digest,
)
from agent_os_core import DeterministicProvider, RunExecutionError, ScopeMismatchError
from agent_os_core.event_store import InMemoryTaskEventStore
from agent_os_core.trajectory import TrajectoryProjector


NOW = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
REVISION = "b" * 64


def _profile(*, revision: str | None = REVISION) -> ProviderProfile:
    return ProviderProfile(
        profile_id="provider-profile:trajectory",
        provider_id="provider:test",
        model_id="model:test",
        model_revision_digest=revision,
        endpoint_class="test",
        credential_ref_id="credential:trajectory",
        capabilities=("chat", "tool-calls"),
        max_context_tokens=16_000,
        request_timeout_seconds=60,
        created_at=NOW,
    )


def _binding(profile: ProviderProfile) -> ProviderInvocationBinding:
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


def _workflow() -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow:provider-trajectory",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:none:1",),
        nodes=(
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
            NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(
            EdgeSpec(source="read", target="provider"),
            EdgeSpec(source="provider", target="evaluate"),
            EdgeSpec(source="evaluate", target="done"),
        ),
    )


def _committed_task(app: AgentOSApplication) -> str:
    (app.sandbox.root / "fixture.txt").write_text("before\n", encoding="utf-8")
    task = app.create_task(
        {
            "goal_id": "goal:provider-trajectory",
            "tenant_id": "tenant:local",
            "workspace_id": "workspace:local",
            "created_by": "user:local",
            "created_at": NOW,
            "statement": "inspect fixture",
        }
    )
    app.commit_task(
        task.task_id,
        {
            "commitment": {
                "commitment_id": "commitment:provider-trajectory",
                "task_id": task.task_id,
                "goal_id": "goal:provider-trajectory",
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "accepted_by": "user:local",
                "accepted_at": NOW,
                "deliverables": ["provider trajectory"],
                "acceptance_criteria": ["typed provider receipt"],
                "authority_scopes": [
                    "workspace:read",
                    "task.configuration.snapshot",
                ],
                "budget": {
                    "max_cost_usd": "1",
                    "max_duration_seconds": 300,
                    "max_provider_tokens": 1000,
                    "max_tool_calls": 10,
                },
                "risk_tier": 1,
                "exit_conditions": ["receipt projected"],
                "expires_at": NOW + timedelta(days=1),
            },
            "workflow": _workflow().model_dump(mode="json"),
            "expected_outcome": {
                "expected_outcome_id": "expected:provider-trajectory",
                "task_id": task.task_id,
                "tenant_id": "tenant:local",
                "workspace_id": "workspace:local",
                "evaluator_type": "none",
                "evaluator_version": "1",
                "evidence_requirements": ["provider receipt"],
                "failure_semantics": ["missing receipt"],
                "threshold": 1,
                "observation_window_seconds": 60,
                "frozen_at": NOW,
            },
        },
    )
    return task.task_id


def _bound_app(tmp_path, *, revision: str | None = REVISION) -> AgentOSApplication:
    app = AgentOSApplication(database=tmp_path / "agent.sqlite3", workspace=tmp_path)
    profile = _profile(revision=revision)
    app.provider_profile = profile
    app.provider = DeterministicProvider(
        text="SENSITIVE_RESPONSE_BODY",
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:provider-trajectory",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
        ),
        invocation_binding=_binding(profile),
    )
    app.provider_configured = True
    return app


def _run_bound(
    app: AgentOSApplication, task_id: str
) -> tuple[str, TaskConfigurationSnapshot]:
    snapshot = app.seal_task_configuration(task_id, {})
    result = app.run_task(
        task_id,
        {
            "target_path": "fixture.txt",
            "prompt": "SENSITIVE_PROMPT_BODY",
        },
        configuration_snapshot_id=snapshot.snapshot_id,
    )
    assert result.run is not None
    return result.run.run_id, snapshot


def _copy_stream_with_receipt(
    app: AgentOSApplication,
    task_id: str,
    receipt_payload: dict[str, object],
    *,
    provider_event_id: str | None = None,
    provider_node_id: str | None = None,
) -> InMemoryTaskEventStore:
    copied = InMemoryTaskEventStore()
    for event in app.store.read(task_id):
        payload = event.decoded_payload()
        if event.event_type is TaskEventType.PROVIDER_RESPONDED:
            payload["provider_execution_receipt"] = receipt_payload
            if provider_node_id is not None:
                payload["node_id"] = provider_node_id
        copied.append(
            task_id,
            expected_sequence=len(copied.read(task_id)),
            drafts=(
                TaskEventDraft.build(
                    event_id=(
                        provider_event_id
                        if event.event_type is TaskEventType.PROVIDER_RESPONDED
                        and provider_event_id is not None
                        else event.event_id
                    ),
                    task_id=event.task_id,
                    event_type=event.event_type,
                    payload=payload,
                    occurred_at=event.occurred_at,
                    correlation_id=event.correlation_id,
                    causation_id=event.causation_id,
                ),
            ),
        )
    return copied


def test_bound_developer_run_emits_typed_provider_receipt_and_read_only_projection(
    tmp_path,
) -> None:
    app = _bound_app(tmp_path)
    task_id = _committed_task(app)
    run_id, snapshot = _run_bound(app, task_id)

    provider_events = tuple(
        event
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.PROVIDER_RESPONDED
    )
    assert len(provider_events) == 1
    receipt = ProviderExecutionReceipt.model_validate(
        provider_events[0].decoded_payload()["provider_execution_receipt"]
    )
    assert receipt.task_id == task_id
    assert receipt.run_id == run_id
    assert receipt.source_event_id == provider_events[0].event_id
    assert receipt.node_id == "provider"
    assert receipt.provider_profile_id == _profile().profile_id
    assert receipt.provider_profile_digest == snapshot.provider_profile_digest
    assert receipt.provider_id == _profile().provider_id
    assert receipt.model_id == _profile().model_id
    assert receipt.model_revision_digest == REVISION
    assert receipt.request_id.startswith("request-")
    assert receipt.response_id.startswith("response-")
    assert receipt.invocation_binding_digest == _binding(_profile()).digest()
    assert receipt.working_set_ref.status is BindingStatus.MISSING

    projection = app.project_task_trajectory(task_id, run_id)
    invocation = next(
        step.model_invocation
        for step in projection.steps
        if step.model_invocation is not None
    )
    assert invocation is not None
    assert invocation.request_id == receipt.request_id
    assert invocation.response_id == receipt.response_id
    assert invocation.request_digest == receipt.request_digest
    assert invocation.response_digest == receipt.response_digest
    assert invocation.model_revision_digest == REVISION
    assert projection.manifest.working_set_ref.status is BindingStatus.MISSING


def test_unbound_provider_fails_before_invocation(tmp_path) -> None:
    app = AgentOSApplication(database=tmp_path / "unbound.sqlite3", workspace=tmp_path)
    app.provider_profile = _profile()
    provider = DeterministicProvider(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:unbound",
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(
                    {"path": "fixture.txt", "content": "after\n"}
                ),
            ),
        )
    )
    app.provider = provider
    app.provider_configured = True
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})

    with pytest.raises(RunExecutionError, match="invocation binding"):
        app.run_task(
            task_id,
            {"target_path": "fixture.txt"},
            configuration_snapshot_id=snapshot.snapshot_id,
        )
    assert provider.requests == []


def test_provider_binding_profile_drift_fails_before_invocation(tmp_path) -> None:
    app = _bound_app(tmp_path)
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})
    drifted = _profile().model_copy(update={"profile_id": "provider-profile:drift"})
    provider = DeterministicProvider(
        tool_proposals=app.provider.tool_proposals,  # type: ignore[attr-defined]
        invocation_binding=_binding(drifted),
    )
    app.provider = provider

    with pytest.raises(RunExecutionError, match="profile.*binding"):
        app.run_task(
            task_id,
            {"target_path": "fixture.txt"},
            configuration_snapshot_id=snapshot.snapshot_id,
        )
    assert provider.requests == []


def test_missing_revision_and_untrusted_nested_working_set_remain_explicit_gaps(
    tmp_path,
) -> None:
    app = _bound_app(tmp_path, revision=None)
    task_id = _committed_task(app)
    run_id, _ = _run_bound(app, task_id)
    projection = app.project_task_trajectory(task_id, run_id)
    invocation = next(
        step.model_invocation
        for step in projection.steps
        if step.model_invocation is not None
    )
    assert invocation is not None
    assert invocation.model_revision_digest is None
    assert "model_revision_digest" in invocation.missing_fields
    assert invocation.working_set_ref.status is BindingStatus.MISSING


def test_tampered_provider_receipt_digest_is_rejected_by_projection(tmp_path) -> None:
    app = _bound_app(tmp_path)
    task_id = _committed_task(app)
    run_id, _ = _run_bound(app, task_id)
    receipt = dict(
        next(
            event.decoded_payload()["provider_execution_receipt"]
            for event in app.store.read(task_id)
            if event.event_type is TaskEventType.PROVIDER_RESPONDED
        )
    )
    receipt["provider_profile_digest"] = "c" * 64
    tampered = _copy_stream_with_receipt(app, task_id, receipt)

    with pytest.raises(ValidationError, match="receipt digest"):
        TrajectoryProjector().project(tampered, task_id, run_id)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_id", "provider:rewritten"),
        ("model_id", "model:rewritten"),
        ("model_revision_digest", "d" * 64),
    ),
)
def test_self_consistent_provider_identity_rewrite_cannot_escape_sealed_profile(
    tmp_path, field: str, value: str
) -> None:
    app = _bound_app(tmp_path)
    task_id = _committed_task(app)
    run_id, _ = _run_bound(app, task_id)
    receipt = dict(
        next(
            event.decoded_payload()["provider_execution_receipt"]
            for event in app.store.read(task_id)
            if event.event_type is TaskEventType.PROVIDER_RESPONDED
        )
    )
    receipt[field] = value
    receipt["receipt_digest"] = provider_execution_receipt_digest(receipt)
    ProviderExecutionReceipt.model_validate(receipt)
    rewritten = _copy_stream_with_receipt(app, task_id, receipt)

    with pytest.raises(ScopeMismatchError, match="configuration.*binding"):
        TrajectoryProjector().project(rewritten, task_id, run_id)


@pytest.mark.parametrize(
    ("event_id", "node_id"),
    (
        ("event:provider-replayed", "provider"),
        (None, "provider-replayed"),
    ),
)
def test_valid_receipt_cannot_be_replayed_on_another_provider_event_or_node(
    tmp_path, event_id: str | None, node_id: str
) -> None:
    app = _bound_app(tmp_path)
    task_id = _committed_task(app)
    run_id, _ = _run_bound(app, task_id)
    receipt = dict(
        next(
            event.decoded_payload()["provider_execution_receipt"]
            for event in app.store.read(task_id)
            if event.event_type is TaskEventType.PROVIDER_RESPONDED
        )
    )
    replayed = _copy_stream_with_receipt(
        app,
        task_id,
        receipt,
        provider_event_id=event_id,
        provider_node_id=node_id,
    )

    with pytest.raises(ScopeMismatchError, match="source event|node"):
        TrajectoryProjector().project(replayed, task_id, run_id)


def test_correction_during_provider_call_prevents_response_persistence(tmp_path) -> None:
    app = _bound_app(tmp_path)
    profile = app.provider_profile

    class CorrectingProvider(DeterministicProvider):
        def complete(self, request: ProviderRequest) -> ProviderResponse:
            app.correction.correct("task", request.task_id, "during provider call")
            return super().complete(request)

    provider = CorrectingProvider(
        text="SENSITIVE_RESPONSE_BODY",
        tool_proposals=app.provider.tool_proposals,  # type: ignore[attr-defined]
        invocation_binding=_binding(profile),
    )
    app.provider = provider
    task_id = _committed_task(app)
    snapshot = app.seal_task_configuration(task_id, {})

    with pytest.raises(RunExecutionError, match="correction.*changed|halted"):
        app.run_task(
            task_id,
            {"target_path": "fixture.txt"},
            configuration_snapshot_id=snapshot.snapshot_id,
        )
    assert len(provider.requests) == 1
    assert all(
        event.event_type is not TaskEventType.PROVIDER_RESPONDED
        for event in app.store.read(task_id)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tenant_id", "tenant:other"),
        ("workspace_id", "workspace:other"),
        ("run_id", "run:other"),
        ("correction_epoch", 999),
    ),
)
def test_provider_receipt_scope_or_epoch_confusion_is_rejected(
    tmp_path, field: str, value: object
) -> None:
    app = _bound_app(tmp_path)
    task_id = _committed_task(app)
    run_id, _ = _run_bound(app, task_id)
    receipt_payload = next(
        event.decoded_payload()["provider_execution_receipt"]
        for event in app.store.read(task_id)
        if event.event_type is TaskEventType.PROVIDER_RESPONDED
    )
    changed = dict(receipt_payload)
    changed[field] = value
    if field == "correction_epoch":
        for epoch_field in ("pre_correction_epochs", "post_correction_epochs"):
            epochs = dict(changed[epoch_field])
            epochs["task_epoch"] = value
            changed[epoch_field] = epochs
    changed["receipt_digest"] = provider_execution_receipt_digest(changed)
    ProviderExecutionReceipt.model_validate(changed)
    confused = _copy_stream_with_receipt(app, task_id, changed)

    with pytest.raises(ScopeMismatchError, match="scope|epoch"):
        TrajectoryProjector().project(confused, task_id, run_id)


def test_projection_survives_restart_and_http_exposes_only_safe_refs(tmp_path) -> None:
    app = _bound_app(tmp_path)
    task_id = _committed_task(app)
    run_id, _ = _run_bound(app, task_id)
    first = app.project_task_trajectory(task_id, run_id)

    restarted = AgentOSApplication(
        database=tmp_path / "agent.sqlite3", workspace=tmp_path
    )
    second = restarted.project_task_trajectory(task_id, run_id)
    assert second == first

    handler = type("TrajectoryHandler", (Handler,), {"application": restarted})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(
            f"{base}/v1/tasks/{task_id}/runs/{run_id}/trajectory"
        ) as response:
            payload = json.loads(response.read())
        serialized = json.dumps(payload)
        assert payload["trajectory_digest"] == first.trajectory_digest
        assert "SENSITIVE_PROMPT_BODY" not in serialized
        assert "SENSITIVE_RESPONSE_BODY" not in serialized
        assert "TEST_PROVIDER_SECRET" not in serialized
        assert "credential_ref" not in serialized
        assert "base_url" not in serialized
    finally:
        server.shutdown()
        server.server_close()
