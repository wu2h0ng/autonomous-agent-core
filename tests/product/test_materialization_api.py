from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from agent_os_contracts import (
    CandidateProvenance,
    CandidateWriteChannel,
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    MaterializationOutcome,
    NodeKind,
    NodeSpec,
    PrincipalIdentity,
    PrincipalRole,
    RepresentationPatch,
    RepresentationPatchOperation,
    RepresentationRelationClass,
    ResourceBudget,
    RunStatus,
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core import candidate_source_snapshot_digest


NOW = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_D = "d" * 64


@contextmanager
def _running_server(app: AgentOSApplication) -> Iterator[str]:
    handler = type("MaterializationHandler", (Handler,), {"application": app})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    idempotency_key: str = "materialization-http-key",
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            status = response.status
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = json.loads(exc.read())
    assert isinstance(payload, dict)
    return status, payload


def _workflow() -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow:http-materialization",
        version=1,
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:materialization-contract:1",),
        nodes=(
            NodeSpec(
                node_id="discover",
                kind=NodeKind.TOOL,
                capability="workspace.read",
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="discover", target="done"),),
    )


def _running_task(app: AgentOSApplication) -> tuple[str, str]:
    goal = Goal(
        goal_id="goal:http-materialization",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        created_by="user:local",
        created_at=NOW,
        statement="Build an inert grounded representation candidate",
    )
    created = app.tasks.create_task(goal)
    commitment = Commitment(
        commitment_id="commitment:http-materialization",
        task_id=created.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by="user:local",
        accepted_at=NOW,
        deliverables=("sealed candidate",),
        acceptance_criteria=("no runtime activation",),
        authority_scopes=("domain.materialize",),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=1_000,
            max_tool_calls=4,
        ),
        risk_tier=1,
        exit_conditions=("candidate sealed or abstained",),
        expires_at=FAR_FUTURE,
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:http-materialization",
        task_id=created.task_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        evaluator_type="materialization-contract",
        evaluator_version="1",
        evidence_requirements=("source provenance",),
        failure_semantics=("unsupported claims abstain",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )
    app.tasks.commit_task(created.task_id, commitment, _workflow(), expected)
    started = app.tasks.start_run(created.task_id)
    assert started.run is not None
    running = app.tasks.update_run_status(
        created.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_QUEUED,
    )
    assert running.run is not None
    return created.task_id, running.run.run_id


def _patch(object_ref: str = "type:Company") -> RepresentationPatch:
    return RepresentationPatch(
        operations=(
            RepresentationPatchOperation(
                operation_id="op:company-kind",
                operation="UPSERT",
                assertion_id="assertion:company-kind",
                subject_ref="entity:acme",
                predicate="rdf:type",
                object_ref=object_ref,
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("evidence:filing",),
            ),
        )
    )


def _candidate_body(
    task_id: str,
    run_id: str,
    *,
    patch: RepresentationPatch | None = None,
    parent_candidate_digest: str | None = None,
    mechanism_digest: str = DIGEST_B,
    requested_channel: CandidateWriteChannel = CandidateWriteChannel.R,
    outcome: MaterializationOutcome = MaterializationOutcome.CANDIDATE,
) -> dict[str, Any]:
    selected_patch = patch or _patch()
    provenance: tuple[CandidateProvenance, ...] = (
        (
            CandidateProvenance(
                source_id="source:filing",
                source_ref="artifact:filing",
                source_type="regulatory-filing",
                source_digest=DIGEST_A,
                accessed_at=NOW - timedelta(minutes=5),
                effective_at=NOW - timedelta(days=1),
                license_or_terms_id="terms:public-filing",
                permitted_use="analysis",
                redistribution_allowed=False,
                custodian_verified_by="principal:reviewer",
                derivation_input_digests=(DIGEST_A,),
                output_patch_digest=selected_patch.patch_digest(),
                expires_at=FAR_FUTURE,
            ),
        )
        if outcome is MaterializationOutcome.CANDIDATE
        else ()
    )
    return {
        "task_id": task_id,
        "materialization_run_id": run_id,
        "tenant_id": "tenant:local",
        "workspace_id": "workspace:local",
        "submitted_by": "user:local",
        "mechanism_digest": mechanism_digest,
        "source_snapshot_digest": candidate_source_snapshot_digest(provenance),
        "parent_candidate_digest": parent_candidate_digest,
        "requested_channel": requested_channel.value,
        "outcome": outcome.value,
        "representation_patch": (
            selected_patch.model_dump(mode="json")
            if outcome is MaterializationOutcome.CANDIDATE
            else None
        ),
        "provenance": [item.model_dump(mode="json") for item in provenance],
        "submitted_at": NOW.isoformat(),
    }


@pytest.fixture
def app(tmp_path: Path) -> Iterator[AgentOSApplication]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = tmp_path / "state" / "agent-os.sqlite3"
    database.parent.mkdir()
    value = AgentOSApplication(database=database, workspace=workspace)
    yield value
    candidates = getattr(value, "candidates", None)
    if candidates is not None:
        candidates.close()
    value.store.close()


