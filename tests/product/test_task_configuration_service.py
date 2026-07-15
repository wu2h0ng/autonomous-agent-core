from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import RLock

import pytest

from agent_os_contracts import (
    CandidateEvaluationDisposition,
    CandidateEvaluationDraft,
    CandidateEvaluationReceipt,
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
    DomainPriorSelector,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    MaterializationOutcome,
    NodeKind,
    NodeSpec,
    PrincipalIdentity,
    PrincipalRole,
    ProviderProfile,
    RepresentationPatch,
    RepresentationPatchOperation,
    RepresentationRelationClass,
    ResourceBudget,
    TaskConfigurationSnapshotCommand,
    TaskEventType,
    WorkflowGraph,
    content_digest,
    domain_candidate_digest,
)
from agent_os_core import (
    POLICY_KERNEL_V1_DIGEST,
    TASK_CONFIGURATION_CAPABILITY,
    CorrectionAuthority,
    InMemoryTaskEventStore,
    TaskConfigurationConflict,
    TaskConfigurationDenied,
    TaskConfigurationDrift,
    TaskConfigurationNotFound,
    TaskConfigurationRuntime,
    TaskConfigurationSnapshotService,
    TaskService,
    SQLiteCandidateEvaluationStore,
    SQLiteCandidatePromotionStore,
    candidate_promotion_idempotency_key,
    candidate_promotion_payload_digest,
    candidate_receipt_chain_digest,
)
from agent_os_core.materialization import SEALER_ID
from agent_os_core.materialization_evaluation_persistence import (
    CandidateEvaluationRecordRequest,
    candidate_evaluation_idempotency_key,
    candidate_evaluation_payload_digest,
)
from agent_os_core.materialization_ledger import SQLiteAdaptationLedger
from agent_os_core.materialization_promotion_persistence import (
    CandidatePromotionRecordRequest,
)
from agent_os_core.materialization_promotion_policy import (
    PromotionPolicyRegistry,
    PromotionReduction,
)


NOW = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class _ClosedTestPromotePolicy:
    """Test-only proof fixture; never registered by the Product application."""

    version: str = "TEST-ADM-P4-PROMOTE-V1"
    digest: str = content_digest(
        {
            "schema": "TEST-ONLY-ADM-P4-PROMOTION-POLICY",
            "disposition": "PROMOTE",
        }
    )

    def reduce(
        self,
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
    ) -> PromotionReduction:
        del candidate, receipts
        return PromotionReduction(
            disposition=CandidatePromotionDisposition.PROMOTE,
            reason_codes=("TEST_ONLY_CLOSED_FIXTURE",),
        )


