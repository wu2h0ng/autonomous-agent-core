from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock

from agent_os_contracts import (
    CreateMandateCommand,
    EnvironmentBindingAuthorization,
    MandateObservationAuthorizationCommand,
    MandateObservationAuthorizationReceipt,
    MandateOperationalStatus,
    Mandate,
    MandateRatificationReceipt,
    MandateStatus,
    MandateWorkspaceRecord,
    ObservationBindingDescriptor,
    PrincipalIdentity,
    PrincipalRole,
    RatifiedMandateRef,
    StandingMission,
    canonical_json,
    content_digest,
)


class MandateWorkspaceNotFound(LookupError):
    pass


class MandateWorkspaceConflict(RuntimeError):
    pass


class MandateWorkspacePersistenceConflict(RuntimeError):
    pass


class MandateObservationAuthorizationDenied(PermissionError):
    pass


class MandateObservationAuthorizationConflict(RuntimeError):
    pass


class MandateObservationAuthorizationPersistenceConflict(RuntimeError):
    pass


class SQLiteMandateWorkspaceStore:
    """Durable, scope-bound Mandate records without execution authority."""

    def __init__(self, database: str | Path, *, uri: bool = False) -> None:
        self._database = str(database)
        self._uri = uri
        self._db = sqlite3.connect(
            self._database,
            check_same_thread=False,
            uri=self._uri,
        )
        self._db.row_factory = sqlite3.Row
        self._lock = RLock()
        try:
            with self._lock:
                self._db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mandate_workspace_records (
                        principal_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        mandate_id TEXT NOT NULL,
                        command_digest TEXT NOT NULL,
                        record_digest TEXT NOT NULL,
                        record_json TEXT NOT NULL,
                        PRIMARY KEY (principal_id, tenant_id, workspace_id, mandate_id)
                    )
                    """
                )
                self._validate_schema()
                self._db.commit()
        except Exception:
            self._db.close()
            raise

    def _validate_schema(self) -> None:
        expected = (
            ("principal_id", "TEXT", 1, 1),
            ("tenant_id", "TEXT", 1, 2),
            ("workspace_id", "TEXT", 1, 3),
            ("mandate_id", "TEXT", 1, 4),
            ("command_digest", "TEXT", 1, 0),
            ("record_digest", "TEXT", 1, 0),
            ("record_json", "TEXT", 1, 0),
        )
        try:
            actual = tuple(
                (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
                for row in self._db.execute(
                    "PRAGMA table_info(mandate_workspace_records)"
                ).fetchall()
            )
        except sqlite3.Error:
            raise MandateWorkspacePersistenceConflict(
                "existing Mandate Workspace schema is invalid"
            ) from None
        if actual != expected:
            raise MandateWorkspacePersistenceConflict(
                "existing Mandate Workspace schema is invalid"
            )

    @staticmethod
    def _build_record(
        command: CreateMandateCommand,
        principal: PrincipalIdentity,
        now: datetime,
    ) -> MandateWorkspaceRecord:
        mandate = Mandate(
            mandate_id=command.mandate_id,
            tenant_id=principal.tenant_id,
            workspace_id=principal.workspace_id,
            principal_id=principal.principal_id,
            status=MandateStatus.RATIFIED,
            mission_statement=command.mission_statement,
            desired_outcomes=command.desired_outcomes,
            permanent_constraints=command.permanent_constraints,
            authority_envelope=command.authority_envelope,
            environment_binding_classes=command.environment_binding_classes,
            time_horizon=command.time_horizon,
            review_cadence_seconds=command.review_cadence_seconds,
            expires_at=command.expires_at,
            correction_epoch=0,
            revocation_conditions=command.revocation_conditions,
            created_at=now,
            ratified_at=now,
        )
        mandate_digest = content_digest(mandate)
        receipt = MandateRatificationReceipt(
            receipt_id=f"mandate-ratification:{mandate_digest}",
            mandate_id=mandate.mandate_id,
            mandate_digest=mandate_digest,
            principal_attestation=command.principal_attestation,
            agent_instance_ref_id=command.agent_instance_ref_id,
            initial_correction_epoch=0,
            ratified_at=now,
        )
        mission = StandingMission(
            standing_mission_id=f"standing-mission:{mandate_digest}",
            mandate_id=mandate.mandate_id,
            tenant_id=mandate.tenant_id,
            workspace_id=mandate.workspace_id,
            statement=mandate.mission_statement,
            outcome_criteria_refs=command.outcome_criteria_refs,
            review_cadence_seconds=mandate.review_cadence_seconds,
            projected_at=now,
            expires_at=mandate.expires_at,
            parent_mandate_digest=mandate_digest,
            correction_epoch=mandate.correction_epoch,
            ratification_receipt_digest=content_digest(receipt),
        )
        return MandateWorkspaceRecord(
            source_command_digest=content_digest(command),
            mandate=mandate,
            ratification_receipt=receipt,
            standing_mission=mission,
        )

    @staticmethod
    def _decode_record(
        payload: str,
        expected_command_digest: str,
        expected_digest: str,
        principal: PrincipalIdentity,
        mandate_id: str,
    ) -> MandateWorkspaceRecord:
        try:
            record = MandateWorkspaceRecord.model_validate_json(payload)
        except Exception:
            raise MandateWorkspacePersistenceConflict(
                "durable Mandate Workspace record is invalid"
            ) from None
        mandate = record.mandate
        receipt = record.ratification_receipt
        mission = record.standing_mission
        reconstructed_command = CreateMandateCommand(
            mandate_id=mandate.mandate_id,
            mission_statement=mandate.mission_statement,
            desired_outcomes=mandate.desired_outcomes,
            permanent_constraints=mandate.permanent_constraints,
            authority_envelope=mandate.authority_envelope,
            environment_binding_classes=mandate.environment_binding_classes,
            time_horizon=mandate.time_horizon,
            review_cadence_seconds=mandate.review_cadence_seconds,
            expires_at=mandate.expires_at,
            revocation_conditions=mandate.revocation_conditions,
            agent_instance_ref_id=receipt.agent_instance_ref_id,
            outcome_criteria_refs=mission.outcome_criteria_refs,
            principal_attestation=receipt.principal_attestation,
        )
        if (
            content_digest(record) != expected_digest
            or record.source_command_digest != expected_command_digest
            or content_digest(reconstructed_command) != expected_command_digest
            or mandate.mandate_id != mandate_id
            or mandate.status is not MandateStatus.RATIFIED
            or mandate.principal_id != principal.principal_id
            or mandate.tenant_id != principal.tenant_id
            or mandate.workspace_id != principal.workspace_id
            or receipt.mandate_id != mandate_id
            or receipt.mandate_digest != content_digest(mandate)
            or receipt.initial_correction_epoch != mandate.correction_epoch
            or receipt.ratified_at != mandate.ratified_at
            or mission.mandate_id != mandate_id
            or mission.tenant_id != principal.tenant_id
            or mission.workspace_id != principal.workspace_id
            or mission.parent_mandate_digest != content_digest(mandate)
            or mission.correction_epoch != mandate.correction_epoch
            or mission.ratification_receipt_digest != content_digest(receipt)
            or mission.statement != mandate.mission_statement
            or mission.review_cadence_seconds != mandate.review_cadence_seconds
            or mission.expires_at != mandate.expires_at
        ):
            raise MandateWorkspacePersistenceConflict(
                "durable Mandate Workspace authority binding is invalid"
            )
        return record

    def create(
        self,
        command: CreateMandateCommand,
        principal: PrincipalIdentity,
        now: datetime,
    ) -> MandateWorkspaceRecord:
        if command.expires_at <= now:
            raise ValueError("expired Mandate cannot be ratified")
        command_digest = content_digest(command)
        record = self._build_record(command, principal, now)
        record_json = canonical_json(record)
        record_digest = content_digest(record)
        with self._lock:
            row = self._db.execute(
                """
                SELECT command_digest, record_digest, record_json
                FROM mandate_workspace_records
                WHERE principal_id = ? AND tenant_id = ?
                  AND workspace_id = ? AND mandate_id = ?
                """,
                (
                    principal.principal_id,
                    principal.tenant_id,
                    principal.workspace_id,
                    command.mandate_id,
                ),
            ).fetchone()
            if row is not None:
                if str(row["command_digest"]) != command_digest:
                    raise MandateWorkspaceConflict(
                        "Mandate id is already bound to a different command"
                    )
                return self._decode_record(
                    str(row["record_json"]),
                    str(row["command_digest"]),
                    str(row["record_digest"]),
                    principal,
                    command.mandate_id,
                )
            self._db.execute(
                """
                INSERT INTO mandate_workspace_records (
                    principal_id, tenant_id, workspace_id, mandate_id,
                    command_digest, record_digest, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    principal.principal_id,
                    principal.tenant_id,
                    principal.workspace_id,
                    command.mandate_id,
                    command_digest,
                    record_digest,
                    record_json,
                ),
            )
            self._db.commit()
        return record

    def get(
        self,
        mandate_id: str,
        principal: PrincipalIdentity,
    ) -> MandateWorkspaceRecord:
        with self._lock:
            row = self._db.execute(
                """
                SELECT command_digest, record_digest, record_json
                FROM mandate_workspace_records
                WHERE principal_id = ? AND tenant_id = ?
                  AND workspace_id = ? AND mandate_id = ?
                """,
                (
                    principal.principal_id,
                    principal.tenant_id,
                    principal.workspace_id,
                    mandate_id,
                ),
            ).fetchone()
        if row is None:
            raise MandateWorkspaceNotFound(mandate_id)
        return self._decode_record(
            str(row["record_json"]),
            str(row["command_digest"]),
            str(row["record_digest"]),
            principal,
            mandate_id,
        )

    def list(self, principal: PrincipalIdentity) -> tuple[MandateWorkspaceRecord, ...]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT mandate_id, command_digest, record_digest, record_json
                FROM mandate_workspace_records
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                ORDER BY mandate_id
                """,
                (
                    principal.principal_id,
                    principal.tenant_id,
                    principal.workspace_id,
                ),
            ).fetchall()
        return tuple(
            self._decode_record(
                str(row["record_json"]),
                str(row["command_digest"]),
                str(row["record_digest"]),
                principal,
                str(row["mandate_id"]),
            )
            for row in rows
        )

    def get_for_authorization(
        self,
        mandate_id: str,
        authorizer: PrincipalIdentity,
    ) -> MandateWorkspaceRecord:
        """Resolve an owner record for an independent same-scope tenant admin."""

        with self._lock:
            rows = self._db.execute(
                """
                SELECT principal_id, command_digest, record_digest, record_json
                FROM mandate_workspace_records
                WHERE tenant_id = ? AND workspace_id = ? AND mandate_id = ?
                """,
                (authorizer.tenant_id, authorizer.workspace_id, mandate_id),
            ).fetchall()
        if len(rows) != 1:
            raise MandateObservationAuthorizationDenied(
                "ratified Mandate Workspace record is unavailable"
            )
        row = rows[0]
        owner = PrincipalIdentity(
            principal_id=str(row["principal_id"]),
            tenant_id=authorizer.tenant_id,
            workspace_id=authorizer.workspace_id,
            role=PrincipalRole.PRINCIPAL,
            authenticated_at=authorizer.authenticated_at,
        )
        try:
            return self._decode_record(
                str(row["record_json"]),
                str(row["command_digest"]),
                str(row["record_digest"]),
                owner,
                mandate_id,
            )
        except MandateWorkspacePersistenceConflict:
            raise MandateObservationAuthorizationPersistenceConflict(
                "ratified Mandate Workspace record is invalid"
            ) from None


class SQLiteMandateObservationAuthorizationStore:
    """Atomic bridge from durable Mandate Workspace truth into situated authority."""

    def __init__(
        self,
        database: str | Path,
        *,
        mandate_workspace: SQLiteMandateWorkspaceStore,
        descriptors: tuple[ObservationBindingDescriptor, ...] = (),
    ) -> None:
        self._database = str(database)
        if self._database == ":memory:":
            raise ValueError("Mandate observation authorization requires durable SQLite")
        self._mandate_workspace = mandate_workspace
        indexed = {item.environment_binding_id: item for item in descriptors}
        if len(indexed) != len(descriptors):
            raise ValueError("observation binding descriptor ids must be unique")
        self._descriptors = indexed
        # Reuse the canonical situated store schema; this creates no second runtime.
        from .situated_persistence import SQLiteSituatedAssessmentStore

        SQLiteSituatedAssessmentStore(self._database)
        self._initialize()

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
                CREATE TABLE IF NOT EXISTS mandate_observation_authorizations (
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    mandate_id TEXT NOT NULL,
                    authorization_id TEXT NOT NULL,
                    environment_binding_id TEXT NOT NULL,
                    command_digest TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY (
                        principal_id, tenant_id, workspace_id, authorization_id
                    ),
                    UNIQUE (
                        tenant_id, workspace_id, mandate_id,
                        environment_binding_id
                    )
                )
                """
            )
            expected = (
                ("principal_id", "TEXT", 1, 1),
                ("tenant_id", "TEXT", 1, 2),
                ("workspace_id", "TEXT", 1, 3),
                ("mandate_id", "TEXT", 1, 0),
                ("authorization_id", "TEXT", 1, 4),
                ("environment_binding_id", "TEXT", 1, 0),
                ("command_digest", "TEXT", 1, 0),
                ("receipt_digest", "TEXT", 1, 0),
                ("receipt_json", "TEXT", 1, 0),
            )
            actual = tuple(
                (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
                for row in connection.execute(
                    "PRAGMA table_info(mandate_observation_authorizations)"
                ).fetchall()
            )
            if actual != expected:
                raise MandateObservationAuthorizationPersistenceConflict(
                    "existing observation authorization schema is invalid"
                )
            unique_columns = {
                tuple(
                    str(item[2])
                    for item in connection.execute(
                        f"PRAGMA index_info('{str(index[1])}')"
                    ).fetchall()
                )
                for index in connection.execute(
                    "PRAGMA index_list(mandate_observation_authorizations)"
                ).fetchall()
                if int(index[2]) == 1
            }
            if unique_columns != {
                (
                    "principal_id",
                    "tenant_id",
                    "workspace_id",
                    "authorization_id",
                ),
                (
                    "tenant_id",
                    "workspace_id",
                    "mandate_id",
                    "environment_binding_id",
                ),
            }:
                raise MandateObservationAuthorizationPersistenceConflict(
                    "existing observation authorization schema is invalid"
                )
            connection.commit()
        except sqlite3.Error:
            raise MandateObservationAuthorizationPersistenceConflict(
                "observation authorization persistence is unavailable"
            ) from None
        finally:
            connection.close()

    @staticmethod
    def _project(
        record: MandateWorkspaceRecord,
        command: MandateObservationAuthorizationCommand,
        descriptor: ObservationBindingDescriptor,
        authorizer: PrincipalIdentity,
        now: datetime,
    ) -> tuple[RatifiedMandateRef, MandateObservationAuthorizationReceipt]:
        mandate = record.mandate
        binding = EnvironmentBindingAuthorization(
            environment_binding_id=descriptor.environment_binding_id,
            version=descriptor.version,
            binding_digest=descriptor.source_descriptor_digest,
        )
        receipt = MandateObservationAuthorizationReceipt.create(
            authorization_id=command.authorization_id,
            mandate_id=mandate.mandate_id,
            mandate_version=mandate.correction_epoch + 1,
            mandate_digest=content_digest(mandate),
            workspace_record_digest=content_digest(record),
            ratification_receipt_id=record.ratification_receipt.receipt_id,
            ratification_receipt_digest=content_digest(record.ratification_receipt),
            owner_principal_id=mandate.principal_id,
            authorized_by=authorizer.principal_id,
            tenant_id=mandate.tenant_id,
            workspace_id=mandate.workspace_id,
            correction_epoch=mandate.correction_epoch,
            authorized_at=now,
            expires_at=mandate.expires_at,
            environment_binding_class=descriptor.environment_binding_class,
            source_descriptor_digest=descriptor.source_descriptor_digest,
            environment_binding=binding,
            observation_capabilities=descriptor.observation_capabilities,
            wake_budget_per_window=command.wake_budget_per_window,
            query_budget_per_window=command.query_budget_per_window,
            relevance_assessor=descriptor.relevance_assessor,
            relevance_context=descriptor.relevance_context,
            task_activation_authorized=False,
            capability_grant_authorized=False,
            external_effects_authorized=False,
        )
        projected = RatifiedMandateRef(
            mandate_id=mandate.mandate_id,
            version=mandate.correction_epoch + 1,
            mandate_digest=content_digest(mandate),
            ratification_receipt_id=record.ratification_receipt.receipt_id,
            tenant_id=mandate.tenant_id,
            workspace_id=mandate.workspace_id,
            owner_principal_id=mandate.principal_id,
            ratified_by=mandate.principal_id,
            ratified_at=record.ratification_receipt.ratified_at,
            valid_from=now,
            expires_at=mandate.expires_at,
            correction_epoch=mandate.correction_epoch,
            status=MandateOperationalStatus.ACTIVE,
            authority_envelope_digest=content_digest(mandate.authority_envelope),
            allowed_environment_bindings=(binding,),
            relevance_assessor=descriptor.relevance_assessor,
            relevance_context=descriptor.relevance_context,
            observation_authorization_id=command.authorization_id,
            observation_authorization_receipt_digest=(
                receipt.authorization_receipt_digest
            ),
            workspace_record_digest=receipt.workspace_record_digest,
        )
        return projected, receipt

    def _validate_request(
        self,
        record: MandateWorkspaceRecord,
        command: MandateObservationAuthorizationCommand,
        authorizer: PrincipalIdentity,
        now: datetime,
    ) -> ObservationBindingDescriptor:
        mandate = record.mandate
        descriptor = self._descriptors.get(command.environment_binding_id)
        if (
            authorizer.role is not PrincipalRole.TENANT_ADMIN
            or authorizer.principal_id == mandate.principal_id
            or authorizer.tenant_id != mandate.tenant_id
            or authorizer.workspace_id != mandate.workspace_id
            or authorizer.authenticated_at > now
            or mandate.status is not MandateStatus.RATIFIED
            or mandate.expires_at <= now
            or descriptor is None
            or descriptor.environment_binding_class
            not in mandate.environment_binding_classes
            or command.environment_binding_class
            != descriptor.environment_binding_class
            or command.binding_version != descriptor.version
            or command.requested_capabilities
            != descriptor.observation_capabilities
            or descriptor.observation_capabilities != ("observation.read",)
            or command.wake_budget_per_window
            != descriptor.max_wake_budget_per_window
            or command.query_budget_per_window
            != descriptor.max_query_budget_per_window
            or command.wake_budget_per_window
            > mandate.authority_envelope.wake_budget_per_window
            or command.query_budget_per_window
            > mandate.authority_envelope.query_budget_per_window
            or command.relevance_assessor != descriptor.relevance_assessor
            or command.relevance_context != descriptor.relevance_context
        ):
            raise MandateObservationAuthorizationDenied(
                "Mandate observation authorization is not allowed"
            )
        return descriptor

    @staticmethod
    def _decode_receipt(row: sqlite3.Row) -> MandateObservationAuthorizationReceipt:
        try:
            receipt = MandateObservationAuthorizationReceipt.model_validate_json(
                str(row["receipt_json"])
            )
        except Exception:
            raise MandateObservationAuthorizationPersistenceConflict(
                "durable observation authorization receipt is invalid"
            ) from None
        reconstructed_command = MandateObservationAuthorizationCommand(
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
        if (
            receipt.authorization_receipt_digest != str(row["receipt_digest"])
            or content_digest(reconstructed_command) != str(row["command_digest"])
            or receipt.authorization_id != str(row["authorization_id"])
            or receipt.mandate_id != str(row["mandate_id"])
            or receipt.environment_binding.environment_binding_id
            != str(row["environment_binding_id"])
            or receipt.authorized_by != str(row["principal_id"])
            or receipt.tenant_id != str(row["tenant_id"])
            or receipt.workspace_id != str(row["workspace_id"])
            or receipt.environment_binding.binding_digest
            != receipt.source_descriptor_digest
        ):
            raise MandateObservationAuthorizationPersistenceConflict(
                "durable observation authorization index is invalid"
            )
        return receipt

    def authorize(
        self,
        mandate_id: str,
        command: MandateObservationAuthorizationCommand,
        authorizer: PrincipalIdentity,
        now: datetime,
    ) -> MandateObservationAuthorizationReceipt:
        record = self._mandate_workspace.get_for_authorization(mandate_id, authorizer)
        command_digest = content_digest(command)
        preflight = self._connect()
        try:
            existing_rows = preflight.execute(
                """
                SELECT * FROM mandate_observation_authorizations
                WHERE tenant_id = ? AND workspace_id = ?
                  AND (authorization_id = ? OR
                       (mandate_id = ? AND environment_binding_id = ?))
                """,
                (
                    authorizer.tenant_id,
                    authorizer.workspace_id,
                    command.authorization_id,
                    mandate_id,
                    command.environment_binding_id,
                ),
            ).fetchall()
        finally:
            preflight.close()
        if existing_rows:
            if len(existing_rows) != 1:
                raise MandateObservationAuthorizationPersistenceConflict(
                    "durable observation authorization index is ambiguous"
                )
            row = existing_rows[0]
            if (
                str(row["principal_id"]) != authorizer.principal_id
                or str(row["command_digest"]) != command_digest
            ):
                raise MandateObservationAuthorizationConflict(
                    "observation authorization identity conflicts"
                )
        descriptor = self._validate_request(record, command, authorizer, now)
        if existing_rows:
            row = existing_rows[0]
            replay = self._decode_receipt(row)
            projected, expected_receipt = self._project(
                record, command, descriptor, authorizer, replay.authorized_at
            )
            check = self._connect()
            try:
                situated = check.execute(
                    """SELECT mandate_json FROM situated_mandates
                       WHERE principal_id = ? AND tenant_id = ?
                         AND workspace_id = ? AND mandate_id = ?""",
                    (
                        record.mandate.principal_id,
                        record.mandate.tenant_id,
                        record.mandate.workspace_id,
                        mandate_id,
                    ),
                ).fetchone()
            finally:
                check.close()
            try:
                current = RatifiedMandateRef.model_validate_json(
                    str(situated["mandate_json"]) if situated is not None else ""
                )
            except Exception:
                raise MandateObservationAuthorizationPersistenceConflict(
                    "durable situated authority is invalid"
                ) from None
            if replay != expected_receipt:
                raise MandateObservationAuthorizationPersistenceConflict(
                    "durable observation authorization projection is invalid"
                )
            if current != projected:
                raise MandateObservationAuthorizationDenied(
                    "Mandate observation authority has changed"
                )
            return replay
        projected, receipt = self._project(
            record, command, descriptor, authorizer, now
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workspace_row = connection.execute(
                """
                SELECT command_digest, record_digest FROM mandate_workspace_records
                WHERE principal_id = ? AND tenant_id = ?
                  AND workspace_id = ? AND mandate_id = ?
                """,
                (
                    record.mandate.principal_id,
                    record.mandate.tenant_id,
                    record.mandate.workspace_id,
                    mandate_id,
                ),
            ).fetchone()
            if (
                workspace_row is None
                or str(workspace_row["command_digest"])
                != record.source_command_digest
                or str(workspace_row["record_digest"]) != content_digest(record)
            ):
                raise MandateObservationAuthorizationPersistenceConflict(
                    "ratified Mandate Workspace record changed during authorization"
                )
            situated = connection.execute(
                """SELECT mandate_json FROM situated_mandates
                   WHERE principal_id = ? AND tenant_id = ?
                     AND workspace_id = ? AND mandate_id = ?""",
                (
                    record.mandate.principal_id,
                    record.mandate.tenant_id,
                    record.mandate.workspace_id,
                    mandate_id,
                ),
            ).fetchone()
            if situated is not None:
                try:
                    current = RatifiedMandateRef.model_validate_json(
                        str(situated["mandate_json"])
                    )
                except Exception:
                    raise MandateObservationAuthorizationPersistenceConflict(
                        "durable situated authority is invalid"
                    ) from None
                if current != projected:
                    raise MandateObservationAuthorizationDenied(
                        "Mandate observation authority has changed"
                    )
            existing = connection.execute(
                """
                SELECT * FROM mandate_observation_authorizations
                WHERE tenant_id = ? AND workspace_id = ?
                  AND (authorization_id = ? OR
                       (mandate_id = ? AND environment_binding_id = ?))
                """,
                (
                    authorizer.tenant_id,
                    authorizer.workspace_id,
                    command.authorization_id,
                    mandate_id,
                    command.environment_binding_id,
                ),
            ).fetchall()
            if existing:
                if len(existing) != 1:
                    raise MandateObservationAuthorizationPersistenceConflict(
                        "durable observation authorization index is ambiguous"
                    )
                replay = self._decode_receipt(existing[0])
                if (
                    str(existing[0]["command_digest"]) != command_digest
                    or replay != receipt
                ):
                    raise MandateObservationAuthorizationConflict(
                        "observation authorization identity conflicts"
                    )
                connection.rollback()
                return replay
            if situated is None:
                connection.execute(
                    """
                    INSERT INTO situated_mandates (
                        principal_id, tenant_id, workspace_id,
                        mandate_id, mandate_version, mandate_digest,
                        status, correction_epoch, mandate_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        projected.owner_principal_id,
                        projected.tenant_id,
                        projected.workspace_id,
                        projected.mandate_id,
                        projected.version,
                        projected.mandate_digest,
                        projected.status.value,
                        projected.correction_epoch,
                        canonical_json(projected),
                    ),
                )
            connection.execute(
                """
                INSERT INTO mandate_observation_authorizations (
                    principal_id, tenant_id, workspace_id, mandate_id,
                    authorization_id, environment_binding_id, command_digest,
                    receipt_digest, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    authorizer.principal_id,
                    authorizer.tenant_id,
                    authorizer.workspace_id,
                    mandate_id,
                    command.authorization_id,
                    command.environment_binding_id,
                    command_digest,
                    receipt.authorization_receipt_digest,
                    canonical_json(receipt),
                ),
            )
            connection.commit()
            return receipt
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list(
        self,
        mandate_id: str,
        authorizer: PrincipalIdentity,
    ) -> tuple[MandateObservationAuthorizationReceipt, ...]:
        if authorizer.role is not PrincipalRole.TENANT_ADMIN:
            raise MandateObservationAuthorizationDenied(
                "Mandate observation authorization is not allowed"
            )
        # Revalidates the current owner record and its exact durable digest.
        record = self._mandate_workspace.get_for_authorization(mandate_id, authorizer)
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM mandate_observation_authorizations
                WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ?
                  AND mandate_id = ? ORDER BY authorization_id
                """,
                (
                    authorizer.principal_id,
                    authorizer.tenant_id,
                    authorizer.workspace_id,
                    mandate_id,
                ),
            ).fetchall()
            receipts = tuple(self._decode_receipt(row) for row in rows)
            situated = connection.execute(
                """SELECT mandate_json FROM situated_mandates
                   WHERE principal_id = ? AND tenant_id = ?
                     AND workspace_id = ? AND mandate_id = ?""",
                (
                    record.mandate.principal_id,
                    record.mandate.tenant_id,
                    record.mandate.workspace_id,
                    mandate_id,
                ),
            ).fetchone()
        finally:
            connection.close()
        if receipts:
            try:
                current = RatifiedMandateRef.model_validate_json(
                    str(situated["mandate_json"]) if situated is not None else ""
                )
            except Exception:
                raise MandateObservationAuthorizationPersistenceConflict(
                    "durable situated authority is invalid"
                ) from None
            for receipt in receipts:
                descriptor = self._descriptors.get(
                    receipt.environment_binding.environment_binding_id
                )
                if descriptor is None:
                    raise MandateObservationAuthorizationPersistenceConflict(
                        "observation binding descriptor is unavailable"
                    )
                command = MandateObservationAuthorizationCommand(
                    authorization_id=receipt.authorization_id,
                    environment_binding_id=descriptor.environment_binding_id,
                    environment_binding_class=descriptor.environment_binding_class,
                    binding_version=descriptor.version,
                    requested_capabilities=descriptor.observation_capabilities,
                    wake_budget_per_window=receipt.wake_budget_per_window,
                    query_budget_per_window=receipt.query_budget_per_window,
                    relevance_assessor=descriptor.relevance_assessor,
                    relevance_context=descriptor.relevance_context,
                )
                expected, expected_receipt = self._project(
                    record,
                    command,
                    descriptor,
                    authorizer,
                    receipt.authorized_at,
                )
                if receipt != expected_receipt or current != expected:
                    raise MandateObservationAuthorizationPersistenceConflict(
                        "observation authorization projection is invalid"
                    )
        return receipts
