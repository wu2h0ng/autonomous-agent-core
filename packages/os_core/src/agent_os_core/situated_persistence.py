from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeAlias

from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    HelpRequest,
    MandateOperationalStatus,
    RatifiedMandateRef,
    RelevanceAssessment,
    SituatedAssessmentOutcomeKind,
    SituatedAssessmentRecord,
    TaskDraftProposal,
    canonical_json,
)

from .errors import SituationalPersistenceConflict, SituationalTrustDenied


ProposalResult: TypeAlias = TaskDraftProposal | HelpRequest | None


def situated_assessment_record(
    assessment: RelevanceAssessment,
    result: ProposalResult,
    *,
    source_binding_digest: str,
) -> SituatedAssessmentRecord:
    outcome_kind = SituatedAssessmentOutcomeKind.NO_PROPOSAL
    task_draft = None
    help_request = None
    if isinstance(result, TaskDraftProposal):
        outcome_kind = SituatedAssessmentOutcomeKind.TASK_DRAFT
        task_draft = result
    elif isinstance(result, HelpRequest):
        outcome_kind = SituatedAssessmentOutcomeKind.HELP_REQUEST
        help_request = result
    return SituatedAssessmentRecord(
        assessment_record_id=f"situated-assessment:{source_binding_digest}",
        source_binding_digest=source_binding_digest,
        tenant_id=assessment.tenant_id,
        workspace_id=assessment.workspace_id,
        assessment=assessment,
        outcome_kind=outcome_kind,
        task_draft=task_draft,
        help_request=help_request,
        recorded_at=assessment.assessed_at,
    )


def proposal_result(record: SituatedAssessmentRecord) -> ProposalResult:
    if record.outcome_kind is SituatedAssessmentOutcomeKind.TASK_DRAFT:
        return record.task_draft
    if record.outcome_kind is SituatedAssessmentOutcomeKind.HELP_REQUEST:
        return record.help_request
    return None


class SituatedAssessmentStore(Protocol):
    durable: bool

    def resolve_active(
        self,
        mandate_id: str,
        environment_binding_id: str,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]: ...

    def _emit_guarded(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        assessment: RelevanceAssessment,
        *,
        principal_id: str,
        evaluated_at: datetime,
        source_binding_digest: str,
        factory: Callable[[], ProposalResult],
    ) -> ProposalResult: ...

    def assessment(self, assessment_id: str) -> RelevanceAssessment | None: ...

    def assessment_record(
        self, assessment_id: str
    ) -> SituatedAssessmentRecord | None: ...

    def record_by_source_binding(
        self, source_binding_digest: str
    ) -> SituatedAssessmentRecord | None: ...

    def pause(self, mandate_id: str, *, expected_epoch: int) -> RatifiedMandateRef: ...

    def revoke(self, mandate_id: str, *, expected_epoch: int) -> RatifiedMandateRef: ...