class _StaticCandidateStore:
    def __init__(self, candidate: DomainCandidate) -> None:
        self.candidate = candidate

    def get_by_digest(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> DomainCandidate | None:
        if (
            tenant_id == self.candidate.draft.tenant_id
            and workspace_id == self.candidate.draft.workspace_id
            and candidate_digest == self.candidate.candidate_digest
        ):
            return self.candidate
        return None


@dataclass(slots=True)
class _PriorFixture:
    ledger: SQLiteAdaptationLedger
    evaluations: SQLiteCandidateEvaluationStore
    promotions: SQLiteCandidatePromotionStore
    candidates: _StaticCandidateStore
    candidate: DomainCandidate
    selector: DomainPriorSelector

    def close(self) -> None:
        self.promotions.close()
        self.evaluations.close()
        self.ledger.close()


def _budget() -> ResourceBudget:
    return ResourceBudget(
        max_cost_usd=Decimal("1"),
        max_duration_seconds=300,
        max_provider_tokens=0,
        max_tool_calls=10,
    )


def _prior_fixture(
    *,
    source_task_id: str = "task:source",
    source_run_id: str = "run:source",
) -> _PriorFixture:
    patch = RepresentationPatch(
        operations=(
            RepresentationPatchOperation(
                operation_id="operation:source",
                operation="UPSERT",
                assertion_id="assertion:source",
                subject_ref="entity:source",
                predicate="rdf:type",
                object_ref="type:Source",
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("artifact:source",),
            ),
        )
    )
    provenance = CandidateProvenance(
        source_id="source:fixture",
        source_ref="artifact:source",
        source_type="test-fixture",
        source_digest="a" * 64,
        accessed_at=NOW,
        effective_at=NOW - timedelta(minutes=1),
        license_or_terms_id="terms:test",
        permitted_use="test-only",
        redistribution_allowed=False,
        output_patch_digest=patch.patch_digest(),
        expires_at=NOW + timedelta(days=1),
    )
    draft = DomainCandidateDraft(
        task_id=source_task_id,
        materialization_run_id=source_run_id,
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        submitted_by="principal:source-builder",
        mechanism_digest="b" * 64,
        source_snapshot_digest="c" * 64,
        requested_channel=CandidateWriteChannel.R,
        outcome=MaterializationOutcome.CANDIDATE,
        representation_patch=patch,
        provenance=(provenance,),
        submitted_at=NOW,
    )
    candidate_payload = {
        "schema_version": "1.0",
        "candidate_id": "candidate:source",
        "candidate_version": 1,
        "payload_digest": content_digest(draft),
        "idempotency_key": content_digest({"candidate": source_task_id}),
        "sealed_by": SEALER_ID,
        "sealed_at": NOW,
        "observed_correction_epochs": CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
        "draft": draft,
    }
    candidate = DomainCandidate(
        **candidate_payload,
        candidate_digest=domain_candidate_digest(candidate_payload),
    )

    ledger = SQLiteAdaptationLedger()
    evaluations = SQLiteCandidateEvaluationStore(ledger=ledger)
    policy = _ClosedTestPromotePolicy()
    promotions = SQLiteCandidatePromotionStore(
        ledger,
        PromotionPolicyRegistry((policy,)),
    )
    evaluator = CandidateEvaluatorIdentity(
        evaluator_id="principal:test-evaluator",
        evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
        evaluator_type="pytest",
        evaluator_version="1",
        implementation_digest="d" * 64,
        configuration_digest="e" * 64,
    )
    evaluation_draft = CandidateEvaluationDraft(
        candidate_digest=candidate.candidate_digest,
        candidate_task_id=source_task_id,
        evaluation_task_id="task:evaluation",
        evaluation_run_id="run:evaluation",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator=evaluator,
        evidence_bundle_digest="f" * 64,
        evidence_refs=("artifact:evaluation",),
        disposition=CandidateEvaluationDisposition.EVALUATOR_PASS,
        score=1.0,
        confidence=1.0,
        submitted_at=NOW,
    )
    evaluation_contract_digest = content_digest(
        {"contract": "TEST-ONLY-ADM-P4-EVALUATION"}
    )
    recorded_by = "principal:test-recorder"
    evaluation_request = CandidateEvaluationRecordRequest(
        evaluation_id="evaluation:source:1",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        candidate_digest=candidate.candidate_digest,
        idempotency_key=candidate_evaluation_idempotency_key(
            evaluation_draft,
            evaluation_contract_digest,
            recorded_by,
        ),
        payload_digest=candidate_evaluation_payload_digest(
            evaluation_draft,
            evaluation_contract_digest,
            recorded_by,
        ),
        recorded_by=recorded_by,
        recorded_at=NOW,
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
        evaluation_contract_digest=evaluation_contract_digest,
        draft=evaluation_draft,
    )
    receipt = evaluations.append(
        evaluation_request,
        expected_parent_digest=None,
    )
    command = CandidatePromotionCommand(
        candidate_digest=candidate.candidate_digest,
        candidate_task_id=source_task_id,
        promotion_task_id="task:promotion",
        promotion_run_id="run:promotion",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        expected_evaluation_head_digest=receipt.evaluation_digest,
    )
    receipts = (receipt,)
    receipt_chain_digest = candidate_receipt_chain_digest(
        candidate.candidate_digest,
        receipts,
    )
    reduction = policy.reduce(candidate, receipts)
    decided_by = "principal:test-promoter"
    promotion_request = CandidatePromotionRecordRequest(
        command=command,
        candidate=candidate,
        receipt_chain_digest=receipt_chain_digest,
        policy_version=policy.version,
        policy_digest=policy.digest,
        reduction=reduction,
        payload_digest=candidate_promotion_payload_digest(
            command,
            candidate,
            receipt_chain_digest,
            policy.version,
            policy.digest,
            reduction,
            decided_by,
        ),
        idempotency_key=candidate_promotion_idempotency_key(
            command,
            policy.version,
            policy.digest,
            decided_by,
        ),
        decided_by=decided_by,
        decided_at=NOW,
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0,
            run_epoch=0,
            capability_epoch=0,
        ),
    )
    result = promotions.append(promotion_request)
    assert result.prior is not None
    return _PriorFixture(
        ledger=ledger,
        evaluations=evaluations,
        promotions=promotions,
        candidates=_StaticCandidateStore(candidate),
        candidate=candidate,
        selector=DomainPriorSelector(
            candidate_task_id=source_task_id,
            candidate_digest=candidate.candidate_digest,
            prior_artifact_id=result.prior.prior_artifact_id,
        ),
    )


