from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, Thread
from typing import Any

import pytest

from agent_os_contracts import (
    AgentRun,
    CandidateEvaluationDisposition,
    CandidateEvaluationDraft,
    CandidateEvaluatorIdentity,
    CandidateEvaluatorKind,
    CandidateProvenance,
    CandidatePromotionCommand,
    CandidatePromotionDisposition,
    CandidateWriteChannel,
    CapabilityGrant,
    CapabilityGrantStatus,
    Commitment,
    CorrectionEpochVector,
    DomainCandidate,
    DomainCandidateDraft,
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
    TaskStatus,
    WorkflowGraph,
    content_digest,
    domain_candidate_digest,
)
from agent_os_core import CorrectionAuthority
from agent_os_core.errors import (
    CandidateConcurrentWrite,
    CandidatePromotionDenied,
    CandidatePromotionNotFound,
    TaskNotFoundError,
)
from agent_os_core.materialization import SEALER_ID
from agent_os_core.materialization_evaluation_persistence import (
    CandidateEvaluationRecordRequest,
    SQLiteCandidateEvaluationStore,
    candidate_evaluation_idempotency_key,
    candidate_evaluation_payload_digest,
)
from agent_os_core.materialization_ledger import SQLiteAdaptationLedger
from agent_os_core.materialization_promotion import (
    PROMOTION_CAPABILITY,
    DomainCandidatePromotionService,
)
from agent_os_core.materialization_promotion_persistence import (
    CandidatePromotionStore,
    SQLiteCandidatePromotionStore,
)
from agent_os_core.materialization_promotion_policy import (
    PromotionPolicyRegistry,
    PromotionPolicyV1,
)
from agent_os_core.task_aggregate import TaskAggregate


NOW = datetime(2026, 7, 15, 16, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def _budget() -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal("1.00"),
        max_duration_seconds=300,
        max_provider_tokens=0,
        max_tool_calls=0,
    )


def _candidate(
    *, outcome: MaterializationOutcome = MaterializationOutcome.CANDIDATE
) -> DomainCandidate:
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
    provenance = CandidateProvenance(
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
        expires_at=NOW + timedelta(days=1),
    )
    draft = DomainCandidateDraft(
        task_id="task:candidate",
        materialization_run_id="run:candidate",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        submitted_by="principal:builder",
        mechanism_digest=DIGEST_B,
        source_snapshot_digest=DIGEST_C,
        requested_channel=CandidateWriteChannel.R,
        outcome=outcome,
        representation_patch=patch
        if outcome is MaterializationOutcome.CANDIDATE
        else None,
        provenance=(provenance,) if outcome is MaterializationOutcome.CANDIDATE else (),
        submitted_at=NOW,
    )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "candidate_id": "domain-candidate:1",
        "candidate_version": 1,
        "payload_digest": content_digest(draft),
        "idempotency_key": content_digest({"candidate": "1", "outcome": outcome}),
        "sealed_by": SEALER_ID,
        "sealed_at": NOW,
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=1,
            run_epoch=1,
            capability_epoch=1,
        ),
        "draft": draft,
    }
    return DomainCandidate(
        **payload,
        candidate_digest=domain_candidate_digest(payload),
    )


class StaticCandidateStore:
    def __init__(self, candidate: DomainCandidate) -> None:
        self.candidate = candidate

    def get_by_digest(
        self, tenant_id: str, workspace_id: str, candidate_digest: str
    ) -> DomainCandidate | None:
        if (
            tenant_id == self.candidate.draft.tenant_id
            and workspace_id == self.candidate.draft.workspace_id
            and candidate_digest == self.candidate.candidate_digest
        ):
            return self.candidate
        return None


class StaticTasks:
    def __init__(self, tasks: Mapping[str, TaskAggregate]) -> None:
        self.tasks = dict(tasks)

    def get_task(self, task_id: str) -> TaskAggregate:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(task_id) from exc


