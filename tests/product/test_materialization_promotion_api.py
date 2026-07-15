from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import ThreadingHTTPServer
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
    CandidateProvenance,
    CandidateWriteChannel,
    CapabilityGrant,
    CapabilityGrantStatus,
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
from agent_os_core import (
    EVALUATION_CAPABILITY,
    PROMOTION_CAPABILITY,
    candidate_source_snapshot_digest,
)


NOW = datetime(2026, 7, 15, 17, 0, tzinfo=timezone.utc)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


@contextmanager
def _running_server(app: AgentOSApplication) -> Iterator[str]:
    handler = type("PromotionHandler", (Handler,), {"application": app})
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
    http_key: str = "promotion-http-key",
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


def _principal(
    principal_id: str,
    *,
    role: PrincipalRole = PrincipalRole.PRINCIPAL,
) -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id=principal_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        role=role,
        authenticated_at=NOW,
    )


def _budget() -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal("1.00"),
        max_duration_seconds=300,
        max_provider_tokens=0,
        max_tool_calls=0,
    )


def _grant(principal: PrincipalIdentity, capability_id: str) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id=f"grant:{principal.principal_id}:{capability_id}",
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        capability_id=capability_id,
        capability_version="1",
        max_risk_tier=1,
        budget_limit=_budget(),
        status=CapabilityGrantStatus.ACTIVE,
        granted_by="system:test",
        granted_at=NOW - timedelta(minutes=1),
        expires_at=FAR_FUTURE,
    )


def _workflow(label: str, actor: str, evaluator_type: str) -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id=f"workflow:{label}",
        version=1,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by=actor,
        created_at=NOW,
        policy_version="policy:1",
        evaluator_refs=(f"evaluator:{evaluator_type}:1",),
        nodes=(
            NodeSpec(
                node_id="inspect",
                kind=NodeKind.TOOL,
                capability="workspace.read",
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="inspect", target="done"),),
    )


def _create_running_task(
    app: AgentOSApplication,
    *,
    label: str,
    actor: str,
    authority_scope: str,
    evaluator_type: str,
) -> tuple[str, str]:
    goal = Goal(
        goal_id=f"goal:{label}",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by=actor,
        created_at=NOW,
        statement=f"Run {label}",
    )
    created = app.tasks.create_task(goal)
    commitment = Commitment(
        commitment_id=f"commitment:{label}",
        task_id=created.task_id,
        goal_id=goal.goal_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        accepted_by=actor,
        accepted_at=NOW,
        deliverables=(label,),
        acceptance_criteria=("typed immutable output",),
        authority_scopes=(authority_scope,),
        budget=_budget(),
        risk_tier=1,
        exit_conditions=("complete or defer",),
        expires_at=FAR_FUTURE,
    )
    expected = ExpectedOutcome(
        expected_outcome_id=f"expected:{label}",
        task_id=created.task_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator_type=evaluator_type,
        evaluator_version="1",
        evidence_requirements=("immutable evidence",),
        failure_semantics=("defer",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )
    app.tasks.commit_task(
        created.task_id,
        commitment,
        _workflow(label, actor, evaluator_type),
        expected,
    )
    started = app.tasks.start_run(created.task_id)
    assert started.run is not None
    running = app.tasks.update_run_status(
        created.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_QUEUED,
    )
    assert running.run is not None
    return created.task_id, running.run.run_id


def _seed_candidate(app: AgentOSApplication):  # type: ignore[no-untyped-def]
    task_id, run_id = _create_running_task(
        app,
        label="candidate",
        actor=app.principal.principal_id,
        authority_scope="domain.materialize",
        evaluator_type="materialization-contract",
    )
    patch = RepresentationPatch(
        operations=(
            RepresentationPatchOperation(
                operation_id="op:1",
                operation="UPSERT",
                assertion_id="assertion:1",
                subject_ref="entity:acme",
                predicate="rdf:type",
                object_ref="type:Company",
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("artifact:filing",),
            ),
        )
    )
    provenance = (
        CandidateProvenance(
            source_id="source:filing",
            source_ref="artifact:filing",
            source_type="regulatory-filing",
            source_digest=DIGEST_A,
            accessed_at=NOW,
            effective_at=NOW - timedelta(days=1),
            license_or_terms_id="terms:public",
            permitted_use="analysis",
            redistribution_allowed=False,
            output_patch_digest=patch.patch_digest(),
            expires_at=FAR_FUTURE,
        ),
    )
    return app.seal_domain_candidate(
        task_id,
        {
            "task_id": task_id,
            "materialization_run_id": run_id,
            "tenant_id": "tenant:1",
            "workspace_id": "workspace:1",
            "submitted_by": app.principal.principal_id,
            "mechanism_digest": DIGEST_B,
            "source_snapshot_digest": candidate_source_snapshot_digest(provenance),
            "requested_channel": CandidateWriteChannel.R,
            "outcome": MaterializationOutcome.CANDIDATE,
            "representation_patch": patch,
            "provenance": provenance,
            "submitted_at": NOW,
        },
    )


class ExplodingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):  # type: ignore[no-untyped-def]
        del request
        self.calls += 1
        raise AssertionError("promotion must not call provider")


