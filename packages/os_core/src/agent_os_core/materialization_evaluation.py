from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from agent_os_contracts import (
    CandidateEvaluationDraft,
    CandidateEvaluationReceipt,
    CapabilityGrant,
    CapabilityGrantStatus,
    DomainCandidate,
    ExpectedOutcome,
    MaterializationOutcome,
    PrincipalIdentity,
    PrincipalRole,
    RunStatus,
    TaskStatus,
    content_digest,
)

from .errors import (
    CandidateEvaluationDenied,
    CandidateEvaluationNotFound,
    CandidateEvaluationScopeMismatch,
)
from .governance import CorrectionAuthority
from .materialization_evaluation_persistence import (
    EVALUATION_CONTRACT_SCHEMA,
    CandidateEvaluationRecordRequest,
    CandidateEvaluationStore,
    candidate_evaluation_idempotency_key,
    candidate_evaluation_payload_digest,
)
from .materialization_persistence import CandidateStore
from .task_aggregate import TaskAggregate
from .task_service import Clock, TaskService


EVALUATION_CAPABILITY = "domain.candidate.evaluate"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def evaluation_contract_digest(
    expected_outcome: ExpectedOutcome,
    evaluator_refs: Sequence[str],
    authority_scopes: Sequence[str],
) -> str:
    return content_digest(
        {
            "schema": EVALUATION_CONTRACT_SCHEMA,
            "expected_outcome": expected_outcome,
            "workflow_evaluator_refs": tuple(evaluator_refs),
            "commitment_authority_scopes": tuple(authority_scopes),
        }
    )