def _promotion_task(
    *,
    actor: str = "principal:promoter",
    task_id: str = "task:promotion",
    run_id: str = "run:promotion",
    authority_scopes: tuple[str, ...] = ("domain.candidate.promote",),
    task_status: TaskStatus = TaskStatus.RUNNING,
    run_status: RunStatus = RunStatus.RUNNING,
) -> TaskAggregate:
    goal = Goal(
        goal_id="goal:promotion",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by=actor,
        created_at=NOW,
        statement="Decide candidate promotion",
    )
    commitment = Commitment(
        commitment_id="commitment:promotion",
        task_id=task_id,
        goal_id=goal.goal_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        accepted_by=actor,
        accepted_at=NOW,
        deliverables=("immutable decision",),
        acceptance_criteria=("policy-bound",),
        authority_scopes=authority_scopes,
        budget=_budget(),
        risk_tier=1,
        exit_conditions=("decision appended",),
        expires_at=NOW + timedelta(hours=1),
    )
    workflow = WorkflowGraph(
        workflow_id="workflow:promotion",
        version=1,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by=actor,
        created_at=NOW,
        policy_version="policy:1",
        evaluator_refs=("evaluator:promotion-policy:1",),
        nodes=(
            NodeSpec(
                node_id="decide",
                kind=NodeKind.TOOL,
                capability=PROMOTION_CAPABILITY,
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="decide", target="done"),),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="expected:promotion",
        task_id=task_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator_type="promotion-policy",
        evaluator_version="1",
        evidence_requirements=("complete receipt chain",),
        failure_semantics=("defer",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )
    run = AgentRun(
        run_id=run_id,
        task_id=task_id,
        commitment_id=commitment.commitment_id,
        workflow_id=workflow.workflow_id,
        workflow_version=workflow.version,
        workflow_digest=workflow.canonical_digest(),
        expected_outcome_id=expected.expected_outcome_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        status=run_status,
        created_at=NOW,
        provider_profile_id="provider-profile:unbound",
        policy_version="policy:1",
    )
    return TaskAggregate(
        task_id=task_id,
        sequence=3,
        status=task_status,
        goal=goal,
        commitment=commitment,
        workflow=workflow,
        expected_outcome=expected,
        run=run,
        last_event_id="event:3",
    )


def _grant(
    principal: PrincipalIdentity,
    **updates: Any,
) -> CapabilityGrant:
    values: dict[str, Any] = {
        "grant_id": "grant:domain.candidate.promote",
        "principal_id": principal.principal_id,
        "tenant_id": principal.tenant_id,
        "workspace_id": principal.workspace_id,
        "capability_id": PROMOTION_CAPABILITY,
        "capability_version": "1",
        "max_risk_tier": 1,
        "budget_limit": _budget(),
        "status": CapabilityGrantStatus.ACTIVE,
        "granted_by": "system:test",
        "granted_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(updates)
    return CapabilityGrant(**values)


def _append_receipt(
    store: SQLiteCandidateEvaluationStore,
    candidate: DomainCandidate,
    index: int,
) -> Any:
    latest = store.latest("tenant:1", "workspace:1", candidate.candidate_digest)
    draft = CandidateEvaluationDraft(
        candidate_digest=candidate.candidate_digest,
        candidate_task_id=candidate.draft.task_id,
        evaluation_task_id=f"task:evaluation:{index}",
        evaluation_run_id=f"run:evaluation:{index}",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator=CandidateEvaluatorIdentity(
            evaluator_id=f"principal:evaluator:{index}",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="contract-check",
            evaluator_version="1",
            implementation_digest=content_digest({"implementation": index}),
            configuration_digest=content_digest({"configuration": index}),
        ),
        evidence_bundle_digest=content_digest({"evidence": index}),
        evidence_refs=(f"artifact:evidence:{index}",),
        disposition=CandidateEvaluationDisposition.EVALUATOR_PASS,
        score=0.9,
        confidence=0.8,
        parent_evaluation_digest=(
            latest.evaluation_digest if latest is not None else None
        ),
        submitted_at=NOW,
    )
    contract_digest = content_digest({"contract": "ADM-P2"})
    recorder = f"principal:recorder:{index}"
    request = CandidateEvaluationRecordRequest(
        evaluation_id=f"candidate-evaluation:{index}",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        candidate_digest=candidate.candidate_digest,
        idempotency_key=candidate_evaluation_idempotency_key(
            draft, contract_digest, recorder
        ),
        payload_digest=candidate_evaluation_payload_digest(
            draft, contract_digest, recorder
        ),
        recorded_by=recorder,
        recorded_at=NOW,
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=1,
            run_epoch=1,
            capability_epoch=1,
        ),
        evaluation_contract_digest=contract_digest,
        draft=draft,
    )
    return store.append(
        request,
        expected_parent_digest=latest.evaluation_digest if latest else None,
    )


@dataclass
class Context:
    ledger: SQLiteAdaptationLedger
    evaluations: SQLiteCandidateEvaluationStore
    promotions: SQLiteCandidatePromotionStore
    candidate: DomainCandidate
    candidate_store: StaticCandidateStore
    task: TaskAggregate
    tasks: StaticTasks
    correction: CorrectionAuthority
    principal: PrincipalIdentity
    grant: CapabilityGrant
    service: DomainCandidatePromotionService


def _build_context(*, receipt_count: int = 1) -> Context:
    ledger = SQLiteAdaptationLedger()
    evaluations = SQLiteCandidateEvaluationStore(ledger=ledger)
    policies = PromotionPolicyRegistry((PromotionPolicyV1(),))
    promotions = SQLiteCandidatePromotionStore(ledger, policies)
    candidate = _candidate()
    for index in range(1, receipt_count + 1):
        _append_receipt(evaluations, candidate, index)
    candidate_store = StaticCandidateStore(candidate)
    task = _promotion_task()
    tasks = StaticTasks({task.task_id: task})
    correction = CorrectionAuthority()
    principal = PrincipalIdentity(
        principal_id="principal:promoter",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )
    grant = _grant(principal)
    service = DomainCandidatePromotionService(
        tasks,
        correction,
        candidate_store,
        evaluations,
        promotions,
        {PROMOTION_CAPABILITY: grant},
        policies,
        clock=lambda: NOW,
    )
    return Context(
        ledger,
        evaluations,
        promotions,
        candidate,
        candidate_store,
        task,
        tasks,
        correction,
        principal,
        grant,
        service,
    )


@pytest.fixture
def context() -> Iterator[Context]:
    value = _build_context()
    yield value
    value.promotions.close()
    value.evaluations.close()
    value.ledger.close()


def _command(context: Context, **updates: Any) -> CandidatePromotionCommand:
    receipts = context.evaluations.list_for_candidate(
        "tenant:1", "workspace:1", context.candidate.candidate_digest
    )
    values: dict[str, Any] = {
        "candidate_digest": context.candidate.candidate_digest,
        "candidate_task_id": context.candidate.draft.task_id,
        "promotion_task_id": context.task.task_id,
        "promotion_run_id": context.task.run.run_id if context.task.run else "missing",
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "expected_evaluation_head_digest": (
            receipts[-1].evaluation_digest if receipts else None
        ),
        "expected_parent_promotion_digest": None,
    }
    values.update(updates)
    return CandidatePromotionCommand(**values)


def _service(
    context: Context,
    *,
    task: TaskAggregate | None = None,
    principal: PrincipalIdentity | None = None,
    grant: CapabilityGrant | None | object = ...,
    correction: Any | None = None,
    promotions: CandidatePromotionStore | None = None,
    candidate: DomainCandidate | None = None,
) -> tuple[DomainCandidatePromotionService, PrincipalIdentity, StaticTasks]:
    actual_task = task or context.task
    actual_principal = principal or context.principal
    actual_grants: dict[str, CapabilityGrant] = {}
    if grant is ...:
        actual_grants[PROMOTION_CAPABILITY] = context.grant
    elif isinstance(grant, CapabilityGrant):
        actual_grants[PROMOTION_CAPABILITY] = grant
    tasks = StaticTasks({actual_task.task_id: actual_task})
    service = DomainCandidatePromotionService(
        tasks,
        correction or context.correction,
        StaticCandidateStore(candidate or context.candidate),
        context.evaluations,
        promotions or context.promotions,
        actual_grants,
        PromotionPolicyRegistry((PromotionPolicyV1(),)),
        clock=lambda: NOW,
    )
    return service, actual_principal, tasks


def _promotion_task_with_acceptor_mismatch() -> TaskAggregate:
    task = _promotion_task()
    assert task.commitment is not None
    return replace(
        task,
        commitment=task.commitment.model_copy(
            update={"accepted_by": "principal:other"}
        ),
    )


def test_decide_v1_defer_is_complete_chain_bound_and_non_mutating(
    context: Context,
) -> None:
    candidate_before = context.candidate.model_dump_json()
    receipts_before = context.evaluations.list_for_candidate(
        "tenant:1", "workspace:1", context.candidate.candidate_digest
    )
    tasks_before = dict(context.tasks.tasks)
    result = context.service.decide(
        context.principal,
        context.candidate.draft.task_id,
        context.candidate.candidate_digest,
        _command(context),
    )
    assert result.decision.disposition is CandidatePromotionDisposition.DEFER
    assert result.prior is None
    assert result.decision.evaluation_receipt_digests == tuple(
        receipt.evaluation_digest for receipt in receipts_before
    )
    assert context.candidate.model_dump_json() == candidate_before
    assert (
        context.evaluations.list_for_candidate(
            "tenant:1", "workspace:1", context.candidate.candidate_digest
        )
        == receipts_before
    )
    assert context.tasks.tasks == tasks_before


def test_decide_and_lists_require_exact_candidate_route(context: Context) -> None:
    with pytest.raises(CandidatePromotionNotFound):
        context.service.decide(
            context.principal,
            "task:wrong",
            context.candidate.candidate_digest,
            _command(context),
        )
    with pytest.raises(CandidatePromotionNotFound):
        context.service.list_decisions(
            context.principal,
            context.candidate.draft.task_id,
            DIGEST_A,
        )


def test_non_candidate_outcome_is_denied(context: Context) -> None:
    abstention = _candidate(outcome=MaterializationOutcome.ASK)
    service, principal, _ = _service(context, candidate=abstention)
    with pytest.raises(CandidatePromotionDenied, match="CANDIDATE"):
        service.decide(
            principal,
            abstention.draft.task_id,
            abstention.candidate_digest,
            CandidatePromotionCommand(
                **{
                    **_command(context).model_dump(mode="python"),
                    "candidate_digest": abstention.candidate_digest,
                }
            ),
        )


@pytest.mark.parametrize(
    "role", (PrincipalRole.WORKER, PrincipalRole.MODEL, PrincipalRole.PLUGIN)
)
def test_promoter_role_is_principal_or_tenant_admin_only(
    context: Context,
    role: PrincipalRole,
) -> None:
    principal = context.principal.model_copy(update={"role": role})
    service, _, _ = _service(context, principal=principal)
    with pytest.raises(CandidatePromotionDenied, match="role"):
        service.decide(
            principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _command(context),
        )


@pytest.mark.parametrize(
    "task",
    (
        _promotion_task(actor="principal:other"),
        _promotion_task_with_acceptor_mismatch(),
        _promotion_task(authority_scopes=("domain.candidate.promote@1",)),
        _promotion_task(task_status=TaskStatus.COMMITTED),
        _promotion_task(run_status=RunStatus.FAILED),
    ),
)
def test_promotion_task_ownership_scope_and_running_state_are_exact(
    context: Context,
    task: TaskAggregate,
) -> None:
    service, principal, _ = _service(context, task=task)
    with pytest.raises(CandidatePromotionDenied):
        service.decide(
            principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _command(context),
        )


@pytest.mark.parametrize(
    "grant_update",
    (
        None,
        {"status": CapabilityGrantStatus.REVOKED},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"capability_version": "2"},
        {"capability_id": "domain.candidate.promote@1"},
        {"principal_id": "principal:other"},
        {"workspace_id": "workspace:other"},
    ),
)
def test_exact_raw_capability_grant_is_required(
    context: Context,
    grant_update: dict[str, Any] | None,
) -> None:
    grant = (
        None if grant_update is None else context.grant.model_copy(update=grant_update)
    )
    service, principal, _ = _service(context, grant=grant)
    with pytest.raises(CandidatePromotionDenied, match="grant"):
        service.decide(
            principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _command(context),
        )