class SQLiteSituatedAssessmentStore:
    """Durable V0 Mandate authority and proposal-only assessment ledger."""

    durable = True

    def __init__(
        self,
        database: str | Path,
        *,
        mandates: Iterable[RatifiedMandateRef] = (),
    ) -> None:
        self._database = str(database)
        if self._database == ":memory:":
            raise ValueError(
                "SQLite situated authority requires a file-backed database"
            )
        self._initialize()
        for mandate in mandates:
            self._bootstrap_mandate(mandate)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS situated_mandates (
                    mandate_id TEXT PRIMARY KEY,
                    mandate_version INTEGER NOT NULL,
                    mandate_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    correction_epoch INTEGER NOT NULL,
                    mandate_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS situated_assessment_records (
                    assessment_id TEXT PRIMARY KEY,
                    assessment_record_id TEXT NOT NULL UNIQUE,
                    source_binding_digest TEXT NOT NULL UNIQUE,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _decode_mandate(payload: str) -> RatifiedMandateRef:
        try:
            return RatifiedMandateRef.model_validate_json(payload)
        except Exception:
            raise SituationalPersistenceConflict(
                "durable ratified mandate state is invalid"
            ) from None

    @staticmethod
    def _decode_record(payload: str) -> SituatedAssessmentRecord:
        try:
            return SituatedAssessmentRecord.model_validate_json(payload)
        except Exception:
            raise SituationalPersistenceConflict(
                "durable situated assessment state is invalid"
            ) from None

    @staticmethod
    def _same_authority_root(
        current: RatifiedMandateRef,
        proposed: RatifiedMandateRef,
    ) -> bool:
        return (
            current.model_copy(
                update={
                    "status": proposed.status,
                    "correction_epoch": proposed.correction_epoch,
                }
            )
            == proposed
        )

    def _bootstrap_mandate(self, mandate: RatifiedMandateRef) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT mandate_json FROM situated_mandates WHERE mandate_id = ?",
                (mandate.mandate_id,),
            ).fetchone()
            if row is not None:
                current = self._decode_mandate(str(row["mandate_json"]))
                if not self._same_authority_root(current, mandate):
                    raise SituationalPersistenceConflict(
                        "ratified mandate identity conflicts with durable authority"
                    )
                connection.rollback()
                return
            connection.execute(
                """
                INSERT INTO situated_mandates (
                    mandate_id, mandate_version, mandate_digest,
                    status, correction_epoch, mandate_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    mandate.mandate_id,
                    mandate.version,
                    mandate.mandate_digest,
                    mandate.status.value,
                    mandate.correction_epoch,
                    canonical_json(mandate),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read_mandate(
        self,
        connection: sqlite3.Connection,
        mandate_id: str,
    ) -> RatifiedMandateRef:
        row = connection.execute(
            "SELECT mandate_json FROM situated_mandates WHERE mandate_id = ?",
            (mandate_id,),
        ).fetchone()
        if row is None:
            raise SituationalTrustDenied("ratified mandate is unavailable")
        return self._decode_mandate(str(row["mandate_json"]))

    @staticmethod
    def _resolve_active_mandate(
        mandate: RatifiedMandateRef,
        environment_binding_id: str,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]:
        if (
            mandate.owner_principal_id != principal_id
            or mandate.tenant_id != tenant_id
            or mandate.workspace_id != workspace_id
        ):
            raise SituationalTrustDenied("ratified mandate scope is not authorized")
        if mandate.status is not MandateOperationalStatus.ACTIVE:
            raise SituationalTrustDenied("ratified mandate is not active")
        if evaluated_at < mandate.valid_from or evaluated_at >= mandate.expires_at:
            raise SituationalTrustDenied(
                "ratified mandate is not active at evaluation time"
            )
        binding = mandate.binding(environment_binding_id)
        if binding is None:
            raise SituationalTrustDenied("environment binding is not ratified")
        return mandate, binding

    def resolve_active(
        self,
        mandate_id: str,
        environment_binding_id: str,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]:
        connection = self._connect()
        try:
            mandate = self._read_mandate(connection, mandate_id)
        finally:
            connection.close()
        return self._resolve_active_mandate(
            mandate,
            environment_binding_id,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluated_at=evaluated_at,
        )

    def _emit_guarded(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        assessment: RelevanceAssessment,
        *,
        principal_id: str,
        evaluated_at: datetime,
        source_binding_digest: str,
        factory: Callable[[], ProposalResult],
    ) -> ProposalResult:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._read_mandate(connection, mandate.mandate_id)
            current, current_binding = self._resolve_active_mandate(
                current,
                binding.environment_binding_id,
                principal_id=principal_id,
                tenant_id=mandate.tenant_id,
                workspace_id=mandate.workspace_id,
                evaluated_at=evaluated_at,
            )
            if current != mandate or current_binding != binding:
                raise SituationalTrustDenied(
                    "mandate or environment binding epoch changed before emission"
                )
            result = factory()
            record = situated_assessment_record(
                assessment,
                result,
                source_binding_digest=source_binding_digest,
            )
            rows = connection.execute(
                """
                SELECT record_json FROM situated_assessment_records
                WHERE assessment_id = ? OR source_binding_digest = ?
                """,
                (assessment.assessment_id, source_binding_digest),
            ).fetchall()
            if rows:
                existing = tuple(
                    self._decode_record(str(row["record_json"])) for row in rows
                )
                if len(existing) != 1 or existing[0] != record:
                    raise SituationalPersistenceConflict(
                        "assessment identity or source binding conflicts with durable record"
                    )
                connection.rollback()
                return proposal_result(existing[0])
            connection.execute(
                """
                INSERT INTO situated_assessment_records (
                    assessment_id, assessment_record_id, source_binding_digest,
                    tenant_id, workspace_id, record_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.assessment_id,
                    record.assessment_record_id,
                    record.source_binding_digest,
                    record.tenant_id,
                    record.workspace_id,
                    canonical_json(record),
                ),
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def assessment_record(self, assessment_id: str) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT record_json FROM situated_assessment_records
                WHERE assessment_id = ?
                """,
                (assessment_id,),
            ).fetchone()
        finally:
            connection.close()
        return self._decode_record(str(row["record_json"])) if row is not None else None

    def record_by_source_binding(
        self, source_binding_digest: str
    ) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT record_json FROM situated_assessment_records
                WHERE source_binding_digest = ?
                """,
                (source_binding_digest,),
            ).fetchone()
        finally:
            connection.close()
        return self._decode_record(str(row["record_json"])) if row is not None else None

    def assessment(self, assessment_id: str) -> RelevanceAssessment | None:
        record = self.assessment_record(assessment_id)
        return record.assessment if record is not None else None

    def pause(self, mandate_id: str, *, expected_epoch: int) -> RatifiedMandateRef:
        return self._change_status(
            mandate_id,
            expected_epoch=expected_epoch,
            status=MandateOperationalStatus.PAUSED,
        )

    def revoke(self, mandate_id: str, *, expected_epoch: int) -> RatifiedMandateRef:
        return self._change_status(
            mandate_id,
            expected_epoch=expected_epoch,
            status=MandateOperationalStatus.REVOKED,
        )

    def _change_status(
        self,
        mandate_id: str,
        *,
        expected_epoch: int,
        status: MandateOperationalStatus,
    ) -> RatifiedMandateRef:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._read_mandate(connection, mandate_id)
            if current.status is MandateOperationalStatus.REVOKED:
                raise SituationalTrustDenied("revoked mandate status is terminal")
            if current.correction_epoch != expected_epoch:
                raise SituationalTrustDenied("mandate correction epoch changed")
            updated = current.model_copy(
                update={
                    "status": status,
                    "correction_epoch": current.correction_epoch + 1,
                }
            )
            cursor = connection.execute(
                """
                UPDATE situated_mandates
                SET status = ?, correction_epoch = ?, mandate_json = ?
                WHERE mandate_id = ? AND correction_epoch = ?
                """,
                (
                    updated.status.value,
                    updated.correction_epoch,
                    canonical_json(updated),
                    mandate_id,
                    expected_epoch,
                ),
            )
            if cursor.rowcount != 1:
                raise SituationalTrustDenied("mandate correction epoch changed")
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