class DomainCandidateEvaluationRecorder:
    def __init__(
        self,
        tasks: TaskService,
        correction: CorrectionAuthority,
        candidates: CandidateStore,
        evaluations: CandidateEvaluationStore,
        grants: Mapping[str, CapabilityGrant],
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._tasks = tasks
        self._correction = correction
        self._candidates = candidates
        self._evaluations = evaluations
        self._grants = grants
        self._clock = clock

    def record(
        self,
        principal: PrincipalIdentity,
        candidate_task_id: str,
        candidate_digest: str,
        draft: CandidateEvaluationDraft,
    ) -> CandidateEvaluationReceipt:
        candidate = self._candidates.get_by_digest(
            principal.tenant_id,
            principal.workspace_id,
            candidate_digest,
        )
        if (
            candidate is None
            or candidate.candidate_digest != draft.candidate_digest
            or candidate.draft.task_id != candidate_task_id
            or draft.candidate_task_id != candidate_task_id
        ):
            raise CandidateEvaluationNotFound("candidate was not found in route scope")
        if candidate.draft.outcome is not MaterializationOutcome.CANDIDATE:
            raise CandidateEvaluationDenied(
                "only a CANDIDATE outcome may receive an evaluation receipt"
            )

        task = self._tasks.get_task(draft.evaluation_task_id)
        self._validate_task_and_scope(task, principal, candidate, draft)
        self._validate_grant(principal, draft)
        self._validate_independence(principal, candidate, draft)

        expected = task.expected_outcome
        workflow = task.workflow
        commitment = task.commitment
        run = task.run
        assert expected is not None
        assert workflow is not None
        assert commitment is not None
        assert run is not None
        required_ref = (
            f"evaluator:{expected.evaluator_type}:{expected.evaluator_version}"
        )
        if (
            expected.evaluator_type != draft.evaluator.evaluator_type
            or expected.evaluator_version != draft.evaluator.evaluator_version
            or required_ref not in workflow.evaluator_refs
        ):
            raise CandidateEvaluationDenied(
                "evaluation task evaluator binding does not match receipt evaluator"
            )

        contract_digest = evaluation_contract_digest(
            expected,
            workflow.evaluator_refs,
            commitment.authority_scopes,
        )
        recorded_by = principal.principal_id
        payload_digest = candidate_evaluation_payload_digest(
            draft,
            contract_digest,
            recorded_by,
        )
        idempotency_key = candidate_evaluation_idempotency_key(
            draft,
            contract_digest,
            recorded_by,
        )
        if self._correction.halted(
            draft.evaluation_task_id,
            draft.evaluation_run_id,
            EVALUATION_CAPABILITY,
        ):
            raise CandidateEvaluationDenied(
                "evaluation receipt recording is halted by correction authority"
            )
        observed_epochs = self._correction.snapshot(
            draft.evaluation_task_id,
            draft.evaluation_run_id,
            EVALUATION_CAPABILITY,
        )
        request = CandidateEvaluationRecordRequest(
            evaluation_id=f"candidate-evaluation:{payload_digest[:24]}",
            tenant_id=draft.tenant_id,
            workspace_id=draft.workspace_id,
            candidate_digest=draft.candidate_digest,
            idempotency_key=idempotency_key,
            payload_digest=payload_digest,
            recorded_by=recorded_by,
            recorded_at=self._clock(),
            observed_correction_epochs=observed_epochs,
            evaluation_contract_digest=contract_digest,
            draft=draft,
        )
        with self._correction.guard_unchanged(
            draft.evaluation_task_id,
            draft.evaluation_run_id,
            EVALUATION_CAPABILITY,
            observed_epochs,
        ) as unchanged:
            if not unchanged:
                raise CandidateEvaluationDenied(
                    "correction epoch changed before evaluation receipt append"
                )
            return self._evaluations.append(
                request,
                expected_parent_digest=draft.parent_evaluation_digest,
            )

    def list_for_candidate(
        self,
        principal: PrincipalIdentity,
        candidate_task_id: str,
        candidate_digest: str,
    ) -> tuple[CandidateEvaluationReceipt, ...]:
        candidate = self._candidates.get_by_digest(
            principal.tenant_id,
            principal.workspace_id,
            candidate_digest,
        )
        if candidate is None or candidate.draft.task_id != candidate_task_id:
            raise CandidateEvaluationNotFound("candidate was not found in route scope")
        if (
            candidate.draft.tenant_id != principal.tenant_id
            or candidate.draft.workspace_id != principal.workspace_id
        ):
            raise CandidateEvaluationScopeMismatch(
                "candidate evaluation listing scope mismatch"
            )
        return self._evaluations.list_for_candidate(
            principal.tenant_id,
            principal.workspace_id,
            candidate_digest,
        )

    def _validate_task_and_scope(
        self,
        task: TaskAggregate,
        principal: PrincipalIdentity,
        candidate: DomainCandidate,
        draft: CandidateEvaluationDraft,
    ) -> None:
        commitment = task.commitment
        goal = task.goal
        run = task.run
        if commitment is None or goal is None or run is None:
            raise CandidateEvaluationDenied(
                "evaluation recording requires an active committed run"
            )
        if task.status is not TaskStatus.RUNNING or run.status is not RunStatus.RUNNING:
            raise CandidateEvaluationDenied(
                "evaluation recording requires Task and Run status RUNNING"
            )
        if (
            task.task_id != draft.evaluation_task_id
            or run.run_id != draft.evaluation_run_id
        ):
            raise CandidateEvaluationScopeMismatch(
                "evaluation task or run scope mismatch"
            )
        candidate_draft = candidate.draft
        if (
            candidate_draft.task_id == draft.evaluation_task_id
            or candidate_draft.materialization_run_id == draft.evaluation_run_id
        ):
            raise CandidateEvaluationDenied(
                "candidate generation and evaluation require distinct Task and Run"
            )
        expected_scope = (commitment.tenant_id, commitment.workspace_id)
        if (
            (run.tenant_id, run.workspace_id) != expected_scope
            or (principal.tenant_id, principal.workspace_id) != expected_scope
            or (draft.tenant_id, draft.workspace_id) != expected_scope
            or (candidate_draft.tenant_id, candidate_draft.workspace_id)
            != expected_scope
        ):
            raise CandidateEvaluationScopeMismatch(
                "candidate evaluation principal, tenant or workspace scope mismatch"
            )
        if principal.role in {PrincipalRole.MODEL, PrincipalRole.PLUGIN}:
            raise CandidateEvaluationDenied(
                "MODEL and PLUGIN identities cannot record evaluation receipts"
            )
        if (
            goal.created_by != principal.principal_id
            or commitment.accepted_by != principal.principal_id
        ):
            raise CandidateEvaluationDenied(
                "evaluation Goal creator and Commitment acceptor must be recorder"
            )
        if EVALUATION_CAPABILITY not in commitment.authority_scopes:
            raise CandidateEvaluationDenied(
                "evaluation Commitment lacks required authority scope"
            )

    def _validate_grant(
        self,
        principal: PrincipalIdentity,
        draft: CandidateEvaluationDraft,
    ) -> None:
        grant = self._grants.get(EVALUATION_CAPABILITY)
        if grant is None:
            raise CandidateEvaluationDenied("evaluation capability grant is missing")
        if (
            grant.status is not CapabilityGrantStatus.ACTIVE
            or grant.expires_at <= self._clock()
            or grant.capability_id != EVALUATION_CAPABILITY
            or grant.capability_version != "1"
            or grant.principal_id != principal.principal_id
            or grant.tenant_id != draft.tenant_id
            or grant.workspace_id != draft.workspace_id
        ):
            raise CandidateEvaluationDenied(
                "evaluation capability grant is inactive, expired or out of scope"
            )

    @staticmethod
    def _validate_independence(
        principal: PrincipalIdentity,
        candidate: DomainCandidate,
        draft: CandidateEvaluationDraft,
    ) -> None:
        candidate_draft = candidate.draft
        sealed_by = candidate.sealed_by
        forbidden_identities = {candidate_draft.submitted_by, sealed_by}
        if (
            principal.principal_id in forbidden_identities
            or draft.evaluator.evaluator_id in forbidden_identities
        ):
            raise CandidateEvaluationDenied(
                "candidate builder or sealer cannot record/bind its evaluation"
            )
        if draft.evaluator.implementation_digest == candidate_draft.mechanism_digest:
            raise CandidateEvaluationDenied(
                "candidate mechanism cannot be reused as evaluator implementation"
            )