@pytest.mark.parametrize(
    "actor",
    (
        "principal:builder",
        SEALER_ID,
        "principal:evaluator:1",
        "principal:recorder:1",
    ),
)
def test_promoter_is_a_fifth_distinct_identity(context: Context, actor: str) -> None:
    principal = context.principal.model_copy(update={"principal_id": actor})
    task = _promotion_task(actor=actor)
    grant = _grant(principal)
    service, _, _ = _service(
        context,
        task=task,
        principal=principal,
        grant=grant,
    )
    with pytest.raises(CandidatePromotionDenied, match="distinct"):
        service.decide(
            principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _command(context),
        )


def test_promotion_task_and_run_must_differ_from_candidate_and_receipts(
    context: Context,
) -> None:
    for task in (
        _promotion_task(
            task_id="task:evaluation:1",
            run_id="run:promotion",
        ),
        _promotion_task(
            task_id="task:promotion",
            run_id="run:evaluation:1",
        ),
        _promotion_task(
            task_id="task:promotion",
            run_id=context.candidate.draft.materialization_run_id,
        ),
    ):
        service, principal, _ = _service(context, task=task)
        command = _command(
            context,
            promotion_task_id=task.task_id,
            promotion_run_id=task.run.run_id if task.run else "missing",
        )
        with pytest.raises(CandidatePromotionDenied, match="distinct"):
            service.decide(
                principal,
                context.candidate.draft.task_id,
                context.candidate.candidate_digest,
                command,
            )


