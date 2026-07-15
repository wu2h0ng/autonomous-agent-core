from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from typing import Any, Iterator

import pytest

from agent_os_contracts import (
    CandidateProvenance,
    CandidateWriteChannel,
    Commitment,
    CorrectionEpochVector,
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
    domain_candidate_digest,
)
from agent_os_core import CorrectionAuthority, SQLiteTaskEventStore, TaskService
from agent_os_core.materialization import (
    MATERIALIZATION_CAPABILITY,
    DomainCandidateSealer,
    candidate_source_snapshot_digest,
)
from agent_os_core.materialization_persistence import SQLiteCandidateStore
from agent_os_core.errors import (
    CandidateConcurrentWrite,
    CandidateIdempotencyConflict,
    CandidateProvenanceError,
    CandidateScopeMismatch,
    CandidateSealingDenied,
)


NOW = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)
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


@dataclass(frozen=True)
class RunningContext:
    task_store: SQLiteTaskEventStore
    tasks: TaskService
    correction: CorrectionAuthority
    candidate_store: SQLiteCandidateStore
    sealer: DomainCandidateSealer
    principal: PrincipalIdentity
    task_id: str
    run_id: str


class ScriptedCorrectionAuthority:
    def __init__(self, snapshots: tuple[CorrectionEpochVector, ...]) -> None:
        self._snapshots = iter(snapshots)

    def halted(self, task_id: str, run_id: str, capability_id: str) -> bool:
        assert task_id and run_id and capability_id == MATERIALIZATION_CAPABILITY
        return False

    def snapshot(
        self,
        task_id: str,
        run_id: str,
        capability_id: str,
    ) -> CorrectionEpochVector:
        assert task_id and run_id and capability_id == MATERIALIZATION_CAPABILITY
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


class BlockingAppendCandidateStore(SQLiteCandidateStore):
    def __init__(self) -> None:
        super().__init__()
        self.append_entered = Event()
        self.append_release = Event()

    def append(self, request, *, expected_parent_digest):
        self.append_entered.set()
        if not self.append_release.wait(timeout=5):
            raise TimeoutError("candidate append was not released")
        return super().append(
            request,
            expected_parent_digest=expected_parent_digest,
        )


def _goal() -> Goal:
    return Goal(
        goal_id="goal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="principal-1",
        created_at=NOW,
        statement="Materialize a grounded representation candidate",
    )


def _commitment(task_id: str) -> Commitment:
    return Commitment(
        commitment_id="commitment-1",
        task_id=task_id,
        goal_id="goal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        accepted_by="principal-1",
        accepted_at=NOW,
        deliverables=("sealed candidate",),
        acceptance_criteria=("candidate remains inert",),
        authority_scopes=("domain.materialize",),
        budget=ResourceBudget(
            max_cost_usd=Decimal("1.00"),
            max_duration_seconds=300,
            max_provider_tokens=1_000,
            max_tool_calls=4,
        ),
        risk_tier=1,
        exit_conditions=("candidate sealed or abstained",),
        expires_at=NOW + timedelta(hours=1),
    )


