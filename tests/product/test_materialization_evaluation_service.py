from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, Thread
from typing import Any, Iterator

import pytest

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
    TaskEventType,
    WorkflowGraph,
)
from agent_os_core import CorrectionAuthority, SQLiteTaskEventStore, TaskService
from agent_os_core.errors import (
    CandidateEvaluationDenied,
    CandidateEvaluationNotFound,
    CandidateEvaluationScopeMismatch,
)
from agent_os_core.materialization import (
    DomainCandidateSealer,
    candidate_source_snapshot_digest,
)
from agent_os_core.materialization_evaluation import (
    EVALUATION_CAPABILITY,
    DomainCandidateEvaluationRecorder,
    evaluation_contract_digest,
)
from agent_os_core.materialization_evaluation_persistence import (
    SQLiteCandidateEvaluationStore,
)
from agent_os_core.materialization_persistence import SQLiteCandidateStore


NOW = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


class DeterministicIdFactory:
    def __init__(self) -> None:
        self._counts: defaultdict[str, int] = defaultdict(int)

    def __call__(self, kind: str) -> str:
        self._counts[kind] += 1
        return f"{kind}-{self._counts[kind]}"


class ScriptedCorrectionAuthority:
    def __init__(self, snapshots: tuple[CorrectionEpochVector, ...]) -> None:
        self._snapshots = iter(snapshots)

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
        assert task_id and run_id and capability_id == EVALUATION_CAPABILITY
        return False

    def snapshot(
        self, task_id: str, run_id: str, capability_id: str
    ) -> CorrectionEpochVector:
        assert task_id and run_id and capability_id == EVALUATION_CAPABILITY
        return next(self._snapshots)

    @contextmanager
    def guard_unchanged(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
        observed_epochs: CorrectionEpochVector,
    ) -> Iterator[bool]:
        yield self.snapshot(task_id, run_id, capability_id) == observed_epochs


class BlockingEvaluationStore(SQLiteCandidateEvaluationStore):
    def __init__(self) -> None:
        super().__init__()
        self.append_entered = Event()
        self.append_release = Event()

    def append(self, request, *, expected_parent_digest):
        self.append_entered.set()
        if not self.append_release.wait(timeout=5):
            raise TimeoutError("evaluation append was not released")
        return super().append(request, expected_parent_digest=expected_parent_digest)


@dataclass(frozen=True)
class EvaluationContext:
    task_store: SQLiteTaskEventStore
    tasks: TaskService
    correction: CorrectionAuthority
    candidate_store: SQLiteCandidateStore
    evaluation_store: SQLiteCandidateEvaluationStore
    recorder: DomainCandidateEvaluationRecorder
    principal: PrincipalIdentity
    grant: CapabilityGrant
    candidate: DomainCandidate
    evaluation_task_id: str
    evaluation_run_id: str


def _budget() -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal("1.00"),
        max_duration_seconds=300,
        max_provider_tokens=1_000,
        max_tool_calls=4,
    )


def _workflow(
    *,
    workflow_id: str,
    created_by: str,
    evaluator_type: str,
) -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id=workflow_id,
        version=1,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by=created_by,
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
    tasks: TaskService,
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
    created = tasks.create_task(goal)
    commitment = Commitment(
        commitment_id=f"commitment:{label}",
        task_id=created.task_id,
        goal_id=goal.goal_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        accepted_by=actor,
        accepted_at=NOW,
        deliverables=(label,),
        acceptance_criteria=("typed receipt",),
        authority_scopes=(authority_scope,),
        budget=_budget(),
        risk_tier=1,
        exit_conditions=("complete or abstain",),
        expires_at=NOW + timedelta(hours=2),
    )
    expected = ExpectedOutcome(
        expected_outcome_id=f"expected:{label}",
        task_id=created.task_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator_type=evaluator_type,
        evaluator_version="1",
        evidence_requirements=("external evidence digest",),
        failure_semantics=("unresolved stays inert",),
        threshold=0.8,
        observation_window_seconds=60,
        frozen_at=NOW,
    )
    tasks.commit_task(
        created.task_id,
        commitment,
        _workflow(
            workflow_id=f"workflow:{label}",
            created_by=actor,
            evaluator_type=evaluator_type,
        ),
        expected,
    )
    started = tasks.start_run(created.task_id)
    assert started.run is not None
    running = tasks.update_run_status(
        created.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_QUEUED,
    )
    assert running.run is not None
    return created.task_id, running.run.run_id


