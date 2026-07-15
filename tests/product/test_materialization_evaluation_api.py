from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from agent_os_contracts import (
    CandidateEvaluationDisposition,
    CandidateEvaluationDraft,
    CandidateEvaluatorIdentity,
    CandidateEvaluatorKind,
    PrincipalIdentity,
    PrincipalRole,
)
from tests.product.test_materialization_evaluation_service import (
    DIGEST_A,
    DIGEST_C,
    DIGEST_D,
    NOW,
    _create_running_task,
    _grant,
    _seed_candidate,
)


@contextmanager
def _running_server(app: AgentOSApplication) -> Iterator[str]:
    handler = type("EvaluationHandler", (Handler,), {"application": app})
    server = __import__("http.server").server.ThreadingHTTPServer(
        ("127.0.0.1", 0), handler
    )
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
    http_key: str = "evaluation-http-key",
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Idempotency-Key": http_key},
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


def _principal(principal_id: str) -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id=principal_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        role=PrincipalRole.WORKER,
        authenticated_at=NOW,
    )


def _evaluation_body(
    candidate,
    evaluation_task_id: str,
    evaluation_run_id: str,
    **updates: Any,
) -> dict[str, Any]:
    draft = CandidateEvaluationDraft(
        candidate_digest=candidate.candidate_digest,
        candidate_task_id=candidate.draft.task_id,
        evaluation_task_id=evaluation_task_id,
        evaluation_run_id=evaluation_run_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator=CandidateEvaluatorIdentity(
            evaluator_id="evaluator:programmatic:http",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="candidate-contract",
            evaluator_version="1",
            implementation_digest=DIGEST_C,
            configuration_digest=DIGEST_D,
        ),
        evidence_bundle_digest=DIGEST_A,
        evidence_refs=("external://evidence/http",),
        disposition=CandidateEvaluationDisposition.EVALUATOR_PASS,
        score=0.9,
        confidence=0.8,
        submitted_at=NOW,
    )
    values = draft.model_dump(mode="json")
    values.update(updates)
    return values


@pytest.fixture
def applications(tmp_path: Path):
    database = tmp_path / "state" / "agent-os.sqlite3"
    database.parent.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    builder = _principal("principal:builder")
    recorder = _principal("principal:recorder")
    builder_app = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=builder,
    )
    candidate = _seed_candidate(
        builder_app.tasks,
        builder_app.correction,
        builder_app.candidates,
    )
    evaluation_grant = _grant(recorder)
    evaluator_app = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=recorder,
        evaluation_grant=evaluation_grant,
    )
    evaluation_task_id, evaluation_run_id = _create_running_task(
        evaluator_app.tasks,
        label="http-evaluation",
        actor=recorder.principal_id,
        authority_scope="domain.candidate.evaluate",
        evaluator_type="candidate-contract",
    )
    yield (
        builder_app,
        evaluator_app,
        candidate,
        evaluation_task_id,
        evaluation_run_id,
        database,
        workspace,
        recorder,
        evaluation_grant,
    )
    for app in (evaluator_app, builder_app):
        app.evaluation_receipts.close()
        app.candidates.close()
        app.store.close()


def test_http_records_lists_and_restarts_without_mutating_product_state(
    applications,
) -> None:
    (
        _,
        evaluator_app,
        candidate,
        task_id,
        run_id,
        database,
        workspace,
        recorder,
        grant,
    ) = applications
    path = (
        f"/v1/tasks/{candidate.draft.task_id}/domain-candidates/"
        f"{candidate.candidate_digest}/evaluations:record"
    )
    before_events = evaluator_app.store.read(task_id)
    before_candidate = evaluator_app.candidates.get_by_digest(
        "tenant:1", "workspace:1", candidate.candidate_digest
    )
    before_workspace = tuple(
        sorted(
            item.relative_to(evaluator_app.sandbox.root)
            for item in evaluator_app.sandbox.root.rglob("*")
            if item.is_file()
        )
    )

    with _running_server(evaluator_app) as base:
        status, receipt = _request_json(
            base,
            path,
            method="POST",
            body=_evaluation_body(candidate, task_id, run_id),
        )
        listed_status, listed = _request_json(
            base,
            path.removesuffix(":record"),
        )

    assert status == 201
    assert listed_status == 200
    assert receipt["recorded_by"] == recorder.principal_id
    assert [item["evaluation_digest"] for item in listed["evaluations"]] == [
        receipt["evaluation_digest"]
    ]
    assert evaluator_app.store.read(task_id) == before_events
    assert (
        evaluator_app.candidates.get_by_digest(
            "tenant:1", "workspace:1", candidate.candidate_digest
        )
        == before_candidate
    )
    assert (
        tuple(
            sorted(
                item.relative_to(evaluator_app.sandbox.root)
                for item in evaluator_app.sandbox.root.rglob("*")
                if item.is_file()
            )
        )
        == before_workspace
    )

    restarted = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=recorder,
        evaluation_grant=grant,
    )
    try:
        with _running_server(restarted) as base:
            restart_status, restarted_list = _request_json(
                base,
                path.removesuffix(":record"),
            )
        assert restart_status == 200
        assert (
            restarted_list["evaluations"][0]["evaluation_digest"]
            == receipt["evaluation_digest"]
        )
    finally:
        restarted.evaluation_receipts.close()
        restarted.candidates.close()
        restarted.store.close()


def test_record_endpoint_bypasses_generic_http_idempotency_cache(
    applications,
) -> None:
    _, app, candidate, task_id, run_id, *_ = applications
    path = (
        f"/v1/tasks/{candidate.draft.task_id}/domain-candidates/"
        f"{candidate.candidate_digest}/evaluations:record"
    )
    body = _evaluation_body(candidate, task_id, run_id)
    changed = dict(body)
    changed["score"] = 0.1

    with _running_server(app) as base:
        first_status, _ = _request_json(
            base, path, method="POST", body=body, http_key="same-http-key"
        )
        second_status, second = _request_json(
            base, path, method="POST", body=changed, http_key="same-http-key"
        )

    assert first_status == 201
    assert second_status == 409
    assert second["error"] == "CandidateIdempotencyConflict"


def test_record_endpoint_rejects_path_override_and_missing_candidate(
    applications,
) -> None:
    _, app, candidate, task_id, run_id, *_ = applications
    body = _evaluation_body(candidate, task_id, run_id)
    body["candidate_task_id"] = "task:override"
    valid_path = (
        f"/v1/tasks/{candidate.draft.task_id}/domain-candidates/"
        f"{candidate.candidate_digest}/evaluations:record"
    )
    missing_path = (
        f"/v1/tasks/{candidate.draft.task_id}/domain-candidates/"
        f"{'f' * 64}/evaluations:record"
    )

    with _running_server(app) as base:
        override_status, _ = _request_json(base, valid_path, method="POST", body=body)
        missing_body = _evaluation_body(candidate, task_id, run_id)
        missing_body["candidate_digest"] = "f" * 64
        missing_status, _ = _request_json(
            base, missing_path, method="POST", body=missing_body
        )

    assert override_status == 403
    assert missing_status == 404
