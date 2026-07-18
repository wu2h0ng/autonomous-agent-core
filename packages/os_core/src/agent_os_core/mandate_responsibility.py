from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from agent_os_contracts import (
    Goal,
    MandateOperationalStatus,
    MandateStatus,
    MandateTaskLink,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocation,
    MandateTaskLinkRevocationCommand,
    MandateWorkspaceRecord,
    PrincipalIdentity,
    PrincipalRole,
    RatifiedMandateRef,
    TaskEvent,
    TaskEventType,
    canonical_json,
    content_digest,
)


class MandateResponsibilityDenied(PermissionError):
    pass


class MandateResponsibilityNotFound(LookupError):
    pass


class MandateResponsibilityConflict(RuntimeError):
    pass


class MandateResponsibilityPersistenceConflict(RuntimeError):
    pass


class SQLiteMandateResponsibilityStore:
    """Append-only Mandate/Task association authority without Task mutation."""

    _LINK_TABLE = "mandate_responsibility_links"
    _REVOCATION_TABLE = "mandate_responsibility_revocations"

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = str(Path(database).expanduser().resolve())
        self._clock = clock or (lambda: datetime.now(timezone.utc))
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

    @staticmethod
    def _table_shape(
        connection: sqlite3.Connection, table: str
    ) -> tuple[tuple[str, str, int, int], ...]:
        return tuple(
            (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        )

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._LINK_TABLE} (
                    association_id TEXT NOT NULL,
                    link_id TEXT NOT NULL PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    mandate_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    correction_epoch INTEGER NOT NULL,
                    command_digest TEXT NOT NULL,
                    record_digest TEXT NOT NULL UNIQUE,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_mandate_responsibility_link_scope
                    ON {self._LINK_TABLE}
                    (principal_id, tenant_id, workspace_id, mandate_id, association_id);
                CREATE TABLE IF NOT EXISTS {self._REVOCATION_TABLE} (
                    revocation_id TEXT NOT NULL PRIMARY KEY,
                    association_id TEXT NOT NULL,
                    link_id TEXT NOT NULL UNIQUE,
                    principal_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    mandate_id TEXT NOT NULL,
                    correction_epoch INTEGER NOT NULL,
                    command_digest TEXT NOT NULL,
                    record_digest TEXT NOT NULL UNIQUE,
                    record_json TEXT NOT NULL,
                    FOREIGN KEY (link_id) REFERENCES {self._LINK_TABLE}(link_id)
                );
                """
            )
            link_shape = self._table_shape(connection, self._LINK_TABLE)
            revocation_shape = self._table_shape(connection, self._REVOCATION_TABLE)
            if link_shape != (
                ("association_id", "TEXT", 1, 0),
                ("link_id", "TEXT", 1, 1),
                ("principal_id", "TEXT", 1, 0),
                ("tenant_id", "TEXT", 1, 0),
                ("workspace_id", "TEXT", 1, 0),
                ("mandate_id", "TEXT", 1, 0),
                ("task_id", "TEXT", 1, 0),
                ("correction_epoch", "INTEGER", 1, 0),
                ("command_digest", "TEXT", 1, 0),
                ("record_digest", "TEXT", 1, 0),
                ("record_json", "TEXT", 1, 0),
            ) or revocation_shape != (
                ("revocation_id", "TEXT", 1, 1),
                ("association_id", "TEXT", 1, 0),
                ("link_id", "TEXT", 1, 0),
                ("principal_id", "TEXT", 1, 0),
                ("tenant_id", "TEXT", 1, 0),
                ("workspace_id", "TEXT", 1, 0),
                ("mandate_id", "TEXT", 1, 0),
                ("correction_epoch", "INTEGER", 1, 0),
                ("command_digest", "TEXT", 1, 0),
                ("record_digest", "TEXT", 1, 0),
                ("record_json", "TEXT", 1, 0),
            ):
                raise MandateResponsibilityPersistenceConflict(
                    "existing responsibility store schema is invalid"
                )
        finally:
            connection.close()

    @staticmethod
    def _decode_workspace_row(row: sqlite3.Row) -> MandateWorkspaceRecord:
        try:
            record = MandateWorkspaceRecord.model_validate_json(str(row["record_json"]))
        except Exception:
            raise MandateResponsibilityPersistenceConflict(
                "Mandate Workspace record is malformed"
            ) from None
        mandate = record.mandate
        receipt = record.ratification_receipt
        mission = record.standing_mission
        if (
            content_digest(record) != str(row["record_digest"])
            or record.source_command_digest != str(row["command_digest"])
            or mandate.principal_id != str(row["principal_id"])
            or mandate.tenant_id != str(row["tenant_id"])
            or mandate.workspace_id != str(row["workspace_id"])
            or mandate.mandate_id != str(row["mandate_id"])
            or mandate.status is not MandateStatus.RATIFIED
            or receipt.mandate_id != mandate.mandate_id
            or receipt.mandate_digest != content_digest(mandate)
            or mission.mandate_id != mandate.mandate_id
            or mission.tenant_id != mandate.tenant_id
            or mission.workspace_id != mandate.workspace_id
            or mission.parent_mandate_digest != content_digest(mandate)
            or mission.ratification_receipt_digest != content_digest(receipt)
        ):
            raise MandateResponsibilityPersistenceConflict(
                "Mandate Workspace record binding is invalid"
            )
        return record

    def _read_workspace(
        self,
        connection: sqlite3.Connection,
        mandate_id: str,
        reader: PrincipalIdentity,
    ) -> tuple[MandateWorkspaceRecord, str]:
        if reader.role not in {PrincipalRole.PRINCIPAL, PrincipalRole.TENANT_ADMIN}:
            raise MandateResponsibilityDenied("responsibility read role is not allowed")
        rows = connection.execute(
            "SELECT * FROM mandate_workspace_records "
            "WHERE tenant_id = ? AND workspace_id = ? AND mandate_id = ?",
            (reader.tenant_id, reader.workspace_id, mandate_id),
        ).fetchall()
        if len(rows) != 1:
            exists = connection.execute(
                "SELECT 1 FROM mandate_workspace_records WHERE mandate_id = ? LIMIT 1",
                (mandate_id,),
            ).fetchone()
            if exists is not None:
                raise MandateResponsibilityDenied("Mandate scope is not authorized")
            raise MandateResponsibilityNotFound(mandate_id)
        record = self._decode_workspace_row(rows[0])
        if (
            reader.role is PrincipalRole.PRINCIPAL
            and reader.principal_id != record.mandate.principal_id
        ):
            raise MandateResponsibilityDenied("Mandate owner scope is not authorized")
        return record, str(rows[0]["record_digest"])

    @staticmethod
    def _decode_operational_row(row: sqlite3.Row) -> RatifiedMandateRef:
        try:
            mandate = RatifiedMandateRef.model_validate_json(str(row["mandate_json"]))
        except Exception:
            raise MandateResponsibilityPersistenceConflict(
                "operational Mandate source is malformed"
            ) from None
        if (
            mandate.owner_principal_id != str(row["principal_id"])
            or mandate.tenant_id != str(row["tenant_id"])
            or mandate.workspace_id != str(row["workspace_id"])
            or mandate.mandate_id != str(row["mandate_id"])
            or mandate.version != int(row["mandate_version"])
            or mandate.mandate_digest != str(row["mandate_digest"])
            or mandate.status.value != str(row["status"])
            or mandate.correction_epoch != int(row["correction_epoch"])
        ):
            raise MandateResponsibilityPersistenceConflict(
                "operational Mandate index binding is invalid"
            )
        return mandate

    def _read_authority(
        self,
        connection: sqlite3.Connection,
        mandate_id: str,
        actor: PrincipalIdentity,
        *,
        require_admin: bool,
        require_active: bool,
        now: datetime,
    ) -> tuple[MandateWorkspaceRecord, str, RatifiedMandateRef, str]:
        if require_admin and actor.role is not PrincipalRole.TENANT_ADMIN:
            raise MandateResponsibilityDenied("TENANT_ADMIN role is required")
        workspace, workspace_digest = self._read_workspace(
            connection, mandate_id, actor
        )
        owner = workspace.mandate.principal_id
        row = connection.execute(
            "SELECT * FROM situated_mandates WHERE principal_id = ? "
            "AND tenant_id = ? AND workspace_id = ? AND mandate_id = ?",
            (owner, actor.tenant_id, actor.workspace_id, mandate_id),
        ).fetchone()
        if row is None:
            raise MandateResponsibilityDenied(
                "operational Mandate source is unavailable"
            )
        operational = self._decode_operational_row(row)
        if (
            operational.workspace_record_digest != workspace_digest
            or operational.mandate_digest != content_digest(workspace.mandate)
            or operational.ratification_receipt_id
            != workspace.ratification_receipt.receipt_id
            or operational.owner_principal_id != owner
        ):
            raise MandateResponsibilityPersistenceConflict(
                "Mandate dual-authority join is invalid"
            )
        if require_active and (
            operational.status is not MandateOperationalStatus.ACTIVE
            or now < operational.valid_from
            or now >= operational.expires_at
        ):
            raise MandateResponsibilityDenied(
                "operational Mandate is not active at link time"
            )
        return (
            workspace,
            workspace_digest,
            operational,
            content_digest(operational),
        )

    @staticmethod
    def _read_task_created(
        connection: sqlite3.Connection,
        task_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> tuple[TaskEvent, str]:
        row = connection.execute(
            "SELECT * FROM task_events WHERE task_id = ? AND sequence = 1",
            (task_id,),
        ).fetchone()
        if row is None:
            raise MandateResponsibilityNotFound(f"Task not found: {task_id}")
        try:
            event = TaskEvent.model_validate(dict(row))
            goal = Goal.model_validate(event.decoded_payload()["goal"])
        except Exception:
            raise MandateResponsibilityPersistenceConflict(
                "Task TASK_CREATED identity is malformed"
            ) from None
        if (
            event.event_type is not TaskEventType.TASK_CREATED
            or event.sequence != 1
            or event.task_id != task_id
        ):
            raise MandateResponsibilityPersistenceConflict(
                "Task TASK_CREATED identity is invalid"
            )
        if goal.tenant_id != tenant_id or goal.workspace_id != workspace_id:
            raise MandateResponsibilityDenied("Task scope is not authorized")
        return event, content_digest(event)

    @staticmethod
    def _seal_link(payload: dict[str, object]) -> MandateTaskLink:
        digest = content_digest({"schema_version": "1.0", **payload})
        return MandateTaskLink.model_validate({**payload, "record_digest": digest})

    @staticmethod
    def _decode_link(row: sqlite3.Row) -> MandateTaskLink:
        try:
            link = MandateTaskLink.model_validate_json(str(row["record_json"]))
        except Exception:
            raise MandateResponsibilityPersistenceConflict(
                "durable responsibility link is malformed"
            ) from None
        reconstructed = MandateTaskLinkCommand(task_id=link.task_id, reason=link.reason)
        payload = link.model_dump(mode="json", exclude={"record_digest"})
        if (
            content_digest(payload) != link.record_digest
            or link.command_digest != content_digest(reconstructed)
            or link.association_id != str(row["association_id"])
            or link.link_id != str(row["link_id"])
            or link.principal_id != str(row["principal_id"])
            or link.tenant_id != str(row["tenant_id"])
            or link.workspace_id != str(row["workspace_id"])
            or link.mandate_id != str(row["mandate_id"])
            or link.task_id != str(row["task_id"])
            or link.correction_epoch != int(row["correction_epoch"])
            or link.command_digest != str(row["command_digest"])
            or link.record_digest != str(row["record_digest"])
        ):
            raise MandateResponsibilityPersistenceConflict(
                "durable responsibility link binding is invalid"
            )
        return link

    @staticmethod
    def _seal_revocation(payload: dict[str, object]) -> MandateTaskLinkRevocation:
        digest = content_digest({"schema_version": "1.0", **payload})
        return MandateTaskLinkRevocation.model_validate(
            {**payload, "record_digest": digest}
        )

    @staticmethod
    def _decode_revocation(row: sqlite3.Row) -> MandateTaskLinkRevocation:
        try:
            revocation = MandateTaskLinkRevocation.model_validate_json(
                str(row["record_json"])
            )
        except Exception:
            raise MandateResponsibilityPersistenceConflict(
                "durable responsibility revocation is malformed"
            ) from None
        command = MandateTaskLinkRevocationCommand(
            expected_link_digest=revocation.link_record_digest,
            reason=revocation.reason,
        )
        payload = revocation.model_dump(mode="json", exclude={"record_digest"})
        if (
            content_digest(payload) != revocation.record_digest
            or revocation.command_digest != content_digest(command)
            or revocation.revocation_id != str(row["revocation_id"])
            or revocation.association_id != str(row["association_id"])
            or revocation.link_id != str(row["link_id"])
            or revocation.principal_id != str(row["principal_id"])
            or revocation.tenant_id != str(row["tenant_id"])
            or revocation.workspace_id != str(row["workspace_id"])
            or revocation.mandate_id != str(row["mandate_id"])
            or revocation.correction_epoch != int(row["correction_epoch"])
            or revocation.command_digest != str(row["command_digest"])
            or revocation.record_digest != str(row["record_digest"])
        ):
            raise MandateResponsibilityPersistenceConflict(
                "durable responsibility revocation binding is invalid"
            )
        return revocation

    def create_link(
        self,
        command: MandateTaskLinkCommand,
        mandate_id: str,
        actor: PrincipalIdentity,
    ) -> MandateTaskLink:
        now = self._clock()
        command_digest = content_digest(command)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workspace, workspace_digest, operational, operational_digest = (
                self._read_authority(
                    connection,
                    mandate_id,
                    actor,
                    require_admin=True,
                    require_active=True,
                    now=now,
                )
            )
            _, task_created_digest = self._read_task_created(
                connection,
                command.task_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
            )
            association_digest = content_digest(
                {
                    "principal_id": workspace.mandate.principal_id,
                    "tenant_id": actor.tenant_id,
                    "workspace_id": actor.workspace_id,
                    "mandate_id": mandate_id,
                    "task_id": command.task_id,
                    "task_created_event_digest": task_created_digest,
                }
            )
            association_id = f"mandate-task-association:{association_digest}"
            rows = connection.execute(
                f"SELECT * FROM {self._LINK_TABLE} WHERE association_id = ? "
                "ORDER BY rowid",
                (association_id,),
            ).fetchall()
            links = tuple(self._decode_link(row) for row in rows)
            revocation_rows = connection.execute(
                f"SELECT * FROM {self._REVOCATION_TABLE} WHERE association_id = ?",
                (association_id,),
            ).fetchall()
            revocations = {
                str(row["link_id"]): self._decode_revocation(row)
                for row in revocation_rows
            }
            active = tuple(link for link in links if link.link_id not in revocations)
            if len(active) > 1:
                raise MandateResponsibilityPersistenceConflict(
                    "multiple active responsibility links exist"
                )
            if active:
                if active[0].correction_epoch != operational.correction_epoch:
                    raise MandateResponsibilityDenied(
                        "correction epoch drift prevents responsibility relink"
                    )
                if active[0].command_digest != command_digest:
                    raise MandateResponsibilityConflict(
                        "active association is bound to a different command"
                    )
                connection.rollback()
                return active[0]
            prior_digest: str | None = None
            if links:
                latest = links[-1]
                if latest.correction_epoch != operational.correction_epoch:
                    raise MandateResponsibilityDenied(
                        "correction epoch drift prevents responsibility relink"
                    )
                prior = revocations.get(latest.link_id)
                if prior is None:
                    raise MandateResponsibilityPersistenceConflict(
                        "inactive responsibility link lacks revocation"
                    )
                prior_digest = prior.record_digest
            link_identity_digest = content_digest(
                {
                    "association_id": association_id,
                    "correction_epoch": operational.correction_epoch,
                    "workspace_record_digest": workspace_digest,
                    "operational_mandate_ref_digest": operational_digest,
                    "prior_record_digest": prior_digest,
                    "command_digest": command_digest,
                }
            )
            link = self._seal_link(
                {
                    "association_id": association_id,
                    "link_id": f"mandate-task-link:{link_identity_digest}",
                    "principal_id": workspace.mandate.principal_id,
                    "tenant_id": actor.tenant_id,
                    "workspace_id": actor.workspace_id,
                    "mandate_id": mandate_id,
                    "task_id": command.task_id,
                    "task_created_event_digest": task_created_digest,
                    "workspace_record_digest": workspace_digest,
                    "operational_mandate_ref_digest": operational_digest,
                    "correction_epoch": operational.correction_epoch,
                    "linked_by": actor.principal_id,
                    "linked_at": now,
                    "reason": command.reason,
                    "prior_record_digest": prior_digest,
                    "command_digest": command_digest,
                    "task_activation_authorized": False,
                    "capability_grant_authorized": False,
                    "external_effects_authorized": False,
                }
            )
            connection.execute(
                f"INSERT INTO {self._LINK_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    link.association_id,
                    link.link_id,
                    link.principal_id,
                    link.tenant_id,
                    link.workspace_id,
                    link.mandate_id,
                    link.task_id,
                    link.correction_epoch,
                    link.command_digest,
                    link.record_digest,
                    canonical_json(link),
                ),
            )
            connection.commit()
            return link
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def list_links(
        self,
        mandate_id: str,
        reader: PrincipalIdentity,
        *,
        include_revoked: bool = True,
    ) -> tuple[MandateTaskLink, ...]:
        connection = self._connect()
        try:
            workspace, _ = self._read_workspace(connection, mandate_id, reader)
            rows = connection.execute(
                f"SELECT * FROM {self._LINK_TABLE} WHERE principal_id = ? "
                "AND tenant_id = ? AND workspace_id = ? AND mandate_id = ? "
                "ORDER BY rowid",
                (
                    workspace.mandate.principal_id,
                    reader.tenant_id,
                    reader.workspace_id,
                    mandate_id,
                ),
            ).fetchall()
            links = tuple(self._decode_link(row) for row in rows)
            if include_revoked:
                return links
            revoked = {
                str(row["link_id"])
                for row in connection.execute(
                    f"SELECT link_id FROM {self._REVOCATION_TABLE} "
                    "WHERE principal_id = ? AND tenant_id = ? "
                    "AND workspace_id = ? AND mandate_id = ?",
                    (
                        workspace.mandate.principal_id,
                        reader.tenant_id,
                        reader.workspace_id,
                        mandate_id,
                    ),
                ).fetchall()
            }
            return tuple(link for link in links if link.link_id not in revoked)
        finally:
            connection.close()

    def revoke_link(
        self,
        command: MandateTaskLinkRevocationCommand,
        mandate_id: str,
        link_id: str,
        actor: PrincipalIdentity,
    ) -> MandateTaskLinkRevocation:
        now = self._clock()
        command_digest = content_digest(command)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            workspace, _, operational, _ = self._read_authority(
                connection,
                mandate_id,
                actor,
                require_admin=True,
                require_active=True,
                now=now,
            )
            row = connection.execute(
                f"SELECT * FROM {self._LINK_TABLE} WHERE link_id = ? "
                "AND principal_id = ? AND tenant_id = ? AND workspace_id = ? "
                "AND mandate_id = ?",
                (
                    link_id,
                    workspace.mandate.principal_id,
                    actor.tenant_id,
                    actor.workspace_id,
                    mandate_id,
                ),
            ).fetchone()
            if row is None:
                raise MandateResponsibilityNotFound(link_id)
            link = self._decode_link(row)
            if link.correction_epoch != operational.correction_epoch:
                raise MandateResponsibilityDenied(
                    "correction epoch drift prevents responsibility revocation"
                )
            if command.expected_link_digest != link.record_digest:
                raise MandateResponsibilityConflict("stale link digest")
            existing = connection.execute(
                f"SELECT * FROM {self._REVOCATION_TABLE} WHERE link_id = ?",
                (link_id,),
            ).fetchone()
            if existing is not None:
                revocation = self._decode_revocation(existing)
                if revocation.command_digest != command_digest:
                    raise MandateResponsibilityConflict(
                        "responsibility revocation conflicts with existing bytes"
                    )
                connection.rollback()
                return revocation
            revocation_identity_digest = content_digest(
                {
                    "link_record_digest": link.record_digest,
                    "correction_epoch": operational.correction_epoch,
                    "command_digest": command_digest,
                }
            )
            revocation = self._seal_revocation(
                {
                    "revocation_id": (
                        f"mandate-task-link-revocation:{revocation_identity_digest}"
                    ),
                    "association_id": link.association_id,
                    "link_id": link.link_id,
                    "link_record_digest": link.record_digest,
                    "principal_id": link.principal_id,
                    "tenant_id": link.tenant_id,
                    "workspace_id": link.workspace_id,
                    "mandate_id": link.mandate_id,
                    "task_id": link.task_id,
                    "correction_epoch": operational.correction_epoch,
                    "revoked_by": actor.principal_id,
                    "revoked_at": now,
                    "reason": command.reason,
                    "command_digest": command_digest,
                    "task_activation_authorized": False,
                    "capability_grant_authorized": False,
                    "external_effects_authorized": False,
                }
            )
            connection.execute(
                f"INSERT INTO {self._REVOCATION_TABLE} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    revocation.revocation_id,
                    revocation.association_id,
                    revocation.link_id,
                    revocation.principal_id,
                    revocation.tenant_id,
                    revocation.workspace_id,
                    revocation.mandate_id,
                    revocation.correction_epoch,
                    revocation.command_digest,
                    revocation.record_digest,
                    canonical_json(revocation),
                ),
            )
            connection.commit()
            return revocation
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