def _seed_candidate(
    tasks: TaskService,
    correction: CorrectionAuthority,
    store: SQLiteCandidateStore,
) -> DomainCandidate:
    task_id, run_id = _create_running_task(
        tasks,
        label="candidate",
        actor="principal:builder",
        authority_scope="domain.materialize",
        evaluator_type="materialization-contract",
    )
    principal = PrincipalIdentity(
        principal_id="principal:builder",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        role=PrincipalRole.PRINCIPAL,
        authenticated_at=NOW,
    )
    patch = RepresentationPatch(
        operations=(
            RepresentationPatchOperation(
                operation_id="op:1",
                operation="UPSERT",
                assertion_id="assertion:1",
                subject_ref="entity:1",
                predicate="rdf:type",
                object_ref="type:Company",
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("evidence:source",),
            ),
        )
    )
    provenance = (
        CandidateProvenance(
            source_id="source:1",
            source_ref="artifact:source",
            source_type="filing",
            source_digest=DIGEST_A,
            accessed_at=NOW - timedelta(minutes=1),
            effective_at=NOW - timedelta(days=1),
            license_or_terms_id="terms:public",
            permitted_use="analysis",
            redistribution_allowed=False,
            output_patch_digest=patch.patch_digest(),
            expires_at=NOW + timedelta(days=1),
        ),
    )
    draft = DomainCandidateDraft(
        task_id=task_id,
        materialization_run_id=run_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        submitted_by=principal.principal_id,
        mechanism_digest=DIGEST_B,
        source_snapshot_digest=candidate_source_snapshot_digest(provenance),
        requested_channel=CandidateWriteChannel.R,
        outcome=MaterializationOutcome.CANDIDATE,
        representation_patch=patch,
        provenance=provenance,
        submitted_at=NOW,
    )
    return DomainCandidateSealer(
        tasks,
        correction,
        store,
        clock=lambda: NOW,
    ).seal(principal, draft)