def _append_later_receipt(fixture: _PriorFixture) -> CandidateEvaluationReceipt:
    latest = fixture.evaluations.latest(
        "tenant:1",
        "workspace:1",
        fixture.candidate.candidate_digest,
    )
    assert latest is not None
    draft = CandidateEvaluationDraft(
        candidate_digest=fixture.candidate.candidate_digest,
        candidate_task_id=fixture.candidate.draft.task_id,
        evaluation_task_id="task:evaluation:later",
        evaluation_run_id="run:evaluation:later",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        evaluator=CandidateEvaluatorIdentity(
            evaluator_id="principal:test-evaluator:later",
            evaluator_kind=CandidateEvaluatorKind.PROGRAMMATIC,
            evaluator_type="pytest",
            evaluator_version="2",
            implementation_digest="1" * 64,
            configuration_digest="2" * 64,
        ),
        evidence_bundle_digest="3" * 64,
        evidence_refs=("artifact:evaluation:later",),
        disposition=CandidateEvaluationDisposition.EVALUATOR_PASS,
        score=1.0,
        confidence=1.0,
        parent_evaluation_digest=latest.evaluation_digest,
        submitted_at=NOW,
    )
    contract_digest = content_digest(
        {"contract": "TEST-ONLY-ADM-P4-EVALUATION-LATER"}
    )
    recorded_by = "principal:test-recorder:later"
    return fixture.evaluations.append(
        CandidateEvaluationRecordRequest(
            evaluation_id="evaluation:source:2",
            tenant_id="tenant:1",
            workspace_id="workspace:1",
            candidate_digest=fixture.candidate.candidate_digest,
            idempotency_key=candidate_evaluation_idempotency_key(
                draft,
                contract_digest,
                recorded_by,
            ),
            payload_digest=candidate_evaluation_payload_digest(
                draft,
                contract_digest,
                recorded_by,
            ),
            recorded_by=recorded_by,
            recorded_at=NOW,
            observed_correction_epochs=CorrectionEpochVector(
                task_epoch=0,
                run_epoch=0,
                capability_epoch=0,
            ),
            evaluation_contract_digest=contract_digest,
            draft=draft,
        ),
        expected_parent_digest=latest.evaluation_digest,
    )


def _provider(*, suffix: str = "1") -> ProviderProfile:
    return ProviderProfile(
        profile_id=f"provider-profile:{suffix}",
        provider_id="deterministic",
        model_id=f"deterministic-{suffix}",
        endpoint_class="test",
        credential_ref_id="credential:none",
        capabilities=("chat",),
        max_context_tokens=16_000,
        request_timeout_seconds=60,
        created_at=NOW,
    )


