from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeAlias

from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    HelpRequest,
    LedgerAccessScope,
    MandateOperationalStatus,
    MandateObservationAuthorizationCommand,
    MandateObservationAuthorizationReceipt,
    MandateWorkspaceRecord,
    RatifiedMandateRef,
    RelevanceAssessment,
    SituatedAssessmentOutcomeKind,
    SituatedAssessmentRecord,
    TaskDraftProposal,
    canonical_json,
    content_digest,
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

    def record_by_input_binding(
        self, input_binding_digest: str
    ) -> SituatedAssessmentRecord | None: ...

    def record_by_result_digest(
        self, result_digest: str
    ) -> SituatedAssessmentRecord | None: ...

    def replay_if_active(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        input_binding_digest: str,
        *,
        principal_id: str,
        evaluated_at: datetime,
    ) -> SituatedAssessmentRecord | None: ...

class ScopedSituatedAssessmentReader(Protocol):
    scope: LedgerAccessScope

    def resolve_active(
        self,
        mandate_id: str,
        environment_binding_id: str,
        *,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]: ...

    def record_by_input_binding(
        self, input_binding_digest: str
    ) -> SituatedAssessmentRecord | None: ...

    def record_by_result_digest(
        self, result_digest: str
    ) -> SituatedAssessmentRecord | None: ...


class _ScopedSituatedAssessmentFacade:
    __slots__ = ("_store", "scope")

    def __init__(
        self, store: SituatedAssessmentStore, scope: LedgerAccessScope
    ) -> None:
        self._store = store
        self.scope = scope

    def resolve_active(
        self,
        mandate_id: str,
        environment_binding_id: str,
        *,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]:
        return self._store.resolve_active(
            mandate_id,
            environment_binding_id,
            principal_id=self.scope.principal_id,
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            evaluated_at=evaluated_at,
        )

    def record_by_input_binding(
        self, input_binding_digest: str
    ) -> SituatedAssessmentRecord | None:
        scoped_lookup = getattr(self._store, "_record_by_input_binding_scoped", None)
        if scoped_lookup is None:
            raise SituationalPersistenceConflict(
                "durable assessment store lacks scoped lookup capability"
            )
        record = scoped_lookup(input_binding_digest, scope=self.scope)
        if record is None:
            return None
        if (
            record.tenant_id != self.scope.tenant_id
            or record.workspace_id != self.scope.workspace_id
            or record.assessment.tenant_id != self.scope.tenant_id
            or record.assessment.workspace_id != self.scope.workspace_id
        ):
            return None
        mandate, binding = self._store.resolve_active(
            record.assessment.mandate_id,
            record.assessment.environment_binding_id,
            principal_id=self.scope.principal_id,
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            evaluated_at=record.assessment.assessed_at,
        )
        if (
            mandate.owner_principal_id != self.scope.principal_id
            or binding.environment_binding_id
            != record.assessment.environment_binding_id
        ):
            raise SituationalPersistenceConflict(
                "durable assessment scope conflicts with ratified mandate"
            )
        return record

    def record_by_result_digest(
        self, result_digest: str
    ) -> SituatedAssessmentRecord | None:
        scoped_lookup = getattr(self._store, "_record_by_result_digest_scoped", None)
        if scoped_lookup is None:
            raise SituationalPersistenceConflict(
                "durable assessment store lacks scoped result lookup capability"
            )
        return scoped_lookup(result_digest, scope=self.scope)