@dataclass
class Environment:
    database: Path
    workspace: Path
    builder_app: AgentOSApplication
    recorder_app: AgentOSApplication
    promoter_app: AgentOSApplication
    candidate: Any
    receipt: Any
    promotion_task_id: str
    promotion_run_id: str
    promoter: PrincipalIdentity
    promotion_grant: CapabilityGrant

    def close(self) -> None:
        for app in (self.promoter_app, self.recorder_app, self.builder_app):
            app.candidate_promotions.close()
            app.evaluation_receipts.close()
            app.candidates.close()
            app.store.close()


def _build_environment(
    tmp_path: Path,
    *,
    disposition: CandidateEvaluationDisposition = (
        CandidateEvaluationDisposition.EVALUATOR_PASS
    ),
    promoter_id: str = "principal:promoter",
) -> Environment:
    database = tmp_path / "state" / "agent-os.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)

    builder = _principal("principal:builder")
    builder_app = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=builder,
    )
    candidate = _seed_candidate(builder_app)

    recorder = _principal("principal:recorder", role=PrincipalRole.WORKER)
    evaluation_grant = _grant(recorder, EVALUATION_CAPABILITY)
    recorder_app = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=recorder,
        evaluation_grant=evaluation_grant,
    )
    evaluation_task_id, evaluation_run_id = _create_running_task(
        recorder_app,
        label="evaluation",
        actor=recorder.principal_id,
        authority_scope=EVALUATION_CAPABILITY,
        evaluator_type="candidate-contract",
    )
    decisive = disposition in {
        CandidateEvaluationDisposition.EVALUATOR_PASS,
        CandidateEvaluationDisposition.EVALUATOR_FAIL,
    }
    evaluation = CandidateEvaluationDraft(
        candidate_digest=candidate.candidate_digest,
        candidate_task_id=candidate.draft.task_id,
        evaluation_task_id=evaluation_task_id,
        evaluation_run_id=evaluation_run_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator=CandidateEvaluatorIdentity(
            evaluator_id="principal:evaluator",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="candidate-contract",
            evaluator_version="1",
            implementation_digest=DIGEST_C,
            configuration_digest=DIGEST_D,
        ),
        evidence_bundle_digest=DIGEST_A,
        evidence_refs=("artifact:evidence",),
        disposition=disposition,
        score=0.9 if decisive else None,
        confidence=0.8,
        submitted_at=NOW,
    )
    receipt = recorder_app.record_domain_candidate_evaluation(
        candidate.draft.task_id,
        candidate.candidate_digest,
        evaluation.model_dump(mode="python"),
    )

    promoter = _principal(promoter_id)
    promotion_grant = _grant(promoter, PROMOTION_CAPABILITY)
    promoter_app = AgentOSApplication(
        database=database,
        workspace=workspace,
        principal=promoter,
        promotion_grant=promotion_grant,
    )
    promotion_task_id, promotion_run_id = _create_running_task(
        promoter_app,
        label=f"promotion-{promoter_id}",
        actor=promoter.principal_id,
        authority_scope=PROMOTION_CAPABILITY,
        evaluator_type="promotion-policy",
    )
    return Environment(
        database,
        workspace,
        builder_app,
        recorder_app,
        promoter_app,
        candidate,
        receipt,
        promotion_task_id,
        promotion_run_id,
        promoter,
        promotion_grant,
    )


def _path(environment: Environment, suffix: str = "promotions:decide") -> str:
    return (
        f"/v1/tasks/{environment.candidate.draft.task_id}/domain-candidates/"
        f"{environment.candidate.candidate_digest}/{suffix}"
    )


def _body(environment: Environment, **updates: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "promotion_task_id": environment.promotion_task_id,
        "promotion_run_id": environment.promotion_run_id,
        "expected_evaluation_head_digest": environment.receipt.evaluation_digest,
        "expected_parent_promotion_digest": None,
    }
    values.update(updates)
    return values