def _grant(
    capability_id: str,
    *,
    status: CapabilityGrantStatus = CapabilityGrantStatus.ACTIVE,
    expires_at: datetime | None = None,
    capability_version: str = "1",
) -> CapabilityGrant:
    return CapabilityGrant(
        grant_id=f"grant:{capability_id}",
        principal_id="principal:consumer",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        capability_id=capability_id,
        capability_version=capability_version,
        max_risk_tier=1,
        budget_limit=_budget(),
        status=status,
        granted_by="system",
        granted_at=NOW - timedelta(minutes=1),
        expires_at=expires_at or NOW + timedelta(hours=1),
    )


def _principal(
    *, role: PrincipalRole = PrincipalRole.PRINCIPAL
) -> PrincipalIdentity:
    return PrincipalIdentity(
        principal_id="principal:consumer",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        role=role,
        authenticated_at=NOW,
    )


def _committed_task(
    tasks: TaskService,
    *,
    snapshot_authority: bool = True,
):  # type: ignore[no-untyped-def]
    goal = Goal(
        goal_id="goal:consumer",
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        created_by="principal:consumer",
        created_at=NOW,
        statement="seal a configuration",
    )
    created = tasks.create_task(goal)
    workflow = WorkflowGraph(
        workflow_id="workflow:consumer",
        version=1,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        created_by=goal.created_by,
        created_at=NOW,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(
                node_id="read",
                kind=NodeKind.TOOL,
                capability="workspace.read",
            ),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(EdgeSpec(source="read", target="done"),),
    )
    scopes = ["workspace.read"]
    if snapshot_authority:
        scopes.append(TASK_CONFIGURATION_CAPABILITY)
    commitment = Commitment(
        commitment_id="commitment:consumer",
        task_id=created.task_id,
        goal_id=goal.goal_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        accepted_by=goal.created_by,
        accepted_at=NOW,
        deliverables=("result",),
        acceptance_criteria=("verified",),
        authority_scopes=tuple(scopes),
        budget=_budget(),
        risk_tier=1,
        exit_conditions=("done",),
        expires_at=NOW + timedelta(hours=1),
    )
    expected = ExpectedOutcome(
        expected_outcome_id="outcome:consumer",
        task_id=created.task_id,
        tenant_id=goal.tenant_id,
        workspace_id=goal.workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("NOT_MET",),
        threshold=1.0,
        observation_window_seconds=300,
        frozen_at=NOW,
    )
    return tasks.commit_task(created.task_id, commitment, workflow, expected)