def _workflow() -> WorkflowGraph:
    return WorkflowGraph(
        workflow_id="workflow-1",
        version=1,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="principal-1",
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


def _expected(task_id: str) -> ExpectedOutcome:
    return ExpectedOutcome(
        expected_outcome_id="expected-1",
        task_id=task_id,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        evaluator_type="materialization-contract",
        evaluator_version="1",
        evidence_requirements=("source provenance",),
        failure_semantics=("unsupported claims abstain",),
        threshold=1.0,
        observation_window_seconds=60,
        frozen_at=NOW,
    )


def _principal(**updates: Any) -> PrincipalIdentity:
    values: dict[str, Any] = {
        "principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "role": PrincipalRole.PRINCIPAL,
        "authenticated_at": NOW,
    }
    values.update(updates)
    return PrincipalIdentity(**values)


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


def _provenance(
    patch: RepresentationPatch,
    **updates: Any,
) -> CandidateProvenance:
    values: dict[str, Any] = {
        "source_id": "source:filing",
        "source_ref": "artifact:filing",
        "source_type": "regulatory-filing",
        "source_digest": DIGEST_A,
        "accessed_at": NOW - timedelta(minutes=5),
        "effective_at": NOW - timedelta(days=1),
        "license_or_terms_id": "terms:public-filing",
        "permitted_use": "analysis",
        "redistribution_allowed": False,
        "custodian_verified_by": "principal:reviewer",
        "derivation_input_digests": (DIGEST_A,),
        "output_patch_digest": patch.patch_digest(),
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(updates)
    return CandidateProvenance(**values)


def _draft(
    context: RunningContext,
    *,
    patch: RepresentationPatch | None = None,
    provenance: tuple[CandidateProvenance, ...] | None = None,
    **updates: Any,
):
    from agent_os_contracts import DomainCandidateDraft

    selected_patch = patch or _patch()
    selected_provenance = (
        provenance if provenance is not None else (_provenance(selected_patch),)
    )
    values: dict[str, Any] = {
        "task_id": context.task_id,
        "materialization_run_id": context.run_id,
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "submitted_by": "principal-1",
        "mechanism_digest": DIGEST_B,
        "source_snapshot_digest": candidate_source_snapshot_digest(
            selected_provenance
        ),
        "parent_candidate_digest": None,
        "requested_channel": CandidateWriteChannel.R,
        "outcome": MaterializationOutcome.CANDIDATE,
        "representation_patch": selected_patch,
        "provenance": selected_provenance,
        "submitted_at": NOW,
    }
    values.update(updates)
    return DomainCandidateDraft(**values)


def _build_context(candidate_database: str | Path = ":memory:") -> RunningContext:
    task_store = SQLiteTaskEventStore(":memory:")
    tasks = TaskService(
        task_store,
        id_factory=DeterministicIdFactory(),
        clock=lambda: NOW,
    )
    created = tasks.create_task(_goal())
    tasks.commit_task(
        created.task_id,
        _commitment(created.task_id),
        _workflow(),
        _expected(created.task_id),
    )
    started = tasks.start_run(created.task_id)
    assert started.run is not None
    running = tasks.update_run_status(
        created.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_QUEUED,
    )
    assert running.run is not None
    principal = _principal()
    correction = CorrectionAuthority(
        task_store,
        tenant_id=principal.tenant_id,
        workspace_id=principal.workspace_id,
        written_by=principal.principal_id,
    )
    candidate_store = SQLiteCandidateStore(candidate_database)
    sealer = DomainCandidateSealer(
        tasks,
        correction,
        candidate_store,
        clock=lambda: NOW,
    )
    return RunningContext(
        task_store=task_store,
        tasks=tasks,
        correction=correction,
        candidate_store=candidate_store,
        sealer=sealer,
        principal=principal,
        task_id=created.task_id,
        run_id=running.run.run_id,
    )


@pytest.fixture
def context() -> Iterator[RunningContext]:
    value = _build_context()
    yield value
    value.candidate_store.close()
    value.task_store.close()


def test_seal_is_idempotent_for_same_payload(context: RunningContext) -> None:
    draft = _draft(context)

    first = context.sealer.seal(context.principal, draft)
    second = context.sealer.seal(context.principal, draft)

    assert second == first
    assert context.candidate_store.list_for_task(
        "tenant-1", "workspace-1", context.task_id
    ) == (first,)


def test_concurrent_identical_seals_converge_on_one_row(
    context: RunningContext,
) -> None:
    draft = _draft(context)

    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = tuple(
            pool.map(
                lambda _: context.sealer.seal(context.principal, draft),
                range(2),
            )
        )

    assert candidates[0] == candidates[1]
    assert len(context.candidate_store.list_for_task(
        "tenant-1", "workspace-1", context.task_id
    )) == 1


def test_same_key_different_payload_is_conflict(context: RunningContext) -> None:
    context.sealer.seal(context.principal, _draft(context))
    changed_patch = _patch("type:ShellCompany")

    with pytest.raises(CandidateIdempotencyConflict):
        context.sealer.seal(
            context.principal,
            _draft(
                context,
                patch=changed_patch,
                provenance=(_provenance(changed_patch),),
            ),
        )


def test_stale_parent_is_rejected(context: RunningContext) -> None:
    first = context.sealer.seal(context.principal, _draft(context))
    second = context.sealer.seal(
        context.principal,
        _draft(context, parent_candidate_digest=first.candidate_digest),
    )
    assert second.candidate_version == 2

    with pytest.raises(CandidateConcurrentWrite):
        context.sealer.seal(
            context.principal,
            _draft(
                context,
                parent_candidate_digest=first.candidate_digest,
                mechanism_digest=DIGEST_D,
            ),
        )


def test_final_digest_binds_transactionally_assigned_version(
    context: RunningContext,
) -> None:
    first = context.sealer.seal(context.principal, _draft(context))
    second = context.sealer.seal(
        context.principal,
        _draft(context, parent_candidate_digest=first.candidate_digest),
    )

    assert second.candidate_version == 2
    assert second.candidate_digest == domain_candidate_digest(
        second.model_dump(mode="json", exclude={"candidate_digest"})
    )


def test_sealing_is_blocked_by_c7(context: RunningContext) -> None:
    context.correction.correct("task", context.task_id, "operator halt")

    with pytest.raises(CandidateSealingDenied, match="halted"):
        context.sealer.seal(context.principal, _draft(context))


def test_epoch_change_before_append_fails_closed(context: RunningContext) -> None:
    zero = CorrectionEpochVector(task_epoch=0, run_epoch=0, capability_epoch=0)
    changed = zero.model_copy(update={"run_epoch": 1})
    correction = ScriptedCorrectionAuthority((zero, changed))
    sealer = DomainCandidateSealer(
        context.tasks,
        correction,
        context.candidate_store,
        clock=lambda: NOW,
    )

    with pytest.raises(CandidateSealingDenied, match="correction epoch changed"):
        sealer.seal(context.principal, _draft(context))


def test_correction_cannot_interleave_after_recheck_before_append(
    context: RunningContext,
) -> None:
    store = BlockingAppendCandidateStore()
    sealer = DomainCandidateSealer(
        context.tasks,
        context.correction,
        store,
        clock=lambda: NOW,
    )
    candidates = []
    errors: list[BaseException] = []

    def seal_candidate() -> None:
        try:
            candidates.append(sealer.seal(context.principal, _draft(context)))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    correction_completed = Event()

    def halt_run() -> None:
        context.correction.correct("run", context.run_id, "concurrent halt")
        correction_completed.set()

    seal_thread = Thread(target=seal_candidate)
    seal_thread.start()
    assert store.append_entered.wait(timeout=5)
    correction_thread = Thread(target=halt_run)
    correction_thread.start()
    correction_was_blocked = not correction_completed.wait(timeout=0.2)
    store.append_release.set()
    seal_thread.join(timeout=5)
    correction_thread.join(timeout=5)
    store.close()

    assert correction_was_blocked
    assert errors == []
    assert len(candidates) == 1
    assert candidates[0].observed_correction_epochs.run_epoch == 0
    assert correction_completed.is_set()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("materialization_run_id", "run:wrong"),
        ("tenant_id", "tenant:wrong"),
        ("workspace_id", "workspace:wrong"),
        ("submitted_by", "principal:wrong"),
    ),
)
def test_sealer_rejects_scope_mismatch(
    context: RunningContext,
    field: str,
    value: str,
) -> None:
    with pytest.raises(CandidateScopeMismatch):
        context.sealer.seal(
            context.principal,
            _draft(context).model_copy(update={field: value}),
        )