@pytest.mark.parametrize(
    ("disposition", "expected_observation"),
    (
        (CandidateEvaluationDisposition.EVALUATOR_PASS, None),
        (
            CandidateEvaluationDisposition.EVALUATOR_FAIL,
            "RECORDED_EVALUATOR_FAIL_UNADJUDICATED",
        ),
    ),
)
def test_http_v1_defer_replays_lists_and_restarts_without_side_effects(
    tmp_path: Path,
    disposition: CandidateEvaluationDisposition,
    expected_observation: str | None,
) -> None:
    environment = _build_environment(tmp_path, disposition=disposition)
    app = environment.promoter_app
    provider = ExplodingProvider()
    app.provider = provider  # type: ignore[assignment]
    before_events = app.store.read(environment.promotion_task_id)
    before_candidate = app.candidates.get_by_digest(
        "tenant:1", "workspace:1", environment.candidate.candidate_digest
    )
    before_receipts = app.evaluation_receipts.list_for_candidate(
        "tenant:1", "workspace:1", environment.candidate.candidate_digest
    )
    before_workspace = tuple(
        sorted(
            path.relative_to(app.sandbox.root)
            for path in app.sandbox.root.rglob("*")
            if path.is_file()
        )
    )
    try:
        with _running_server(app) as base:
            first_status, first = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(environment),
            )
            replay_status, replay = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(environment),
            )
            list_status, listed = _request_json(
                base,
                _path(environment, "promotions"),
            )
            prior_status, priors = _request_json(
                base,
                _path(environment, "domain-priors"),
            )

        assert first_status == replay_status == 201
        assert first == replay
        assert first["decision"]["disposition"] == "DEFER"
        assert first["prior"] is None
        if expected_observation is not None:
            assert expected_observation in first["decision"]["reason_codes"]
        assert list_status == prior_status == 200
        assert listed["promotions"] == [first["decision"]]
        assert priors["priors"] == []
        assert app.store.read(environment.promotion_task_id) == before_events
        assert (
            app.candidates.get_by_digest(
                "tenant:1", "workspace:1", environment.candidate.candidate_digest
            )
            == before_candidate
        )
        assert (
            app.evaluation_receipts.list_for_candidate(
                "tenant:1", "workspace:1", environment.candidate.candidate_digest
            )
            == before_receipts
        )
        assert (
            tuple(
                sorted(
                    path.relative_to(app.sandbox.root)
                    for path in app.sandbox.root.rglob("*")
                    if path.is_file()
                )
            )
            == before_workspace
        )
        assert provider.calls == 0

        restarted = AgentOSApplication(
            database=environment.database,
            workspace=environment.workspace,
            principal=environment.promoter,
            promotion_grant=environment.promotion_grant,
        )
        try:
            with _running_server(restarted) as base:
                restart_status, restart_list = _request_json(
                    base,
                    _path(environment, "promotions"),
                )
            assert restart_status == 200
            assert restart_list["promotions"] == [first["decision"]]
        finally:
            restarted.candidate_promotions.close()
            restarted.evaluation_receipts.close()
            restarted.candidates.close()
            restarted.store.close()
    finally:
        environment.close()


@pytest.mark.parametrize(
    "forbidden",
    (
        {"disposition": "PROMOTE"},
        {"threshold": 0.9},
        {"evaluation_receipt_digests": (DIGEST_A,)},
        {"policy_version": "caller"},
        {"prior": {"state": "ACTIVE"}},
        {"activate": True},
    ),
)
def test_http_rejects_caller_decision_semantics(
    tmp_path: Path,
    forbidden: dict[str, Any],
) -> None:
    environment = _build_environment(tmp_path)
    try:
        with _running_server(environment.promoter_app) as base:
            status, _ = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(environment, **forbidden),
            )
        assert status == 400
    finally:
        environment.close()


def test_decide_endpoint_bypasses_generic_http_idempotency_cache(
    tmp_path: Path,
) -> None:
    environment = _build_environment(tmp_path)
    try:
        with _running_server(environment.promoter_app) as base:
            first_status, _ = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(environment),
                http_key="same-key",
            )
            second_status, second = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(environment, disposition="PROMOTE"),
                http_key="same-key",
            )
        assert first_status == 201
        assert second_status == 400
        assert second["error"] == "ValidationError"
    finally:
        environment.close()


def test_http_maps_stale_head_and_parent_to_conflict(tmp_path: Path) -> None:
    environment = _build_environment(tmp_path)
    try:
        with _running_server(environment.promoter_app) as base:
            stale_head_status, _ = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(environment, expected_evaluation_head_digest=DIGEST_A),
            )
            stale_parent_status, _ = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(
                    environment,
                    expected_parent_promotion_digest=DIGEST_A,
                ),
            )
        assert stale_head_status == 409
        assert stale_parent_status == 409
    finally:
        environment.close()


def test_http_rejects_promoter_collision_with_receipt_recorder(
    tmp_path: Path,
) -> None:
    environment = _build_environment(tmp_path, promoter_id="principal:recorder")
    try:
        with _running_server(environment.promoter_app) as base:
            status, body = _request_json(
                base,
                _path(environment),
                method="POST",
                body=_body(environment),
            )
        assert status == 403
        assert body["error"] == "CandidatePromotionDenied"
    finally:
        environment.close()
