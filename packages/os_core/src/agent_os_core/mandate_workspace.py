from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock

from agent_os_contracts import (
    CreateMandateCommand,
    Mandate,
    MandateRatificationReceipt,
    MandateStatus,
    MandateWorkspaceRecord,
    PrincipalIdentity,
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


class SQLiteMandateWorkspaceStore:
    """Durable, scope-bound Mandate records without execution authority."""

    def __init__(self, database: str | Path) -> None:
        self._db = sqlite3.connect(str(database), check_same_thread=False)
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