def test_sealer_rejects_non_running_run(context: RunningContext) -> None:
    context.tasks.update_run_status(
        context.task_id,
        RunStatus.PAUSED,
        event_type=TaskEventType.RUN_PAUSED,
    )

    with pytest.raises(CandidateSealingDenied, match="RUNNING"):
        context.sealer.seal(context.principal, _draft(context))


def test_sealer_rejects_expired_or_drifting_provenance(
    context: RunningContext,
) -> None:
    patch = _patch()
    expired = _provenance(
        patch,
        accessed_at=NOW - timedelta(days=2),
        effective_at=NOW - timedelta(days=3),
        expires_at=NOW - timedelta(days=1),
    )
    with pytest.raises(CandidateProvenanceError, match="expired"):
        context.sealer.seal(
            context.principal,
            _draft(context, patch=patch, provenance=(expired,)),
        )

    with pytest.raises(CandidateProvenanceError, match="snapshot"):
        context.sealer.seal(
            context.principal,
            _draft(context).model_copy(update={"source_snapshot_digest": DIGEST_D}),
        )


@pytest.mark.parametrize(
    "channel",
    [CandidateWriteChannel.B, CandidateWriteChannel.T, CandidateWriteChannel.P],
)
def test_unimplemented_channels_seal_only_not_supported(
    context: RunningContext,
    channel: CandidateWriteChannel,
) -> None:
    draft = _draft(
        context,
        requested_channel=channel,
        outcome=MaterializationOutcome.NOT_SUPPORTED,
        representation_patch=None,
        provenance=(),
        source_snapshot_digest=candidate_source_snapshot_digest(()),
    )

    candidate = context.sealer.seal(context.principal, draft)

    assert candidate.draft.outcome is MaterializationOutcome.NOT_SUPPORTED
    assert candidate.draft.requested_channel is channel


def test_sealing_and_listing_do_not_append_task_events(
    context: RunningContext,
) -> None:
    before = context.task_store.read(context.task_id)

    context.sealer.seal(context.principal, _draft(context))
    context.sealer.list_for_task(context.principal, context.task_id)

    assert context.task_store.read(context.task_id) == before


def test_listing_rejects_cross_tenant_principal(context: RunningContext) -> None:
    with pytest.raises(CandidateScopeMismatch):
        context.sealer.list_for_task(
            _principal(tenant_id="tenant:other"),
            context.task_id,
        )


def test_sqlite_candidate_store_survives_reopen(tmp_path: Path) -> None:
    database = tmp_path / "candidates.sqlite3"
    context = _build_context(database)
    draft = _draft(context)
    first = context.sealer.seal(context.principal, draft)
    context.candidate_store.close()

    reopened = SQLiteCandidateStore(database)
    restarted = DomainCandidateSealer(
        context.tasks,
        context.correction,
        reopened,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    try:
        assert restarted.list_for_task(context.principal, context.task_id) == (first,)
        assert restarted.seal(context.principal, draft) == first
    finally:
        reopened.close()
        context.task_store.close()