def _grant(principal: PrincipalIdentity, **updates: Any) -> CapabilityGrant:
    values: dict[str, Any] = {
        "grant_id": "grant:domain.candidate.evaluate",
        "principal_id": principal.principal_id,
        "tenant_id": principal.tenant_id,
        "workspace_id": principal.workspace_id,
        "capability_id": EVALUATION_CAPABILITY,
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


def _evaluation_draft(
    context: EvaluationContext, **updates: Any
) -> CandidateEvaluationDraft:
    values: dict[str, Any] = {
        "candidate_digest": context.candidate.candidate_digest,
        "candidate_task_id": context.candidate.draft.task_id,
        "evaluation_task_id": context.evaluation_task_id,
        "evaluation_run_id": context.evaluation_run_id,
        "tenant_id": "tenant:1",
        "workspace_id": "workspace:1",
        "evaluator": CandidateEvaluatorIdentity(
            evaluator_id="evaluator:programmatic:1",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="candidate-contract",
            evaluator_version="1",
            implementation_digest=DIGEST_C,
            configuration_digest=DIGEST_D,
        ),
        "evidence_bundle_digest": DIGEST_A,
        "evidence_refs": ("external://evidence/1",),
        "disposition": CandidateEvaluationDisposition.EVALUATOR_PASS,
        "score": 0.9,
        "confidence": 0.8,
        "submitted_at": NOW,
    }
    values.update(updates)
    return CandidateEvaluationDraft(**values)


def _build_context() -> EvaluationContext:
    task_store = SQLiteTaskEventStore()
    tasks = TaskService(
        task_store,
        id_factory=DeterministicIdFactory(),
        clock=lambda: NOW,
    )
    correction = CorrectionAuthority(
        task_store,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        written_by="principal:recorder",
    )
    candidate_store = SQLiteCandidateStore()
    candidate = _seed_candidate(tasks, correction, candidate_store)
    principal = PrincipalIdentity(
        principal_id="principal:recorder",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        role=PrincipalRole.WORKER,
        authenticated_at=NOW,
    )
    evaluation_task_id, evaluation_run_id = _create_running_task(
        tasks,
        label="evaluation",
        actor=principal.principal_id,
        authority_scope=EVALUATION_CAPABILITY,
        evaluator_type="candidate-contract",
    )
    grant = _grant(principal)
    evaluation_store = SQLiteCandidateEvaluationStore()
    recorder = DomainCandidateEvaluationRecorder(
        tasks,
        correction,
        candidate_store,
        evaluation_store,
        {EVALUATION_CAPABILITY: grant},
        clock=lambda: NOW,
    )
    return EvaluationContext(
        task_store=task_store,
        tasks=tasks,
        correction=correction,
        candidate_store=candidate_store,
        evaluation_store=evaluation_store,
        recorder=recorder,
        principal=principal,
        grant=grant,
        candidate=candidate,
        evaluation_task_id=evaluation_task_id,
        evaluation_run_id=evaluation_run_id,
    )


@pytest.fixture
def context() -> Iterator[EvaluationContext]:
    value = _build_context()
    yield value
    value.evaluation_store.close()
    value.candidate_store.close()
    value.task_store.close()


def test_record_and_list_bind_frozen_contract_without_mutating_task(
    context: EvaluationContext,
) -> None:
    draft = _evaluation_draft(context)
    before_events = context.task_store.read(context.evaluation_task_id)
    receipt = context.recorder.record(
        context.principal,
        context.candidate.draft.task_id,
        context.candidate.candidate_digest,
        draft,
    )

    task = context.tasks.get_task(context.evaluation_task_id)
    assert task.expected_outcome is not None
    assert task.workflow is not None
    assert task.commitment is not None
    assert receipt.evaluation_contract_digest == evaluation_contract_digest(
        task.expected_outcome,
        task.workflow.evaluator_refs,
        task.commitment.authority_scopes,
    )
    assert receipt.recorded_by == context.principal.principal_id
    assert context.recorder.list_for_candidate(
        context.principal,
        context.candidate.draft.task_id,
        context.candidate.candidate_digest,
    ) == (receipt,)
    assert context.task_store.read(context.evaluation_task_id) == before_events


@pytest.mark.parametrize(
    "change",
    ["missing-grant", "revoked", "expired", "wrong-principal", "model-role"],
)
def test_record_requires_exact_active_capability_grant(
    context: EvaluationContext,
    change: str,
) -> None:
    principal = context.principal
    grants: dict[str, CapabilityGrant] = {EVALUATION_CAPABILITY: context.grant}
    if change == "missing-grant":
        grants = {}
    elif change == "revoked":
        grants[EVALUATION_CAPABILITY] = context.grant.model_copy(
            update={"status": CapabilityGrantStatus.REVOKED}
        )
    elif change == "expired":
        grants[EVALUATION_CAPABILITY] = _grant(
            principal,
            granted_at=NOW - timedelta(hours=2),
            expires_at=NOW - timedelta(hours=1),
        )
    elif change == "wrong-principal":
        grants[EVALUATION_CAPABILITY] = context.grant.model_copy(
            update={"principal_id": "principal:other"}
        )
    else:
        principal = context.principal.model_copy(update={"role": PrincipalRole.MODEL})
    recorder = DomainCandidateEvaluationRecorder(
        context.tasks,
        context.correction,
        context.candidate_store,
        context.evaluation_store,
        grants,
        clock=lambda: NOW,
    )

    with pytest.raises(CandidateEvaluationDenied):
        recorder.record(
            principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _evaluation_draft(context),
        )


def test_record_rejects_path_scope_identity_and_mechanism_reuse(
    context: EvaluationContext,
) -> None:
    with pytest.raises(CandidateEvaluationNotFound):
        context.recorder.record(
            context.principal,
            "task:wrong",
            context.candidate.candidate_digest,
            _evaluation_draft(context),
        )
    with pytest.raises(CandidateEvaluationScopeMismatch):
        context.recorder.record(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _evaluation_draft(context, workspace_id="workspace:other"),
        )
    reused = _evaluation_draft(context).evaluator.model_copy(
        update={"implementation_digest": context.candidate.draft.mechanism_digest}
    )
    with pytest.raises(CandidateEvaluationDenied, match="mechanism"):
        context.recorder.record(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _evaluation_draft(context, evaluator=reused),
        )


def test_record_rejects_evaluator_contract_mismatch(context: EvaluationContext) -> None:
    evaluator = _evaluation_draft(context).evaluator.model_copy(
        update={"evaluator_version": "2"}
    )
    with pytest.raises(CandidateEvaluationDenied, match="evaluator"):
        context.recorder.record(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _evaluation_draft(context, evaluator=evaluator),
        )


def test_record_rejects_recorder_as_evaluator(context: EvaluationContext) -> None:
    evaluator = _evaluation_draft(context).evaluator.model_copy(
        update={"evaluator_id": context.principal.principal_id}
    )

    with pytest.raises(CandidateEvaluationDenied, match="distinct identities"):
        context.recorder.record(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _evaluation_draft(context, evaluator=evaluator),
        )


def test_record_is_blocked_by_c7(context: EvaluationContext) -> None:
    context.correction.correct("run", context.evaluation_run_id, "operator halt")

    with pytest.raises(CandidateEvaluationDenied, match="halted"):
        context.recorder.record(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _evaluation_draft(context),
        )


def test_epoch_change_before_append_fails_closed(context: EvaluationContext) -> None:
    zero = CorrectionEpochVector(task_epoch=0, run_epoch=0, capability_epoch=0)
    changed = zero.model_copy(update={"run_epoch": 1})
    recorder = DomainCandidateEvaluationRecorder(
        context.tasks,
        ScriptedCorrectionAuthority((zero, changed)),
        context.candidate_store,
        context.evaluation_store,
        {EVALUATION_CAPABILITY: context.grant},
        clock=lambda: NOW,
    )

    with pytest.raises(CandidateEvaluationDenied, match="correction epoch"):
        recorder.record(
            context.principal,
            context.candidate.draft.task_id,
            context.candidate.candidate_digest,
            _evaluation_draft(context),
        )


def test_correction_cannot_interleave_after_recheck_before_append(
    context: EvaluationContext,
) -> None:
    store = BlockingEvaluationStore()
    recorder = DomainCandidateEvaluationRecorder(
        context.tasks,
        context.correction,
        context.candidate_store,
        store,
        {EVALUATION_CAPABILITY: context.grant},
        clock=lambda: NOW,
    )
    receipts = []
    errors: list[BaseException] = []

    def record_receipt() -> None:
        try:
            receipts.append(
                recorder.record(
                    context.principal,
                    context.candidate.draft.task_id,
                    context.candidate.candidate_digest,
                    _evaluation_draft(context),
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    correction_completed = Event()

    def halt_run() -> None:
        context.correction.correct("run", context.evaluation_run_id, "concurrent halt")
        correction_completed.set()

    record_thread = Thread(target=record_receipt)
    record_thread.start()
    assert store.append_entered.wait(timeout=5)
    correction_thread = Thread(target=halt_run)
    correction_thread.start()
    correction_was_blocked = not correction_completed.wait(timeout=0.2)
    store.append_release.set()
    record_thread.join(timeout=5)
    correction_thread.join(timeout=5)
    store.close()

    assert correction_was_blocked
    assert errors == []
    assert len(receipts) == 1
    assert receipts[0].observed_correction_epochs.run_epoch == 0
    assert correction_completed.is_set()
