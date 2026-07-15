from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from agent_os_contracts import (
    CandidateProvenance,
    DomainCandidate,
    DomainCandidateDraft,
    MaterializationOutcome,
    PrincipalIdentity,
    RunStatus,
    TaskStatus,
    canonical_json,
    content_digest,
)

from .errors import (
    CandidateIdempotencyConflict,
    CandidateProvenanceError,
    CandidateScopeMismatch,
    CandidateSealingDenied,
)
from .governance import CorrectionGuard
from .materialization_persistence import CandidateSealRequest, CandidateStore
from .task_aggregate import TaskAggregate
from .task_service import TaskService


IDEMPOTENCY_SCHEMA = "ADM-P1-IDEMPOTENCY-V1"
SOURCE_SNAPSHOT_SCHEMA = "ADM-P1-SOURCE-SNAPSHOT-V1"
SEALER_ID = "system:domain-candidate-sealer:v1"
MATERIALIZATION_CAPABILITY = "domain.materialize"


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def candidate_source_snapshot_digest(
    provenance: Sequence[CandidateProvenance],
) -> str:
    sources = [
        {
            "source_id": item.source_id,
            "source_ref": item.source_ref,
            "source_type": item.source_type,
            "source_digest": item.source_digest,
            "accessed_at": item.accessed_at,
            "effective_at": item.effective_at,
            "license_or_terms_id": item.license_or_terms_id,
            "permitted_use": item.permitted_use,
            "redistribution_allowed": item.redistribution_allowed,
            "custodian_verified_by": item.custodian_verified_by,
            "derivation_input_digests": item.derivation_input_digests,
            "expires_at": item.expires_at,
        }
        for item in provenance
    ]
    sources.sort(key=canonical_json)
    return content_digest(
        {
            "schema": SOURCE_SNAPSHOT_SCHEMA,
            "sources": sources,
        }
    )


class DomainCandidateSealer:
    def __init__(
        self,
        tasks: TaskService,
        correction: CorrectionGuard,
        store: CandidateStore,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._tasks = tasks
        self._correction = correction
        self._store = store
        self._clock = clock

    def seal(
        self,
        principal: PrincipalIdentity,
        draft: DomainCandidateDraft,
    ) -> DomainCandidate:
        task = self._tasks.get_task(draft.task_id)
        self._require_scope_and_running_materialization(task, principal, draft)
        if self._correction.halted(
            draft.task_id,
            draft.materialization_run_id,
            MATERIALIZATION_CAPABILITY,
        ):
            raise CandidateSealingDenied(
                "materialization is halted by correction authority"
            )
        observed_epochs = self._correction.snapshot(
            draft.task_id,
            draft.materialization_run_id,
            MATERIALIZATION_CAPABILITY,
        )
        self._validate_provenance(draft)
        payload_digest = content_digest(draft)
        key = content_digest(
            {
                "schema": IDEMPOTENCY_SCHEMA,
                "tenant_id": draft.tenant_id,
                "workspace_id": draft.workspace_id,
                "task_id": draft.task_id,
                "run_id": draft.materialization_run_id,
                "source_snapshot_digest": draft.source_snapshot_digest,
                "mechanism_digest": draft.mechanism_digest,
                "parent_candidate_digest": draft.parent_candidate_digest,
                "requested_channel": draft.requested_channel,
                "contract_schema_version": draft.schema_version,
            }
        )
        existing = self._store.get_by_idempotency(
            draft.tenant_id,
            draft.workspace_id,
            key,
        )
        with self._correction.guard_unchanged(
            draft.task_id,
            draft.materialization_run_id,
            MATERIALIZATION_CAPABILITY,
            observed_epochs,
        ) as unchanged:
            if not unchanged:
                raise CandidateSealingDenied(
                    "correction epoch changed before candidate append"
                )
            if existing is not None:
                if existing.payload_digest != payload_digest:
                    raise CandidateIdempotencyConflict(
                        "same derived key has different payload"
                    )
                return existing
            request = CandidateSealRequest(
                candidate_id=f"domain-candidate:{payload_digest[:24]}",
                tenant_id=draft.tenant_id,
                workspace_id=draft.workspace_id,
                task_id=draft.task_id,
                payload_digest=payload_digest,
                idempotency_key=key,
                sealed_by=SEALER_ID,
                sealed_at=self._clock(),
                observed_correction_epochs=observed_epochs,
                draft=draft,
            )
            return self._store.append(
                request,
                expected_parent_digest=draft.parent_candidate_digest,
            )

    def list_for_task(
        self,
        principal: PrincipalIdentity,
        task_id: str,
    ) -> tuple[DomainCandidate, ...]:
        task = self._tasks.get_task(task_id)
        commitment = task.commitment
        if commitment is None:
            raise CandidateScopeMismatch(
                "candidate listing requires a committed task scope"
            )
        if (
            principal.tenant_id != commitment.tenant_id
            or principal.workspace_id != commitment.workspace_id
        ):
            raise CandidateScopeMismatch("candidate listing scope mismatch")
        return self._store.list_for_task(
            commitment.tenant_id,
            commitment.workspace_id,
            task_id,
        )

    @staticmethod
    def _require_scope_and_running_materialization(
        task: TaskAggregate,
        principal: PrincipalIdentity,
        draft: DomainCandidateDraft,
    ) -> None:
        commitment = task.commitment
        run = task.run
        if commitment is None or run is None:
            raise CandidateSealingDenied(
                "candidate sealing requires an active committed run"
            )
        if task.status is not TaskStatus.RUNNING or run.status is not RunStatus.RUNNING:
            raise CandidateSealingDenied(
                "candidate sealing requires Task and Run status RUNNING"
            )
        if task.task_id != draft.task_id or run.run_id != draft.materialization_run_id:
            raise CandidateScopeMismatch("candidate task or run scope mismatch")
        expected_scope = (commitment.tenant_id, commitment.workspace_id)
        if (
            (run.tenant_id, run.workspace_id) != expected_scope
            or (principal.tenant_id, principal.workspace_id) != expected_scope
            or (draft.tenant_id, draft.workspace_id) != expected_scope
            or draft.submitted_by != principal.principal_id
        ):
            raise CandidateScopeMismatch(
                "candidate principal, tenant or workspace scope mismatch"
            )

    def _validate_provenance(self, draft: DomainCandidateDraft) -> None:
        if draft.source_snapshot_digest != candidate_source_snapshot_digest(
            draft.provenance
        ):
            raise CandidateProvenanceError("candidate source snapshot digest mismatch")
        now = self._clock()
        if any(item.expires_at <= now for item in draft.provenance):
            raise CandidateProvenanceError("candidate provenance is expired")
        if (
            draft.outcome is MaterializationOutcome.CANDIDATE
            and not draft.provenance
        ):
            raise CandidateProvenanceError(
                "candidate outcome requires source provenance"
            )
