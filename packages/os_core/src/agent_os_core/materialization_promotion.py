from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Protocol

from agent_os_contracts import (
    CandidateEvaluationReceipt,
    CandidatePromotionCommand,
    CandidatePromotionDecision,
    CandidatePromotionResult,
    CandidateWriteChannel,
    CapabilityGrant,
    CapabilityGrantStatus,
    DomainCandidate,
    DomainPriorArtifact,
    MaterializationOutcome,
    PrincipalIdentity,
    PrincipalRole,
    RunStatus,
    TaskStatus,
)

from .errors import (
    CandidateConcurrentWrite,
    CandidatePromotionDenied,
    CandidatePromotionNotFound,
    CandidatePromotionScopeMismatch,
    TaskNotFoundError,
)
from .governance import CorrectionGuard
from .materialization import SEALER_ID
from .materialization_promotion_persistence import (
    CandidatePromotionRecordRequest,
    CandidatePromotionStore,
    candidate_promotion_idempotency_key,
    candidate_promotion_payload_digest,
    candidate_receipt_chain_digest,
)
from .materialization_promotion_policy import (
    PROMOTION_POLICY_V1_DIGEST,
    PromotionPolicyRegistry,
)
from .task_aggregate import TaskAggregate
from .task_service import Clock


PROMOTION_CAPABILITY = "domain.candidate.promote"
PROMOTION_CAPABILITY_VERSION = "1"
PROMOTION_POLICY_VERSION = "ADM-P3-POLICY-V1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskReader(Protocol):
    def get_task(self, task_id: str) -> TaskAggregate: ...