def test_stale_or_caller_selected_receipt_head_is_rejected(context: Context) -> None:
    with pytest.raises(CandidateConcurrentWrite, match="head"):
        context.service.decide(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _command(context, expected_evaluation_head_digest=DIGEST_A),
        )


def test_c7_halt_and_epoch_drift_fail_closed(context: Context) -> None:
    context.correction.correct("capability", PROMOTION_CAPABILITY, "founder halt")
    with pytest.raises(CandidatePromotionDenied, match="halted"):
        context.service.decide(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _command(context),
        )

    class DriftCorrection:
        def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
            del task_id, run_id, capability_id
            return False

        def snapshot(
            self, task_id: str, run_id: str, capability_id: str
        ) -> CorrectionEpochVector:
            del task_id, run_id, capability_id
            return CorrectionEpochVector(task_epoch=1, run_epoch=1, capability_epoch=1)

        @contextmanager
        def guard_unchanged(self, task_id, run_id, capability_id, observed_epochs):  # type: ignore[no-untyped-def]
            del task_id, run_id, capability_id, observed_epochs
            yield False

    service, principal, _ = _service(context, correction=DriftCorrection())
    with pytest.raises(CandidatePromotionDenied, match="epoch"):
        service.decide(
            principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _command(context),
        )


class BlockingPromotionStore:
    def __init__(self, delegate: CandidatePromotionStore) -> None:
        self.delegate = delegate
        self.append_entered = Event()
        self.append_release = Event()

    def append(self, request):  # type: ignore[no-untyped-def]
        self.append_entered.set()
        if not self.append_release.wait(timeout=5):
            raise TimeoutError("promotion append was not released")
        return self.delegate.append(request)

    def list_decisions(self, tenant_id, workspace_id, candidate_digest):  # type: ignore[no-untyped-def]
        return self.delegate.list_decisions(tenant_id, workspace_id, candidate_digest)

    def list_priors(self, tenant_id, workspace_id, candidate_digest):  # type: ignore[no-untyped-def]
        return self.delegate.list_priors(tenant_id, workspace_id, candidate_digest)


def test_c7_guard_is_held_through_atomic_append(context: Context) -> None:
    blocking = BlockingPromotionStore(context.promotions)
    service, principal, _ = _service(context, promotions=blocking)
    decision_done = Event()
    correction_done = Event()
    errors: list[BaseException] = []

    def decide() -> None:
        try:
            service.decide(
                principal,
                context.candidate.draft.task_id,
                context.candidate.candidate_digest,
                _command(context),
            )
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)
        finally:
            decision_done.set()

    def correct() -> None:
        context.correction.correct(
            "capability", PROMOTION_CAPABILITY, "interleaving correction"
        )
        correction_done.set()

    decision_thread = Thread(target=decide)
    decision_thread.start()
    assert blocking.append_entered.wait(timeout=2)
    correction_thread = Thread(target=correct)
    correction_thread.start()
    assert not correction_done.wait(timeout=0.1)
    blocking.append_release.set()
    assert decision_done.wait(timeout=2)
    assert correction_done.wait(timeout=2)
    decision_thread.join(timeout=2)
    correction_thread.join(timeout=2)
    assert errors == []