def test_http_seals_and_lists_without_mutating_task_or_workspace(
    app: AgentOSApplication,
) -> None:
    task_id, run_id = _running_task(app)
    before_events = app.store.read(task_id)
    before_task = app.tasks.get_task(task_id)
    assert before_task.workflow is not None
    before_workflow_digest = before_task.workflow.canonical_digest()
    before_workspace = tuple(sorted(path.relative_to(app.sandbox.root) for path in app.sandbox.root.rglob("*") if path.is_file()))
    before_grants = dict(app.grants)
    before_epochs = app.correction.snapshot(task_id, run_id, "domain.materialize")

    with _running_server(app) as base:
        status, sealed = _request_json(
            base,
            f"/v1/tasks/{task_id}/domain-candidates:seal",
            method="POST",
            body=_candidate_body(task_id, run_id),
        )
        listed_status, listed = _request_json(
            base,
            f"/v1/tasks/{task_id}/domain-candidates",
        )

    assert status == 201
    assert listed_status == 200
    assert sealed["draft"]["materialization_run_id"] == run_id
    assert [item["candidate_digest"] for item in listed["candidates"]] == [
        sealed["candidate_digest"]
    ]
    after_task = app.tasks.get_task(task_id)
    assert app.store.read(task_id) == before_events
    assert after_task.status == before_task.status
    assert after_task.run == before_task.run
    assert after_task.workflow is not None
    assert after_task.workflow.canonical_digest() == before_workflow_digest
    assert tuple(sorted(path.relative_to(app.sandbox.root) for path in app.sandbox.root.rglob("*") if path.is_file())) == before_workspace
    assert app.grants == before_grants
    assert app.correction.snapshot(task_id, run_id, "domain.materialize") == before_epochs


def test_seal_endpoint_bypasses_generic_http_idempotency_cache(
    app: AgentOSApplication,
) -> None:
    task_id, run_id = _running_task(app)
    path = f"/v1/tasks/{task_id}/domain-candidates:seal"
    shared_http_key = "same-http-key"

    with _running_server(app) as base:
        first_status, _ = _request_json(
            base,
            path,
            method="POST",
            body=_candidate_body(task_id, run_id),
            idempotency_key=shared_http_key,
        )
        second_status, second = _request_json(
            base,
            path,
            method="POST",
            body=_candidate_body(task_id, run_id, patch=_patch("type:ShellCompany")),
            idempotency_key=shared_http_key,
        )

    assert first_status == 201
    assert second_status == 409
    assert second["error"] == "CandidateIdempotencyConflict"


@pytest.mark.parametrize(
    ("case", "expected_status"),
    (("wrong-path", 403), ("halted", 403), ("forbidden-channel", 400)),
)
def test_seal_endpoint_maps_typed_failures(
    app: AgentOSApplication,
    case: str,
    expected_status: int,
) -> None:
    task_id, run_id = _running_task(app)
    path_task_id = task_id
    body = _candidate_body(task_id, run_id)
    if case == "wrong-path":
        path_task_id = "task:wrong"
    elif case == "halted":
        app.correction.correct("task", task_id, "operator halt")
    else:
        body["requested_channel"] = "K"

    with _running_server(app) as base:
        status, _ = _request_json(
            base,
            f"/v1/tasks/{path_task_id}/domain-candidates:seal",
            method="POST",
            body=body,
        )

    assert status == expected_status


def test_seal_endpoint_maps_stale_parent_to_conflict(
    app: AgentOSApplication,
) -> None:
    task_id, run_id = _running_task(app)
    path = f"/v1/tasks/{task_id}/domain-candidates:seal"

    with _running_server(app) as base:
        _, first = _request_json(
            base,
            path,
            method="POST",
            body=_candidate_body(task_id, run_id),
            idempotency_key="http-1",
        )
        _, _ = _request_json(
            base,
            path,
            method="POST",
            body=_candidate_body(
                task_id,
                run_id,
                parent_candidate_digest=first["candidate_digest"],
            ),
            idempotency_key="http-2",
        )
        status, payload = _request_json(
            base,
            path,
            method="POST",
            body=_candidate_body(
                task_id,
                run_id,
                parent_candidate_digest=first["candidate_digest"],
                mechanism_digest=DIGEST_D,
            ),
            idempotency_key="http-3",
        )

    assert status == 409
    assert payload["error"] == "CandidateConcurrentWrite"


def test_list_endpoint_rejects_cross_tenant_and_missing_task(
    app: AgentOSApplication,
) -> None:
    task_id, _ = _running_task(app)
    app.principal = PrincipalIdentity(
        principal_id="user:other",
        tenant_id="tenant:other",
        workspace_id="workspace:other",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )

    with _running_server(app) as base:
        cross_status, _ = _request_json(
            base,
            f"/v1/tasks/{task_id}/domain-candidates",
        )
        missing_status, _ = _request_json(
            base,
            "/v1/tasks/task:missing/domain-candidates",
        )

    assert cross_status == 403
    assert missing_status == 404