class CandidateReader(Protocol):
    def get_by_digest(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> DomainCandidate | None: ...


class CandidateEvaluationReader(Protocol):
    def list_for_candidate(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidateEvaluationReceipt, ...]: ...


class DomainCandidatePromotionService:
    def __init__(
        self,
        tasks: TaskReader,
        correction: CorrectionGuard,
        candidates: CandidateReader,
        evaluations: CandidateEvaluationReader,
        promotions: CandidatePromotionStore,
        grants: Mapping[str, CapabilityGrant],
        policies: PromotionPolicyRegistry,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._tasks = tasks
        self._correction = correction
        self._candidates = candidates
        self._evaluations = evaluations
        self._promotions = promotions
        self._grants = grants
        self._policies = policies
        self._clock = clock

    def decide(
        self,
        principal: PrincipalIdentity,
        candidate_task_id: str,
        candidate_digest: str,
        command: CandidatePromotionCommand,
    ) -> CandidatePromotionResult:
        candidate = self._load_candidate(
            principal,
            candidate_task_id,
            candidate_digest,
        )
        self._validate_command_route(
            candidate, candidate_task_id, candidate_digest, command
        )
        self._validate_candidate(candidate)
        receipts = self._evaluations.list_for_candidate(
            principal.tenant_id,
            principal.workspace_id,
            candidate_digest,
        )
        self._validate_complete_chain(candidate, command, receipts)
        task = self._load_promotion_task(command.promotion_task_id)
        self._validate_task_and_scope(task, principal, candidate, receipts, command)
        now = self._clock()
        self._validate_grant(principal, command, now)
        self._validate_fifth_party_identity(principal, candidate, receipts)

        policy = self._policies.resolve(
            PROMOTION_POLICY_VERSION,
            PROMOTION_POLICY_V1_DIGEST,
        )
        reduction = policy.reduce(candidate, receipts)
        receipt_chain_digest = candidate_receipt_chain_digest(
            candidate.candidate_digest,
            receipts,
        )
        payload_digest = candidate_promotion_payload_digest(
            command,
            candidate,
            receipt_chain_digest,
            policy.version,
            policy.digest,
            reduction,
            principal.principal_id,
        )
        idempotency_key = candidate_promotion_idempotency_key(
            command,
            policy.version,
            policy.digest,
            principal.principal_id,
        )
        if self._correction.halted(
            command.promotion_task_id,
            command.promotion_run_id,
            PROMOTION_CAPABILITY,
        ):
            raise CandidatePromotionDenied(
                "candidate promotion is halted by correction authority"
            )
        observed_epochs = self._correction.snapshot(
            command.promotion_task_id,
            command.promotion_run_id,
            PROMOTION_CAPABILITY,
        )
        request = CandidatePromotionRecordRequest(
            command=command,
            candidate=candidate,
            receipt_chain_digest=receipt_chain_digest,
            policy_version=policy.version,
            policy_digest=policy.digest,
            reduction=reduction,
            payload_digest=payload_digest,
            idempotency_key=idempotency_key,
            decided_by=principal.principal_id,
            decided_at=now,
            observed_correction_epochs=observed_epochs,
        )
        with self._correction.guard_unchanged(
            command.promotion_task_id,
            command.promotion_run_id,
            PROMOTION_CAPABILITY,
            observed_epochs,
        ) as unchanged:
            if not unchanged:
                raise CandidatePromotionDenied(
                    "correction epoch changed before promotion append"
                )
            return self._promotions.append(request)

    def list_decisions(
        self,
        principal: PrincipalIdentity,
        candidate_task_id: str,
        candidate_digest: str,
    ) -> tuple[CandidatePromotionDecision, ...]:
        candidate = self._load_candidate(
            principal,
            candidate_task_id,
            candidate_digest,
        )
        self._validate_read_scope(principal, candidate)
        return self._promotions.list_decisions(
            principal.tenant_id,
            principal.workspace_id,
            candidate_digest,
        )

    def list_priors(
        self,
        principal: PrincipalIdentity,
        candidate_task_id: str,
        candidate_digest: str,
    ) -> tuple[DomainPriorArtifact, ...]:
        candidate = self._load_candidate(
            principal,
            candidate_task_id,
            candidate_digest,
        )
        self._validate_read_scope(principal, candidate)
        return self._promotions.list_priors(
            principal.tenant_id,
            principal.workspace_id,
            candidate_digest,
        )

    def _load_candidate(
        self,
        principal: PrincipalIdentity,
        candidate_task_id: str,
        candidate_digest: str,
    ) -> DomainCandidate:
        candidate = self._candidates.get_by_digest(
            principal.tenant_id,
            principal.workspace_id,
            candidate_digest,
        )
        if candidate is None or candidate.draft.task_id != candidate_task_id:
            raise CandidatePromotionNotFound("candidate was not found in route scope")
        return candidate

    @staticmethod
    def _validate_command_route(
        candidate: DomainCandidate,
        candidate_task_id: str,
        candidate_digest: str,
        command: CandidatePromotionCommand,
    ) -> None:
        if (
            command.candidate_digest != candidate_digest
            or command.candidate_task_id != candidate_task_id
            or command.candidate_digest != candidate.candidate_digest
            or command.candidate_task_id != candidate.draft.task_id
        ):
            raise CandidatePromotionScopeMismatch(
                "promotion command does not match candidate route"
            )

    @staticmethod
    def _validate_candidate(candidate: DomainCandidate) -> None:
        draft = candidate.draft
        if (
            draft.outcome is not MaterializationOutcome.CANDIDATE
            or draft.requested_channel is not CandidateWriteChannel.R
            or draft.representation_patch is None
            or not draft.provenance
        ):
            raise CandidatePromotionDenied(
                "only an R-channel CANDIDATE may receive a promotion decision"
            )
        if candidate.sealed_by != SEALER_ID:
            raise CandidatePromotionDenied(
                "candidate was not sealed by the fixed Product sealer"
            )

    @staticmethod
    def _validate_complete_chain(
        candidate: DomainCandidate,
        command: CandidatePromotionCommand,
        receipts: tuple[CandidateEvaluationReceipt, ...],
    ) -> None:
        parent: str | None = None
        for expected_version, receipt in enumerate(receipts, start=1):
            draft = receipt.draft
            if receipt.evaluation_version != expected_version:
                raise CandidatePromotionScopeMismatch(
                    "evaluation receipt chain has a version gap"
                )
            if draft.parent_evaluation_digest != parent:
                raise CandidatePromotionScopeMismatch(
                    "evaluation receipt chain has a parent break"
                )
            if (
                draft.candidate_digest != candidate.candidate_digest
                or draft.candidate_task_id != candidate.draft.task_id
                or draft.tenant_id != candidate.draft.tenant_id
                or draft.workspace_id != candidate.draft.workspace_id
            ):
                raise CandidatePromotionScopeMismatch(
                    "evaluation receipt chain scope mismatch"
                )
            parent = receipt.evaluation_digest
        actual_head = receipts[-1].evaluation_digest if receipts else None
        if command.expected_evaluation_head_digest != actual_head:
            raise CandidateConcurrentWrite(
                "promotion command does not bind the exact latest evaluation head"
            )

    def _load_promotion_task(self, task_id: str) -> TaskAggregate:
        try:
            return self._tasks.get_task(task_id)
        except TaskNotFoundError as exc:
            raise CandidatePromotionNotFound("promotion Task was not found") from exc

    @staticmethod
    def _validate_task_and_scope(
        task: TaskAggregate,
        principal: PrincipalIdentity,
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
        command: CandidatePromotionCommand,
    ) -> None:
        goal = task.goal
        commitment = task.commitment
        run = task.run
        if goal is None or commitment is None or run is None:
            raise CandidatePromotionDenied(
                "promotion requires an active committed Task and Run"
            )
        if task.status is not TaskStatus.RUNNING or run.status is not RunStatus.RUNNING:
            raise CandidatePromotionDenied(
                "promotion requires Task and Run status RUNNING"
            )
        if (
            task.task_id != command.promotion_task_id
            or run.run_id != command.promotion_run_id
        ):
            raise CandidatePromotionScopeMismatch(
                "promotion Task or Run scope mismatch"
            )
        if principal.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise CandidatePromotionDenied(
                "promotion requires PRINCIPAL or TENANT_ADMIN role"
            )
        if (
            goal.created_by != principal.principal_id
            or commitment.accepted_by != principal.principal_id
        ):
            raise CandidatePromotionDenied(
                "promotion Goal creator and Commitment acceptor must be promoter"
            )
        if PROMOTION_CAPABILITY not in commitment.authority_scopes:
            raise CandidatePromotionDenied(
                "promotion Commitment lacks the raw capability authority scope"
            )
        expected_scope = (commitment.tenant_id, commitment.workspace_id)
        if (
            (run.tenant_id, run.workspace_id) != expected_scope
            or (principal.tenant_id, principal.workspace_id) != expected_scope
            or (command.tenant_id, command.workspace_id) != expected_scope
            or (candidate.draft.tenant_id, candidate.draft.workspace_id)
            != expected_scope
        ):
            raise CandidatePromotionScopeMismatch(
                "promotion principal, tenant or workspace scope mismatch"
            )
        if (
            task.task_id == candidate.draft.task_id
            or run.run_id == candidate.draft.materialization_run_id
        ):
            raise CandidatePromotionDenied(
                "promotion Task and Run must be distinct from candidate generation"
            )
        if any(
            receipt.draft.evaluation_task_id == task.task_id
            or receipt.draft.evaluation_run_id == run.run_id
            for receipt in receipts
        ):
            raise CandidatePromotionDenied(
                "promotion Task and Run must be distinct from every evaluation"
            )

    def _validate_grant(
        self,
        principal: PrincipalIdentity,
        command: CandidatePromotionCommand,
        now: datetime,
    ) -> None:
        grant = self._grants.get(PROMOTION_CAPABILITY)
        if grant is None:
            raise CandidatePromotionDenied("promotion capability grant is missing")
        if (
            grant.status is not CapabilityGrantStatus.ACTIVE
            or grant.expires_at <= now
            or grant.capability_id != PROMOTION_CAPABILITY
            or grant.capability_version != PROMOTION_CAPABILITY_VERSION
            or grant.principal_id != principal.principal_id
            or grant.tenant_id != command.tenant_id
            or grant.workspace_id != command.workspace_id
        ):
            raise CandidatePromotionDenied(
                "promotion capability grant is inactive, expired or out of scope"
            )

    @staticmethod
    def _validate_fifth_party_identity(
        principal: PrincipalIdentity,
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
    ) -> None:
        forbidden = {
            candidate.draft.submitted_by,
            candidate.sealed_by,
            *(receipt.draft.evaluator.evaluator_id for receipt in receipts),
            *(receipt.recorded_by for receipt in receipts),
        }
        if principal.principal_id in forbidden:
            raise CandidatePromotionDenied(
                "promoter must be distinct from builder, sealer, evaluators and recorders"
            )

    @staticmethod
    def _validate_read_scope(
        principal: PrincipalIdentity,
        candidate: DomainCandidate,
    ) -> None:
        if (
            principal.tenant_id != candidate.draft.tenant_id
            or principal.workspace_id != candidate.draft.workspace_id
        ):
            raise CandidatePromotionScopeMismatch(
                "candidate promotion listing scope mismatch"
            )