def scoped_situated_assessment_reader(
    store: SituatedAssessmentStore, scope: LedgerAccessScope
) -> ScopedSituatedAssessmentReader:
    return _ScopedSituatedAssessmentFacade(store, scope)


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
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    mandate_id TEXT NOT NULL,
                    mandate_version INTEGER NOT NULL,
                    mandate_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    correction_epoch INTEGER NOT NULL,
                    mandate_json TEXT NOT NULL,
                    PRIMARY KEY (principal_id, tenant_id, workspace_id, mandate_id)
                )
                """
            )
            mandate_expected = (
                ("principal_id", "TEXT", 1, 1),
                ("tenant_id", "TEXT", 1, 2),
                ("workspace_id", "TEXT", 1, 3),
                ("mandate_id", "TEXT", 1, 4),
                ("mandate_version", "INTEGER", 1, 0),
                ("mandate_digest", "TEXT", 1, 0),
                ("status", "TEXT", 1, 0),
                ("correction_epoch", "INTEGER", 1, 0),
                ("mandate_json", "TEXT", 1, 0),
            )
            mandate_actual = tuple(
                (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
                for row in connection.execute(
                    "PRAGMA table_info(situated_mandates)"
                ).fetchall()
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS situated_assessment_records (
                    assessment_id TEXT NOT NULL,
                    assessment_record_id TEXT NOT NULL,
                    source_binding_digest TEXT NOT NULL,
                    input_binding_digest TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            for name, columns in (
                ("ux_situated_assessment_id_scope", "principal_id, tenant_id, workspace_id, assessment_id"),
                ("ux_situated_assessment_record_id_scope", "principal_id, tenant_id, workspace_id, assessment_record_id"),
                ("ux_situated_source_binding_scope", "principal_id, tenant_id, workspace_id, source_binding_digest"),
                ("ux_situated_input_binding_scope", "principal_id, tenant_id, workspace_id, input_binding_digest"),
            ):
                connection.execute(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {name} "
                    f"ON situated_assessment_records ({columns})"
                )
            expected = (
                ("assessment_id", "TEXT", 1, 0),
                ("assessment_record_id", "TEXT", 1, 0),
                ("source_binding_digest", "TEXT", 1, 0),
                ("input_binding_digest", "TEXT", 1, 0),
                ("principal_id", "TEXT", 1, 0),
                ("tenant_id", "TEXT", 1, 0),
                ("workspace_id", "TEXT", 1, 0),
                ("record_json", "TEXT", 1, 0),
            )
            actual = tuple(
                (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
                for row in connection.execute(
                    "PRAGMA table_info(situated_assessment_records)"
                ).fetchall()
            )
            unique_columns = {
                tuple(
                    str(column[2])
                    for column in connection.execute(
                        f"PRAGMA index_info({row[1]})"
                    ).fetchall()
                )
                for row in connection.execute(
                    "PRAGMA index_list(situated_assessment_records)"
                ).fetchall()
                if int(row[2]) == 1
            }
            expected_unique = {
                ("principal_id", "tenant_id", "workspace_id", "assessment_id"),
                ("principal_id", "tenant_id", "workspace_id", "assessment_record_id"),
                ("principal_id", "tenant_id", "workspace_id", "source_binding_digest"),
                ("principal_id", "tenant_id", "workspace_id", "input_binding_digest"),
            }
            if (
                mandate_actual != mandate_expected
                or actual != expected
                or unique_columns != expected_unique
            ):
                raise SituationalPersistenceConflict(
                    "existing SQLite situated assessment schema is invalid"
                )
        except sqlite3.Error:
            raise SituationalPersistenceConflict(
                "existing SQLite situated assessment schema is invalid"
            ) from None
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
                """SELECT mandate_json FROM situated_mandates
                   WHERE principal_id = ? AND tenant_id = ?
                     AND workspace_id = ? AND mandate_id = ?""",
                (
                    mandate.owner_principal_id,
                    mandate.tenant_id,
                    mandate.workspace_id,
                    mandate.mandate_id,
                ),
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
                    principal_id, tenant_id, workspace_id,
                    mandate_id, mandate_version, mandate_digest,
                    status, correction_epoch, mandate_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mandate.owner_principal_id,
                    mandate.tenant_id,
                    mandate.workspace_id,
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
        *,
        principal_id: str | None = None,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> RatifiedMandateRef:
        if principal_id is None or tenant_id is None or workspace_id is None:
            rows = connection.execute(
                "SELECT mandate_json FROM situated_mandates WHERE mandate_id = ?",
                (mandate_id,),
            ).fetchall()
            if len(rows) != 1:
                raise SituationalTrustDenied(
                    "ratified mandate scope is required or ambiguous"
                )
            row = rows[0]
        else:
            row = connection.execute(
                """SELECT mandate_json FROM situated_mandates
                   WHERE principal_id = ? AND tenant_id = ?
                     AND workspace_id = ? AND mandate_id = ?""",
                (principal_id, tenant_id, workspace_id, mandate_id),
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
            mandate = self._read_mandate(
                connection,
                mandate_id,
                principal_id=principal_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
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

    def resolve_observation_authority(
        self,
        mandate_id: str,
        environment_binding_id: str,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        evaluated_at: datetime,
        source_descriptor_digest: str,
        relevance_assessor: object,
        relevance_context: object,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]:
        mandate, binding = self.resolve_active(
            mandate_id,
            environment_binding_id,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluated_at=evaluated_at,
        )
        if (
            mandate.observation_authorization_id is None
            or mandate.observation_authorization_receipt_digest is None
            or mandate.workspace_record_digest is None
        ):
            raise SituationalTrustDenied(
                "verified observation authorization provenance is unavailable"
            )
        connection = self._connect()
        try:
            authorization_rows = connection.execute(
                """SELECT * FROM mandate_observation_authorizations
                   WHERE tenant_id = ? AND workspace_id = ?
                     AND mandate_id = ? AND authorization_id = ?
                     AND environment_binding_id = ?""",
                (
                    tenant_id,
                    workspace_id,
                    mandate_id,
                    mandate.observation_authorization_id,
                    environment_binding_id,
                ),
            ).fetchall()
            workspace_rows = connection.execute(
                """SELECT * FROM mandate_workspace_records
                   WHERE principal_id = ? AND tenant_id = ?
                     AND workspace_id = ? AND mandate_id = ?""",
                (principal_id, tenant_id, workspace_id, mandate_id),
            ).fetchall()
        except sqlite3.Error:
            raise SituationalTrustDenied(
                "observation authorization persistence is unavailable"
            ) from None
        finally:
            connection.close()
        if len(authorization_rows) != 1 or len(workspace_rows) != 1:
            raise SituationalTrustDenied(
                "verified observation authorization is unavailable"
            )
        authorization_row = authorization_rows[0]
        workspace_row = workspace_rows[0]
        try:
            receipt = MandateObservationAuthorizationReceipt.model_validate_json(
                str(authorization_row["receipt_json"])
            )
            workspace_record = MandateWorkspaceRecord.model_validate_json(
                str(workspace_row["record_json"])
            )
            command = MandateObservationAuthorizationCommand(
                authorization_id=receipt.authorization_id,
                environment_binding_id=receipt.environment_binding.environment_binding_id,
                environment_binding_class=receipt.environment_binding_class,
                binding_version=receipt.environment_binding.version,
                requested_capabilities=receipt.observation_capabilities,
                wake_budget_per_window=receipt.wake_budget_per_window,
                query_budget_per_window=receipt.query_budget_per_window,
                relevance_assessor=receipt.relevance_assessor,
                relevance_context=receipt.relevance_context,
            )
        except Exception:
            raise SituationalTrustDenied(
                "observation authorization persistence is invalid"
            ) from None
        if (
            content_digest(command) != str(authorization_row["command_digest"])
            or receipt.authorization_receipt_digest
            != str(authorization_row["receipt_digest"])
            or receipt.authorization_receipt_digest
            != mandate.observation_authorization_receipt_digest
            or receipt.authorization_id != str(authorization_row["authorization_id"])
            or receipt.environment_binding.environment_binding_id
            != str(authorization_row["environment_binding_id"])
            or receipt.authorized_by != str(authorization_row["principal_id"])
            or receipt.mandate_id != mandate_id
            or receipt.tenant_id != tenant_id
            or receipt.workspace_id != workspace_id
            or receipt.owner_principal_id != principal_id
            or receipt.workspace_record_digest != mandate.workspace_record_digest
            or receipt.workspace_record_digest != str(workspace_row["record_digest"])
            or content_digest(workspace_record) != str(workspace_row["record_digest"])
            or workspace_record.source_command_digest
            != str(workspace_row["command_digest"])
            or workspace_record.mandate.principal_id != principal_id
            or workspace_record.mandate.tenant_id != tenant_id
            or workspace_record.mandate.workspace_id != workspace_id
            or content_digest(workspace_record.mandate) != mandate.mandate_digest
            or receipt.mandate_digest != mandate.mandate_digest
            or receipt.environment_binding != binding
            or receipt.source_descriptor_digest != source_descriptor_digest
            or binding.binding_digest != source_descriptor_digest
            or receipt.relevance_assessor != relevance_assessor
            or mandate.relevance_assessor != relevance_assessor
            or receipt.relevance_context != relevance_context
            or mandate.relevance_context != relevance_context
            or receipt.correction_epoch != mandate.correction_epoch
            or receipt.expires_at != mandate.expires_at
        ):
            raise SituationalTrustDenied(
                "observation authorization binding is invalid"
            )
        return mandate, binding

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
            current = self._read_mandate(
                connection,
                mandate.mandate_id,
                principal_id=mandate.owner_principal_id,
                tenant_id=mandate.tenant_id,
                workspace_id=mandate.workspace_id,
            )
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
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                  AND (assessment_id = ? OR source_binding_digest = ?
                       OR input_binding_digest = ?)
                """,
                (
                    principal_id,
                    assessment.tenant_id,
                    assessment.workspace_id,
                    assessment.assessment_id,
                    source_binding_digest,
                    assessment.input_binding_digest,
                ),
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
                    input_binding_digest, principal_id, tenant_id, workspace_id,
                    record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.assessment_id,
                    record.assessment_record_id,
                    record.source_binding_digest,
                    record.assessment.input_binding_digest,
                    principal_id,
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
            rows = connection.execute(
                """
                SELECT * FROM situated_assessment_records
                WHERE assessment_id = ?
                """,
                (assessment_id,),
            ).fetchall()
        finally:
            connection.close()
        if len(rows) > 1:
            raise SituationalPersistenceConflict(
                "assessment id is ambiguous across durable scopes"
            )
        return self._decode_and_validate_record(rows[0]) if rows else None

    def record_by_source_binding(
        self, source_binding_digest: str
    ) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM situated_assessment_records
                WHERE source_binding_digest = ?
                """,
                (source_binding_digest,),
            ).fetchall()
        finally:
            connection.close()
        if len(rows) > 1:
            raise SituationalPersistenceConflict(
                "source binding is ambiguous across durable scopes"
            )
        return self._decode_and_validate_record(rows[0]) if rows else None

    def record_by_input_binding(
        self, input_binding_digest: str
    ) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM situated_assessment_records WHERE input_binding_digest = ?",
                (input_binding_digest,),
            ).fetchall()
        finally:
            connection.close()
        matches = tuple(self._decode_and_validate_record(row) for row in rows)
        if len(matches) > 1:
            raise SituationalPersistenceConflict(
                "input binding maps to multiple durable assessment records"
            )
        return matches[0] if matches else None

    def record_by_result_digest(
        self, result_digest: str
    ) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM situated_assessment_records"
            ).fetchall()
        finally:
            connection.close()
        matches = tuple(
            record
            for record in (self._decode_and_validate_record(row) for row in rows)
            if content_digest(record) == result_digest
        )
        if len(matches) > 1:
            raise SituationalPersistenceConflict(
                "result digest maps to multiple durable assessment records"
            )
        return matches[0] if matches else None

    @classmethod
    def _decode_and_validate_record(
        cls, row: sqlite3.Row
    ) -> SituatedAssessmentRecord:
        record = cls._decode_record(str(row["record_json"]))
        if (
            str(row["assessment_id"]) != record.assessment.assessment_id
            or str(row["assessment_record_id"]) != record.assessment_record_id
            or str(row["source_binding_digest"]) != record.source_binding_digest
            or str(row["input_binding_digest"])
            != record.assessment.input_binding_digest
            or str(row["tenant_id"]) != record.tenant_id
            or str(row["workspace_id"]) != record.workspace_id
            or record.assessment.tenant_id != record.tenant_id
            or record.assessment.workspace_id != record.workspace_id
        ):
            raise SituationalPersistenceConflict(
                "durable situated assessment indexes conflict with canonical bytes"
            )
        return record

    def _record_by_input_binding_scoped(
        self,
        input_binding_digest: str,
        *,
        scope: LedgerAccessScope,
    ) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM situated_assessment_records
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                  AND input_binding_digest = ?
                """,
                (
                    scope.principal_id,
                    scope.tenant_id,
                    scope.workspace_id,
                    input_binding_digest,
                ),
            ).fetchall()
        finally:
            connection.close()
        if len(rows) > 1:
            raise SituationalPersistenceConflict(
                "input binding maps to multiple scoped assessment records"
            )
        if not rows:
            return None
        row = rows[0]
        record = self._decode_and_validate_record(row)
        mandate, _ = self.resolve_active(
            record.assessment.mandate_id,
            record.assessment.environment_binding_id,
            principal_id=scope.principal_id,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            evaluated_at=record.assessment.assessed_at,
        )
        if str(row["principal_id"]) != mandate.owner_principal_id:
            raise SituationalPersistenceConflict(
                "durable situated assessment principal conflicts with authority"
            )
        return record

    def _record_by_result_digest_scoped(
        self,
        result_digest: str,
        *,
        scope: LedgerAccessScope,
    ) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM situated_assessment_records
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                """,
                (scope.principal_id, scope.tenant_id, scope.workspace_id),
            ).fetchall()
        finally:
            connection.close()
        matches = tuple(
            record
            for record in (self._decode_and_validate_record(row) for row in rows)
            if content_digest(record) == result_digest
        )
        if len(matches) > 1:
            raise SituationalPersistenceConflict(
                "scoped result digest maps to multiple durable assessment records"
            )
        return matches[0] if matches else None

    def scoped_reader(
        self, scope: LedgerAccessScope
    ) -> ScopedSituatedAssessmentReader:
        return scoped_situated_assessment_reader(self, scope)

    def replay_if_active(
        self,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        input_binding_digest: str,
        *,
        principal_id: str,
        evaluated_at: datetime,
    ) -> SituatedAssessmentRecord | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._read_mandate(
                connection,
                mandate.mandate_id,
                principal_id=mandate.owner_principal_id,
                tenant_id=mandate.tenant_id,
                workspace_id=mandate.workspace_id,
            )
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
                    "mandate or environment binding epoch changed before replay"
                )
            row = connection.execute(
                """
                SELECT record_json FROM situated_assessment_records
                WHERE assessment_id = ?
                """,
                (f"relevance-assessment:{input_binding_digest}",),
            ).fetchone()
            record = (
                self._decode_record(str(row["record_json"]))
                if row is not None
                else None
            )
            if record is not None and (
                record.assessment.input_binding_digest != input_binding_digest
                or record.tenant_id != mandate.tenant_id
                or record.workspace_id != mandate.workspace_id
            ):
                raise SituationalPersistenceConflict(
                    "durable replay record does not match guarded input binding"
                )
            connection.commit()
            return record
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def assessment(self, assessment_id: str) -> RelevanceAssessment | None:
        record = self.assessment_record(assessment_id)
        return record.assessment if record is not None else None

    def pause(
        self,
        mandate_id: str,
        *,
        expected_epoch: int,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> RatifiedMandateRef:
        return self._change_status(
            mandate_id,
            expected_epoch=expected_epoch,
            status=MandateOperationalStatus.PAUSED,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def revoke(
        self,
        mandate_id: str,
        *,
        expected_epoch: int,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> RatifiedMandateRef:
        return self._change_status(
            mandate_id,
            expected_epoch=expected_epoch,
            status=MandateOperationalStatus.REVOKED,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

    def _change_status(
        self,
        mandate_id: str,
        *,
        expected_epoch: int,
        status: MandateOperationalStatus,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> RatifiedMandateRef:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = self._read_mandate(
                connection,
                mandate_id,
                principal_id=principal_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
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
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                  AND mandate_id = ? AND correction_epoch = ?
                """,
                (
                    updated.status.value,
                    updated.correction_epoch,
                    canonical_json(updated),
                    current.owner_principal_id,
                    current.tenant_id,
                    current.workspace_id,
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