def _harness(
    *,
    reader=None,  # type: ignore[no-untyped-def]
    grants: dict[str, CapabilityGrant] | None = None,
    clock=None,  # type: ignore[no-untyped-def]
    candidates=None,  # type: ignore[no-untyped-def]
    evaluations=None,  # type: ignore[no-untyped-def]
    promotions=None,  # type: ignore[no-untyped-def]
):  # type: ignore[no-untyped-def]
    store = InMemoryTaskEventStore()
    counters: dict[str, int] = {}

    def next_id(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"{kind}:{counters[kind]}"

    tasks = TaskService(store, id_factory=next_id, clock=lambda: NOW)
    correction = CorrectionAuthority(
        tenant_id="tenant:1",
        workspace_id="workspace:1",
        written_by="principal:consumer",
    )
    live_grants = grants or {
        "workspace.read": _grant("workspace.read"),
        TASK_CONFIGURATION_CAPABILITY: _grant(TASK_CONFIGURATION_CAPABILITY),
    }
    runtime_reader = reader or (
        lambda: TaskConfigurationRuntime(
            policy_version="policy-1",
            policy_digest=POLICY_KERNEL_V1_DIGEST,
            provider_profile=_provider(),
            grants=live_grants,
            capability_versions={
                capability_id: grant.capability_version
                for capability_id, grant in live_grants.items()
            },
        )
    )
    service = TaskConfigurationSnapshotService(
        tasks,
        correction,
        configuration_lock=RLock(),
        configuration_reader=runtime_reader,
        id_factory=next_id,
        clock=clock or (lambda: NOW),
        candidates=candidates,
        evaluations=evaluations,
        promotions=promotions,
    )
    return store, tasks, correction, service


def test_seal_derives_exact_product_configuration_and_appends_one_event() -> None:
    store, tasks, _, service = _harness()
    task = _committed_task(tasks)

    snapshot = service.seal(
        _principal(),
        task.task_id,
        TaskConfigurationSnapshotCommand(),
    )

    assert snapshot.consumer_task_id == task.task_id
    assert snapshot.reserved_run_id.startswith("run:")
    assert snapshot.workflow == task.workflow
    assert snapshot.policy_digest == POLICY_KERNEL_V1_DIGEST
    assert snapshot.provider_profile == _provider()
    assert tuple(grant.capability_id for grant in snapshot.execution_grants) == (
        "workspace.read",
    )
    assert snapshot.expected_outcome == task.expected_outcome
    assert [event.event_type for event in store.read(task.task_id)].count(
        TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED
    ) == 1


def test_seal_requires_commitment_authority_and_active_exact_grants() -> None:
    _, tasks, _, service = _harness()
    task = _committed_task(tasks, snapshot_authority=False)

    with pytest.raises(TaskConfigurationDenied, match="authority"):
        service.seal(
            _principal(),
            task.task_id,
            TaskConfigurationSnapshotCommand(),
        )

    expired_grants = {
        "workspace.read": _grant("workspace.read"),
        TASK_CONFIGURATION_CAPABILITY: _grant(
            TASK_CONFIGURATION_CAPABILITY,
            expires_at=NOW,
        ),
    }
    _, tasks2, _, service2 = _harness(grants=expired_grants)
    task2 = _committed_task(tasks2)
    with pytest.raises(TaskConfigurationDenied, match="grant"):
        service2.seal(
            _principal(),
            task2.task_id,
            TaskConfigurationSnapshotCommand(),
        )


def test_seal_detects_c7_halt_before_append() -> None:
    store, tasks, correction, service = _harness()
    task = _committed_task(tasks)
    correction.correct("capability", TASK_CONFIGURATION_CAPABILITY, "halt")

    with pytest.raises(TaskConfigurationDenied, match="correction"):
        service.seal(
            _principal(),
            task.task_id,
            TaskConfigurationSnapshotCommand(),
        )

    assert all(
        event.event_type is not TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED
        for event in store.read(task.task_id)
    )


def test_seal_rederives_all_runtime_inputs_inside_guard() -> None:
    calls = 0
    grants = {
        "workspace.read": _grant("workspace.read"),
        TASK_CONFIGURATION_CAPABILITY: _grant(TASK_CONFIGURATION_CAPABILITY),
    }

    def drifting_reader() -> TaskConfigurationRuntime:
        nonlocal calls
        calls += 1
        return TaskConfigurationRuntime(
            policy_version="policy-1",
            policy_digest=POLICY_KERNEL_V1_DIGEST,
            provider_profile=_provider(suffix="1" if calls == 1 else "2"),
            grants=grants,
            capability_versions={
                capability_id: grant.capability_version
                for capability_id, grant in grants.items()
            },
        )

    store, tasks, _, service = _harness(reader=drifting_reader)
    task = _committed_task(tasks)

    with pytest.raises(TaskConfigurationDrift, match="changed"):
        service.seal(
            _principal(),
            task.task_id,
            TaskConfigurationSnapshotCommand(),
        )

    assert calls >= 2
    assert all(
        event.event_type is not TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED
        for event in store.read(task.task_id)
    )


def test_seal_rechecks_expiry_at_c7_guard_linearization_point() -> None:
    ticks = iter((NOW, NOW + timedelta(hours=2)))
    store, tasks, _, service = _harness(clock=lambda: next(ticks))
    task = _committed_task(tasks)

    with pytest.raises(TaskConfigurationDenied, match="expired"):
        service.seal(
            _principal(),
            task.task_id,
            TaskConfigurationSnapshotCommand(),
        )

    assert all(
        event.event_type is not TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED
        for event in store.read(task.task_id)
    )


def test_execution_grant_binds_runtime_capability_version_not_sealer_version() -> None:
    grants = {
        "workspace.read": _grant("workspace.read", capability_version="2"),
        TASK_CONFIGURATION_CAPABILITY: _grant(TASK_CONFIGURATION_CAPABILITY),
    }

    def versioned_reader() -> TaskConfigurationRuntime:
        return TaskConfigurationRuntime(
            policy_version="policy-1",
            policy_digest=POLICY_KERNEL_V1_DIGEST,
            provider_profile=_provider(),
            grants=grants,
            capability_versions={
                "workspace.read": "2",
                TASK_CONFIGURATION_CAPABILITY: "1",
            },
        )

    _, tasks, _, service = _harness(reader=versioned_reader)
    task = _committed_task(tasks)

    snapshot = service.seal(
        _principal(),
        task.task_id,
        TaskConfigurationSnapshotCommand(),
    )

    assert snapshot.execution_grants[0].capability_version == "2"


def test_execution_grant_rejects_version_different_from_runtime_spec() -> None:
    grants = {
        "workspace.read": _grant("workspace.read", capability_version="1"),
        TASK_CONFIGURATION_CAPABILITY: _grant(TASK_CONFIGURATION_CAPABILITY),
    }

    def mismatched_reader() -> TaskConfigurationRuntime:
        return TaskConfigurationRuntime(
            policy_version="policy-1",
            policy_digest=POLICY_KERNEL_V1_DIGEST,
            provider_profile=_provider(),
            grants=grants,
            capability_versions={
                "workspace.read": "2",
                TASK_CONFIGURATION_CAPABILITY: "1",
            },
        )

    _, tasks, _, service = _harness(reader=mismatched_reader)
    task = _committed_task(tasks)

    with pytest.raises(TaskConfigurationDenied, match="version"):
        service.seal(
            _principal(),
            task.task_id,
            TaskConfigurationSnapshotCommand(),
        )


def test_exact_replay_returns_event_and_changed_request_conflicts() -> None:
    _, tasks, _, service = _harness()
    task = _committed_task(tasks)
    command = TaskConfigurationSnapshotCommand()
    first = service.seal(_principal(), task.task_id, command)

    assert service.seal(_principal(), task.task_id, command) == first

    changed = TaskConfigurationSnapshotCommand(
        prior_selector=DomainPriorSelector(
            candidate_task_id="task:source",
            candidate_digest="b" * 64,
            prior_artifact_id="prior:source",
        )
    )
    with pytest.raises(TaskConfigurationConflict, match="different"):
        service.seal(_principal(), task.task_id, changed)


def test_valid_inert_prior_binds_exact_immutable_lineage() -> None:
    fixture = _prior_fixture()
    try:
        _, tasks, _, service = _harness(
            candidates=fixture.candidates,
            evaluations=fixture.evaluations,
            promotions=fixture.promotions,
        )
        task = _committed_task(tasks)

        snapshot = service.seal(
            _principal(),
            task.task_id,
            TaskConfigurationSnapshotCommand(prior_selector=fixture.selector),
        )

        binding = snapshot.optional_prior
        assert binding is not None
        assert binding.prior_artifact_id == fixture.selector.prior_artifact_id
        assert binding.candidate_digest == fixture.candidate.candidate_digest
        assert binding.candidate_task_id == fixture.candidate.draft.task_id
        assert binding.materialization_run_id == fixture.candidate.draft.materialization_run_id
        assert binding.source_state == "INERT"
        assert binding.source_activation_authority == "NONE"
        assert binding.consumption_mode == "REFERENCE_ONLY"
        assert binding.representation_patch_digest == (
            fixture.candidate.draft.representation_patch.patch_digest()  # type: ignore[union-attr]
        )
        assert binding.provenance == fixture.candidate.draft.provenance
        assert tuple(source.evaluation_digest for source in binding.evaluation_sources) == (
            binding.evaluation_head_digest,
        )
    finally:
        fixture.close()


def test_prior_binding_remains_exact_after_later_receipt_append() -> None:
    fixture = _prior_fixture()
    try:
        later = _append_later_receipt(fixture)
        _, tasks, _, service = _harness(
            candidates=fixture.candidates,
            evaluations=fixture.evaluations,
            promotions=fixture.promotions,
        )
        task = _committed_task(tasks)

        snapshot = service.seal(
            _principal(),
            task.task_id,
            TaskConfigurationSnapshotCommand(prior_selector=fixture.selector),
        )

        binding = snapshot.optional_prior
        assert binding is not None
        assert len(binding.evaluation_receipt_digests) == 1
        assert later.evaluation_digest not in binding.evaluation_receipt_digests
    finally:
        fixture.close()


def test_prior_selection_fails_closed_for_missing_artifact_or_receipts() -> None:
    fixture = _prior_fixture()
    try:
        _, tasks, _, service = _harness(
            candidates=fixture.candidates,
            evaluations=fixture.evaluations,
            promotions=fixture.promotions,
        )
        task = _committed_task(tasks)
        missing = fixture.selector.model_copy(
            update={"prior_artifact_id": "domain-prior:missing"}
        )
        with pytest.raises(TaskConfigurationNotFound, match="prior"):
            service.seal(
                _principal(),
                task.task_id,
                TaskConfigurationSnapshotCommand(prior_selector=missing),
            )

        class EmptyEvaluations:
            @staticmethod
            def list_for_candidate(
                tenant_id: str,
                workspace_id: str,
                candidate_digest: str,
            ) -> tuple[CandidateEvaluationReceipt, ...]:
                del tenant_id, workspace_id, candidate_digest
                return ()

        _, tasks2, _, service2 = _harness(
            candidates=fixture.candidates,
            evaluations=EmptyEvaluations(),
            promotions=fixture.promotions,
        )
        task2 = _committed_task(tasks2)
        with pytest.raises(TaskConfigurationDrift, match="receipt"):
            service2.seal(
                _principal(),
                task2.task_id,
                TaskConfigurationSnapshotCommand(prior_selector=fixture.selector),
            )
    finally:
        fixture.close()


def test_prior_lineage_digest_mutation_fails_closed_before_snapshot_append() -> None:
    fixture = _prior_fixture()
    try:
        receipts = fixture.evaluations.list_for_candidate(
            "tenant:1",
            "workspace:1",
            fixture.candidate.candidate_digest,
        )
        tampered = receipts[0].model_copy(
            update={"evaluation_digest": "0" * 64}
        )

        class TamperedEvaluations:
            @staticmethod
            def list_for_candidate(
                tenant_id: str,
                workspace_id: str,
                candidate_digest: str,
            ) -> tuple[CandidateEvaluationReceipt, ...]:
                del tenant_id, workspace_id, candidate_digest
                return (tampered,)

        store, tasks, _, service = _harness(
            candidates=fixture.candidates,
            evaluations=TamperedEvaluations(),
            promotions=fixture.promotions,
        )
        task = _committed_task(tasks)

        with pytest.raises(TaskConfigurationDrift, match="receipt digest"):
            service.seal(
                _principal(),
                task.task_id,
                TaskConfigurationSnapshotCommand(prior_selector=fixture.selector),
            )

        assert all(
            event.event_type is not TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED
            for event in store.read(task.task_id)
        )
    finally:
        fixture.close()


@pytest.mark.parametrize(
    ("source_task_id", "source_run_id"),
    (("task:1", "run:source"), ("task:source", "run:1")),
)
def test_consumer_task_and_reserved_run_must_differ_from_prior_sources(
    source_task_id: str,
    source_run_id: str,
) -> None:
    fixture = _prior_fixture(
        source_task_id=source_task_id,
        source_run_id=source_run_id,
    )
    try:
        _, tasks, _, service = _harness(
            candidates=fixture.candidates,
            evaluations=fixture.evaluations,
            promotions=fixture.promotions,
        )
        task = _committed_task(tasks)
        with pytest.raises(TaskConfigurationDenied, match="source"):
            service.seal(
                _principal(),
                task.task_id,
                TaskConfigurationSnapshotCommand(prior_selector=fixture.selector),
            )
    finally:
        fixture.close()


def test_bound_start_requires_exact_snapshot_and_reserved_run() -> None:
    _, tasks, _, service = _harness()
    task = _committed_task(tasks)
    snapshot = service.seal(
        _principal(),
        task.task_id,
        TaskConfigurationSnapshotCommand(),
    )

    with pytest.raises(TaskConfigurationNotFound, match="snapshot"):
        service.start_run(_principal(), task.task_id, "task-configuration:wrong")

    started = service.start_run(
        _principal(),
        task.task_id,
        snapshot.snapshot_id,
    )
    assert started.run is not None
    assert started.run.run_id == snapshot.reserved_run_id
    assert started.run.configuration_snapshot_id == snapshot.snapshot_id
    assert started.run.configuration_snapshot_digest == snapshot.snapshot_digest


def test_bound_start_fails_before_append_on_config_or_c7_drift() -> None:
    active_provider = _provider(suffix="1")
    grants = {
        "workspace.read": _grant("workspace.read"),
        TASK_CONFIGURATION_CAPABILITY: _grant(TASK_CONFIGURATION_CAPABILITY),
    }

    def reader() -> TaskConfigurationRuntime:
        return TaskConfigurationRuntime(
            policy_version="policy-1",
            policy_digest=POLICY_KERNEL_V1_DIGEST,
            provider_profile=active_provider,
            grants=grants,
            capability_versions={
                capability_id: grant.capability_version
                for capability_id, grant in grants.items()
            },
        )

    store, tasks, correction, service = _harness(reader=reader)
    task = _committed_task(tasks)
    snapshot = service.seal(
        _principal(),
        task.task_id,
        TaskConfigurationSnapshotCommand(),
    )
    active_provider = _provider(suffix="2")
    with pytest.raises(TaskConfigurationDrift, match="configuration"):
        service.start_run(_principal(), task.task_id, snapshot.snapshot_id)
    assert TaskEventType.RUN_STARTED not in {
        event.event_type for event in store.read(task.task_id)
    }

    active_provider = _provider(suffix="1")
    correction.correct("task", task.task_id, "halt before start")
    with pytest.raises(TaskConfigurationDenied, match="correction"):
        service.start_run(_principal(), task.task_id, snapshot.snapshot_id)
    assert TaskEventType.RUN_STARTED not in {
        event.event_type for event in store.read(task.task_id)
    }


def test_bound_start_rechecks_expiry_at_c7_guard_linearization_point() -> None:
    ticks = iter((NOW, NOW, NOW, NOW + timedelta(hours=2)))
    store, tasks, _, service = _harness(clock=lambda: next(ticks))
    task = _committed_task(tasks)
    snapshot = service.seal(
        _principal(),
        task.task_id,
        TaskConfigurationSnapshotCommand(),
    )

    with pytest.raises(TaskConfigurationDenied, match="expired"):
        service.start_run(_principal(), task.task_id, snapshot.snapshot_id)

    assert TaskEventType.RUN_STARTED not in {
        event.event_type for event in store.read(task.task_id)
    }
