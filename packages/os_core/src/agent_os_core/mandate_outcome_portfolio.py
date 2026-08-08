from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from agent_os_contracts import (
    ActionContract,
    MandateTaskLink,
    ObservedOutcome,
    OutcomePortfolio,
    OutcomePortfolioCreateCommand,
    OutcomePortfolioHelpGap,
    OutcomePortfolioHelpRequest,
    OutcomePortfolioHelpRespondCommand,
    OutcomePortfolioView,
    OutcomeStatus,
    PersistentCommitment,
    PersistentCommitmentAttachCommand,
    PersistentCommitmentState,
    PrincipalIdentity,
    PrincipalRole,
    SettlementCommand,
    SettlementRecord,
    SrlHelpRequest,
    SrlHelpResponse,
    SrlHelpResponseKind,
    content_digest,
)
from agent_os_contracts.outcome_portfolio import (
    _outcome_portfolio_help_request_id,
    help_class_for_gap,
)

from .mandate_responsibility import (
    MandateResponsibilityDenied,
    MandateResponsibilityNotFound,
    MandateResponsibilityPersistenceConflict,
    SQLiteMandateResponsibilityStore,
)
from .task_aggregate import TaskAggregate


class MandateOutcomePortfolioDenied(PermissionError):
    pass


class MandateOutcomePortfolioNotFound(LookupError):
    pass


class MandateOutcomePortfolioConflict(RuntimeError):
    pass


class MandateOutcomePortfolioPersistenceConflict(RuntimeError):
    pass


class OutcomePortfolioTaskReader(Protocol):
    def get_task(self, task_id: str) -> TaskAggregate: ...

    def current_outcome(self, task_id: str) -> ObservedOutcome | None: ...

    def pending_action(self, task_id: str) -> ActionContract | None: ...


_STATUS_TO_STATE = {
    OutcomeStatus.VERIFIED: PersistentCommitmentState.SETTLED_MET,
    OutcomeStatus.NOT_MET: PersistentCommitmentState.SETTLED_NOT_MET,
    OutcomeStatus.INVALID: PersistentCommitmentState.INVALID,
    OutcomeStatus.UNRESOLVED: PersistentCommitmentState.INVALID,
}


class SQLiteMandateOutcomePortfolioStore:
    """Mandate-scoped Outcome Portfolio + Persistent Commitment settlement ledger."""

    _PORTFOLIO_TABLE = "mandate_outcome_portfolios"
    _COMMITMENT_TABLE = "mandate_persistent_commitments"
    _SETTLEMENT_TABLE = "mandate_outcome_settlements"
    _HELP_TABLE = "mandate_outcome_portfolio_help_requests"

    def __init__(
        self,
        database: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        uri: bool = False,
        task_reader: OutcomePortfolioTaskReader | None = None,
    ) -> None:
        self._authority = SQLiteMandateResponsibilityStore(
            database, clock=clock, uri=uri
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._task_reader = task_reader
        self._database = self._authority._database
        self._uri = self._authority._uri
        self._ensure_schema()

    def bind_task_reader(self, task_reader: OutcomePortfolioTaskReader) -> None:
        self._task_reader = task_reader

    def _connect(self) -> sqlite3.Connection:
        return self._authority._connect()

    def _ensure_schema(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._PORTFOLIO_TABLE} (
                    portfolio_id TEXT PRIMARY KEY,
                    mandate_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    record_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {self._COMMITMENT_TABLE} (
                    commitment_record_id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    mandate_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    record_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {self._SETTLEMENT_TABLE} (
                    settlement_id TEXT PRIMARY KEY,
                    commitment_record_id TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    record_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {self._HELP_TABLE} (
                    help_request_id TEXT PRIMARY KEY,
                    mandate_id TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    task_id TEXT,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    record_digest TEXT NOT NULL
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _map_denied(self, exc: Exception) -> None:
        if isinstance(exc, MandateResponsibilityDenied):
            raise MandateOutcomePortfolioDenied(str(exc)) from exc
        if isinstance(exc, MandateResponsibilityNotFound):
            raise MandateOutcomePortfolioNotFound(str(exc)) from exc
        if isinstance(exc, MandateResponsibilityPersistenceConflict):
            raise MandateOutcomePortfolioPersistenceConflict(str(exc)) from exc

    def _read_authority(self, connection, mandate_id, actor, *, require_admin, require_active, now):
        try:
            return self._authority._read_authority(
                connection,
                mandate_id,
                actor,
                require_admin=require_admin,
                require_active=require_active,
                now=now,
            )
        except (
            MandateResponsibilityDenied,
            MandateResponsibilityNotFound,
            MandateResponsibilityPersistenceConflict,
        ) as exc:
            self._map_denied(exc)
            raise

    def _require_active_task_link(
        self,
        connection: sqlite3.Connection,
        *,
        mandate_id: str,
        task_id: str,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        workspace_digest: str,
        operational_digest: str,
        correction_epoch: int,
        portfolio_id: str,
        actor: PrincipalIdentity,
        help_deferred: list[dict[str, object]] | None = None,
    ) -> None:
        """Fail closed unless an active MandateTaskLink binds task to mandate."""
        if help_deferred is None:
            help_deferred = []
        link_rows = connection.execute(
            f"SELECT * FROM {self._authority._LINK_TABLE} "
            "WHERE principal_id = ? AND tenant_id = ? AND workspace_id = ? "
            "AND mandate_id = ? AND task_id = ? ORDER BY rowid",
            (principal_id, tenant_id, workspace_id, mandate_id, task_id),
        ).fetchall()
        links: list[MandateTaskLink] = [
            self._authority._decode_link(row) for row in link_rows
        ]
        if not links:
            help_deferred.append({
                "mandate_id": mandate_id, "portfolio_id": portfolio_id,
                "task_id": task_id, "actor": actor,
                "gap_kind": OutcomePortfolioHelpGap.MISSING_TASK_LINK,
                "details": "active MandateTaskLink is required for portfolio settlement",
            })
            raise MandateOutcomePortfolioDenied(
                "active MandateTaskLink is required for portfolio settlement"
            )
        revocations = self._authority._validated_revocations_for_links(
            connection,
            tuple(links),
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            mandate_id=mandate_id,
        )
        revoked = {revocation.link_id for revocation in revocations}
        active: list[MandateTaskLink] = [
            link for link in links if link.link_id not in revoked
        ]
        if not active:
            help_deferred.append({
                "mandate_id": mandate_id, "portfolio_id": portfolio_id,
                "task_id": task_id, "actor": actor,
                "gap_kind": OutcomePortfolioHelpGap.REVOKED_TASK_LINK,
                "details": "all active MandateTaskLinks for task have been revoked",
            })
            raise MandateOutcomePortfolioDenied(
                "active MandateTaskLink is required for portfolio settlement"
            )
        if len(active) > 1:
            raise MandateOutcomePortfolioPersistenceConflict(
                "multiple active MandateTaskLinks exist for task under mandate"
            )
        link = active[0]
        if link.correction_epoch != correction_epoch:
            help_deferred.append({
                "mandate_id": mandate_id, "portfolio_id": portfolio_id,
                "task_id": task_id, "actor": actor,
                "gap_kind": OutcomePortfolioHelpGap.CORRECTION_EPOCH_DRIFT,
                "details": "MandateTaskLink correction epoch drift prevents settlement",
            })
            raise MandateOutcomePortfolioDenied(
                "MandateTaskLink correction epoch drift prevents settlement"
            )
        if (
            link.workspace_record_digest != workspace_digest
            or link.operational_mandate_ref_digest != operational_digest
        ):
            help_deferred.append({
                "mandate_id": mandate_id, "portfolio_id": portfolio_id,
                "task_id": task_id, "actor": actor,
                "gap_kind": OutcomePortfolioHelpGap.DIGEST_DRIFT,
                "details": "MandateTaskLink authority digest drift prevents settlement",
            })
            raise MandateOutcomePortfolioDenied(
                "MandateTaskLink authority digest drift prevents settlement"
            )

    def create_portfolio(
        self,
        command: OutcomePortfolioCreateCommand,
        mandate_id: str,
        actor: PrincipalIdentity,
    ) -> OutcomePortfolio:
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
            existing = connection.execute(
                f"SELECT * FROM {self._PORTFOLIO_TABLE} WHERE mandate_id = ? "
                "AND tenant_id = ? AND workspace_id = ?",
                (mandate_id, actor.tenant_id, actor.workspace_id),
            ).fetchone()
            if existing is not None:
                portfolio = OutcomePortfolio.model_validate_json(str(existing["payload"]))
                if (
                    portfolio.correction_epoch != operational.correction_epoch
                    or portfolio.workspace_record_digest != workspace_digest
                    or portfolio.operational_mandate_ref_digest != operational_digest
                ):
                    raise MandateOutcomePortfolioDenied(
                        "authority digest drift prevents portfolio replay"
                    )
                if portfolio.command_digest != command_digest:
                    raise MandateOutcomePortfolioConflict(
                        "portfolio already exists with a different command"
                    )
                connection.commit()
                return portfolio
            desired = tuple(workspace.mandate.desired_outcomes)
            if not desired:
                raise MandateOutcomePortfolioDenied(
                    "Mandate desired_outcomes are required for a portfolio"
                )
            portfolio_id = (
                "outcome-portfolio:"
                + content_digest(
                    {
                        "mandate_id": mandate_id,
                        "tenant_id": actor.tenant_id,
                        "workspace_id": actor.workspace_id,
                    }
                )
            )
            payload = {
                "portfolio_id": portfolio_id,
                "principal_id": workspace.mandate.principal_id,
                "tenant_id": actor.tenant_id,
                "workspace_id": actor.workspace_id,
                "mandate_id": mandate_id,
                "desired_outcomes": desired,
                "workspace_record_digest": workspace_digest,
                "operational_mandate_ref_digest": operational_digest,
                "correction_epoch": operational.correction_epoch,
                "created_by": actor.principal_id,
                "created_at": now,
                "command_digest": command_digest,
                "task_activation_authorized": False,
                "capability_grant_authorized": False,
                "external_effects_authorized": False,
            }
            if command.reason is not None:
                payload["reason"] = command.reason
            if command.authority_credential_digest is not None:
                payload["authority_credential_digest"] = (
                    command.authority_credential_digest
                )
            record_digest = content_digest({"schema_version": "1.0", **payload})
            portfolio = OutcomePortfolio.model_validate(
                {**payload, "record_digest": record_digest}
            )
            connection.execute(
                f"INSERT INTO {self._PORTFOLIO_TABLE} "
                "(portfolio_id, mandate_id, tenant_id, workspace_id, principal_id, "
                "payload, record_digest) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    portfolio.portfolio_id,
                    portfolio.mandate_id,
                    portfolio.tenant_id,
                    portfolio.workspace_id,
                    portfolio.principal_id,
                    portfolio.model_dump_json(),
                    portfolio.record_digest,
                ),
            )
            connection.commit()
            return portfolio
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_view(
        self,
        mandate_id: str,
        actor: PrincipalIdentity,
        *,
        include_resolved_help: bool = False,
    ) -> OutcomePortfolioView:
        connection = self._connect()
        try:
            self._read_authority(
                connection,
                mandate_id,
                actor,
                require_admin=False,
                require_active=False,
                now=self._clock(),
            )
            row = connection.execute(
                f"SELECT * FROM {self._PORTFOLIO_TABLE} WHERE mandate_id = ? "
                "AND tenant_id = ? AND workspace_id = ?",
                (mandate_id, actor.tenant_id, actor.workspace_id),
            ).fetchone()
            if row is None:
                raise MandateOutcomePortfolioNotFound(
                    f"Outcome portfolio not found for mandate: {mandate_id}"
                )
            portfolio = OutcomePortfolio.model_validate_json(str(row["payload"]))
            commitments = tuple(
                PersistentCommitment.model_validate_json(str(item["payload"]))
                for item in connection.execute(
                    f"SELECT * FROM {self._COMMITMENT_TABLE} WHERE portfolio_id = ? "
                    "ORDER BY rowid",
                    (portfolio.portfolio_id,),
                ).fetchall()
            )
            settlements = tuple(
                SettlementRecord.model_validate_json(str(item["payload"]))
                for item in connection.execute(
                    f"SELECT * FROM {self._SETTLEMENT_TABLE} WHERE portfolio_id = ? "
                    "ORDER BY rowid",
                    (portfolio.portfolio_id,),
                ).fetchall()
            )
            help_requests: tuple[OutcomePortfolioHelpRequest, ...] = ()
            if actor.role is PrincipalRole.TENANT_ADMIN:
                help_requests = self._load_help_requests(
                    connection,
                    mandate_id=mandate_id,
                    tenant_id=actor.tenant_id,
                    workspace_id=actor.workspace_id,
                    portfolio_id=portfolio.portfolio_id,
                    include_resolved=include_resolved_help,
                )
            return OutcomePortfolioView(
                portfolio=portfolio,
                commitments=commitments,
                settlements=settlements,
                help_requests=help_requests,
            )
        finally:
            connection.close()

    def attach_commitment(
        self,
        command: PersistentCommitmentAttachCommand,
        mandate_id: str,
        actor: PrincipalIdentity,
        *,
        pre_insert_guard: Callable[[], None] | None = None,
    ) -> PersistentCommitment:
        if self._task_reader is None:
            raise MandateOutcomePortfolioDenied("task reader is required")
        now = self._clock()
        command_digest = content_digest(command)
        connection = self._connect()
        help_deferred: list[dict[str, object]] = []
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
            portfolio = self._require_portfolio(
                connection, mandate_id, actor, workspace_digest, operational_digest,
                help_deferred=help_deferred,
            )
            self._require_active_task_link(
                connection,
                mandate_id=mandate_id,
                task_id=command.task_id,
                principal_id=workspace.mandate.principal_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
                workspace_digest=workspace_digest,
                operational_digest=operational_digest,
                correction_epoch=operational.correction_epoch,
                portfolio_id=portfolio.portfolio_id,
                actor=actor,
                help_deferred=help_deferred,
            )
            task = self._task_reader.get_task(command.task_id)
            commitment = task.commitment
            expected = task.expected_outcome
            if commitment is None or expected is None:
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": command.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.MISSING_COMMITMENT_OR_EXPECTED,
                    "details": "Task Commitment and ExpectedOutcome are required",
                })
                raise MandateOutcomePortfolioDenied(
                    "Task Commitment and ExpectedOutcome are required"
                )
            if (
                content_digest(commitment) != command.commitment_digest
                or content_digest(expected) != command.expected_outcome_digest
            ):
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": command.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.DIGEST_DRIFT,
                    "details": "commitment digests do not match Task truth",
                })
                raise MandateOutcomePortfolioDenied(
                    "commitment digests do not match Task truth"
                )
            if (
                expected.tenant_id != actor.tenant_id
                or expected.workspace_id != actor.workspace_id
                or expected.task_id != command.task_id
            ):
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": command.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.SCOPE_MISMATCH,
                    "details": "Task scope is not authorized",
                })
                raise MandateOutcomePortfolioDenied("Task scope is not authorized")
            record_key = content_digest(
                {
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": command.task_id,
                    "commitment_digest": command.commitment_digest,
                    "expected_outcome_digest": command.expected_outcome_digest,
                }
            )
            commitment_record_id = f"persistent-commitment:{record_key}"
            existing = connection.execute(
                f"SELECT * FROM {self._COMMITMENT_TABLE} "
                "WHERE commitment_record_id = ?",
                (commitment_record_id,),
            ).fetchone()
            if existing is not None:
                record = PersistentCommitment.model_validate_json(
                    str(existing["payload"])
                )
                if record.command_digest != command_digest:
                    raise MandateOutcomePortfolioConflict(
                        "persistent commitment already exists with different command"
                    )
                if pre_insert_guard is not None:
                    pre_insert_guard()
                connection.commit()
                return record
            payload = {
                "commitment_record_id": commitment_record_id,
                "portfolio_id": portfolio.portfolio_id,
                "principal_id": workspace.mandate.principal_id,
                "tenant_id": actor.tenant_id,
                "workspace_id": actor.workspace_id,
                "mandate_id": mandate_id,
                "task_id": command.task_id,
                "commitment_digest": command.commitment_digest,
                "expected_outcome_digest": command.expected_outcome_digest,
                "state": PersistentCommitmentState.OPEN,
                "workspace_record_digest": workspace_digest,
                "operational_mandate_ref_digest": operational_digest,
                "correction_epoch": operational.correction_epoch,
                "attached_by": actor.principal_id,
                "attached_at": now,
                "command_digest": command_digest,
                "task_activation_authorized": False,
                "capability_grant_authorized": False,
                "external_effects_authorized": False,
            }
            if command.reason is not None:
                payload["reason"] = command.reason
            record_digest = content_digest({"schema_version": "1.0", **payload})
            record = PersistentCommitment.model_validate(
                {**payload, "record_digest": record_digest}
            )
            if pre_insert_guard is not None:
                pre_insert_guard()
            connection.execute(
                f"INSERT INTO {self._COMMITMENT_TABLE} "
                "(commitment_record_id, portfolio_id, mandate_id, task_id, state, "
                "payload, record_digest) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.commitment_record_id,
                    record.portfolio_id,
                    record.mandate_id,
                    record.task_id,
                    record.state.value,
                    record.model_dump_json(),
                    record.record_digest,
                ),
            )
            connection.commit()
            return record
        except Exception:
            connection.rollback()
            self._flush_help_deferred(help_deferred)
            raise
        finally:
            connection.close()

    def settle(
        self,
        command: SettlementCommand,
        mandate_id: str,
        actor: PrincipalIdentity,
    ) -> SettlementRecord:
        if self._task_reader is None:
            raise MandateOutcomePortfolioDenied("task reader is required")
        now = self._clock()
        command_digest = content_digest(command)
        connection = self._connect()
        help_deferred: list[dict[str, object]] = []
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
            portfolio = self._require_portfolio(
                connection, mandate_id, actor, workspace_digest, operational_digest,
                help_deferred=help_deferred,
            )
            row = connection.execute(
                f"SELECT * FROM {self._COMMITMENT_TABLE} "
                "WHERE commitment_record_id = ?",
                (command.commitment_record_id,),
            ).fetchone()
            if row is None:
                raise MandateOutcomePortfolioNotFound(
                    f"Persistent commitment not found: {command.commitment_record_id}"
                )
            commitment = PersistentCommitment.model_validate_json(str(row["payload"]))
            if (
                commitment.portfolio_id != portfolio.portfolio_id
                or commitment.mandate_id != mandate_id
            ):
                raise MandateOutcomePortfolioDenied(
                    "commitment is outside mandate portfolio"
                )
            self._require_active_task_link(
                connection,
                mandate_id=mandate_id,
                task_id=commitment.task_id,
                principal_id=workspace.mandate.principal_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
                workspace_digest=workspace_digest,
                operational_digest=operational_digest,
                correction_epoch=operational.correction_epoch,
                portfolio_id=portfolio.portfolio_id,
                actor=actor,
                help_deferred=help_deferred,
            )
            if commitment.state is not PersistentCommitmentState.OPEN:
                raise MandateOutcomePortfolioConflict(
                    "commitment is not open for settlement"
                )
            if commitment.expected_outcome_digest != command.expected_outcome_digest:
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": commitment.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.DIGEST_DRIFT,
                    "details": "expected outcome digest drift prevents settlement",
                })
                raise MandateOutcomePortfolioDenied(
                    "expected outcome digest drift prevents settlement"
                )
            current = self._task_reader.current_outcome(commitment.task_id)
            if current is None:
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": commitment.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME,
                    "details": "Task current ObservedOutcome is required",
                })
                raise MandateOutcomePortfolioDenied(
                    "Task current ObservedOutcome is required"
                )
            if content_digest(current) != command.observed_outcome_digest:
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": commitment.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.DIGEST_DRIFT,
                    "details": "observed outcome digest does not match Task current outcome",
                })
                raise MandateOutcomePortfolioDenied(
                    "observed outcome digest does not match Task current outcome"
                )
            if current.status is not command.observed_status:
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": commitment.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.DIGEST_DRIFT,
                    "details": "observed status does not match Task current outcome",
                })
                raise MandateOutcomePortfolioDenied(
                    "observed status does not match Task current outcome"
                )
            task = self._task_reader.get_task(commitment.task_id)
            if task.expected_outcome is None or content_digest(
                task.expected_outcome
            ) != command.expected_outcome_digest:
                help_deferred.append({
                    "mandate_id": mandate_id,
                    "portfolio_id": portfolio.portfolio_id,
                    "task_id": commitment.task_id,
                    "actor": actor,
                    "gap_kind": OutcomePortfolioHelpGap.DIGEST_DRIFT,
                    "details": "Task ExpectedOutcome digest drift prevents settlement",
                })
                raise MandateOutcomePortfolioDenied(
                    "Task ExpectedOutcome digest drift prevents settlement"
                )
            resulting = _STATUS_TO_STATE[current.status]
            if (
                resulting is PersistentCommitmentState.SETTLED_MET
                and current.status is not OutcomeStatus.VERIFIED
            ):
                raise MandateOutcomePortfolioPersistenceConflict(
                    "MET settlement requires VERIFIED outcome"
                )
            settlement_id = "settlement:" + content_digest(
                {
                    "commitment_record_id": commitment.commitment_record_id,
                    "observed_outcome_digest": command.observed_outcome_digest,
                }
            )
            existing_settlement = connection.execute(
                f"SELECT * FROM {self._SETTLEMENT_TABLE} WHERE settlement_id = ?",
                (settlement_id,),
            ).fetchone()
            if existing_settlement is not None:
                record = SettlementRecord.model_validate_json(
                    str(existing_settlement["payload"])
                )
                connection.commit()
                return record
            payload = {
                "settlement_id": settlement_id,
                "commitment_record_id": commitment.commitment_record_id,
                "portfolio_id": portfolio.portfolio_id,
                "mandate_id": mandate_id,
                "task_id": commitment.task_id,
                "expected_outcome_digest": command.expected_outcome_digest,
                "observed_outcome_digest": command.observed_outcome_digest,
                "observed_status": current.status,
                "resulting_state": resulting,
                "settled_by": actor.principal_id,
                "settled_at": now,
                "command_digest": command_digest,
                "task_activation_authorized": False,
                "capability_grant_authorized": False,
                "external_effects_authorized": False,
            }
            if command.reason is not None:
                payload["reason"] = command.reason
            record_digest = content_digest({"schema_version": "1.0", **payload})
            settlement = SettlementRecord.model_validate(
                {**payload, "record_digest": record_digest}
            )
            updated_payload = commitment.model_dump(mode="json")
            updated_payload["state"] = resulting.value
            updated_payload.pop("record_digest", None)
            updated = PersistentCommitment.model_validate(
                {
                    **updated_payload,
                    "record_digest": content_digest(
                        {"schema_version": "1.0", **updated_payload}
                    ),
                }
            )
            connection.execute(
                f"UPDATE {self._COMMITMENT_TABLE} SET state = ?, payload = ?, "
                "record_digest = ? WHERE commitment_record_id = ?",
                (
                    updated.state.value,
                    updated.model_dump_json(),
                    updated.record_digest,
                    updated.commitment_record_id,
                ),
            )
            connection.execute(
                f"INSERT INTO {self._SETTLEMENT_TABLE} "
                "(settlement_id, commitment_record_id, portfolio_id, payload, "
                "record_digest) VALUES (?, ?, ?, ?, ?)",
                (
                    settlement.settlement_id,
                    settlement.commitment_record_id,
                    settlement.portfolio_id,
                    settlement.model_dump_json(),
                    settlement.record_digest,
                ),
            )
            self._auto_cancel_open_help_for_task(
                connection,
                mandate_id=mandate_id,
                portfolio_id=portfolio.portfolio_id,
                task_id=commitment.task_id,
                actor=actor,
                now=now,
                notes=(
                    f"auto-cancelled after settlement {settlement.settlement_id} "
                    f"-> {resulting.value}"
                ),
            )
            connection.commit()
            return settlement
        except Exception:
            connection.rollback()
            self._flush_help_deferred(help_deferred)
            raise
        finally:
            connection.close()

    def _require_portfolio(
        self,
        connection: sqlite3.Connection,
        mandate_id: str,
        actor: PrincipalIdentity,
        workspace_digest: str,
        operational_digest: str,
        help_deferred: list[dict[str, object]] | None = None,
    ) -> OutcomePortfolio:
        if help_deferred is None:
            help_deferred = []
        row = connection.execute(
            f"SELECT * FROM {self._PORTFOLIO_TABLE} WHERE mandate_id = ? "
            "AND tenant_id = ? AND workspace_id = ?",
            (mandate_id, actor.tenant_id, actor.workspace_id),
        ).fetchone()
        if row is None:
            raise MandateOutcomePortfolioNotFound(
                f"Outcome portfolio not found for mandate: {mandate_id}"
            )
        portfolio = OutcomePortfolio.model_validate_json(str(row["payload"]))
        if (
            portfolio.workspace_record_digest != workspace_digest
            or portfolio.operational_mandate_ref_digest != operational_digest
        ):
            help_deferred.append({
                "mandate_id": mandate_id,
                "portfolio_id": portfolio.portfolio_id,
                "task_id": None,
                "actor": actor,
                "gap_kind": OutcomePortfolioHelpGap.DIGEST_DRIFT,
                "details": "portfolio authority digest drift",
            })
            raise MandateOutcomePortfolioDenied("portfolio authority digest drift")
        return portfolio

    def _flush_help_deferred(
        self, help_deferred: list[dict[str, object]]
    ) -> None:
        for item in help_deferred:
            self._emit_help_request(
                mandate_id=str(item["mandate_id"]),
                portfolio_id=str(item["portfolio_id"]),
                task_id=item["task_id"] if isinstance(item["task_id"], (str, type(None))) else str(item["task_id"]),
                actor=item["actor"],  # type: ignore[arg-type]
                gap_kind=item["gap_kind"],  # type: ignore[arg-type]
                details=str(item["details"]),
            )

    def _emit_help_request(
        self,
        *,
        mandate_id: str,
        portfolio_id: str,
        task_id: str | None,
        actor: PrincipalIdentity,
        gap_kind: OutcomePortfolioHelpGap,
        details: str,
        pending_action_digest: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> OutcomePortfolioHelpRequest:
        now = self._clock()
        help_id = _outcome_portfolio_help_request_id(
            mandate_id, portfolio_id, task_id, gap_kind, details,
            actor.principal_id, now,
        )
        conn: sqlite3.Connection
        owns_connection = connection is None
        if connection is not None:
            conn = connection
        else:
            conn = self._connect()
        try:
            workspace, _, _, _ = self._read_authority(
                conn,
                mandate_id,
                actor,
                require_admin=False,
                require_active=False,
                now=now,
            )
            standing_mission_id = workspace.standing_mission.standing_mission_id
            if standing_mission_id != (
                f"standing-mission:{workspace.standing_mission.parent_mandate_digest}"
            ):
                raise MandateOutcomePortfolioPersistenceConflict(
                    "standing mission id is not digest-bound"
                )
            srl_help = SrlHelpRequest(
                help_request_id=help_id,
                mandate_id=mandate_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
                standing_mission_id=standing_mission_id,
                commitment_id=None,
                goal_id=None,
                help_class=help_class_for_gap(gap_kind),
                known_facts=(),
                unknowns=(details,),
                acquisition_attempts=(
                    "checked MandateTaskLink / Task ExpectedOutcome / ObservedOutcome digests",
                ),
                unsafe_boundary=(
                    "outcome portfolio settlement cannot invent missing truth or authority"
                ),
                bounded_options=(),
                minimum_answer=details,
                continuable_work=(
                    "inspect portfolio view and resolve the named gap before retrying settlement",
                ),
                expires_at=now + timedelta(hours=24),
                cancellation_policy="superseded_by_resolved_gap_or_mandate_revocation",
                escalation_policy="founder_or_mandate_admin",
                requested_at=now,
            )
            help_req = OutcomePortfolioHelpRequest(
                portfolio_id=portfolio_id,
                task_id=task_id,
                gap_kind=gap_kind,
                pending_action_digest=pending_action_digest,
                srl_help=srl_help,
            )
            conn.execute(
                f"INSERT OR IGNORE INTO {self._HELP_TABLE} "
                "(help_request_id, mandate_id, portfolio_id, task_id, tenant_id, "
                "workspace_id, payload, record_digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    help_id, mandate_id, portfolio_id, task_id,
                    actor.tenant_id, actor.workspace_id,
                    help_req.model_dump_json(),
                    content_digest(help_req),
                ),
            )
            if owns_connection:
                conn.commit()
            return help_req
        finally:
            if owns_connection:
                conn.close()

    def request_missing_outcome_help(
        self,
        commitment_record_id: str,
        mandate_id: str,
        actor: PrincipalIdentity,
    ) -> OutcomePortfolioHelpRequest:
        """Emit one typed gap after revalidating the canonical open responsibility."""
        if self._task_reader is None:
            raise MandateOutcomePortfolioDenied("task reader is required")
        now = self._clock()
        connection = self._connect()
        help_deferred: list[dict[str, object]] = []
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
            portfolio = self._require_portfolio(
                connection,
                mandate_id,
                actor,
                workspace_digest,
                operational_digest,
                help_deferred=help_deferred,
            )
            row = connection.execute(
                f"SELECT * FROM {self._COMMITMENT_TABLE} "
                "WHERE commitment_record_id = ?",
                (commitment_record_id,),
            ).fetchone()
            if row is None:
                raise MandateOutcomePortfolioNotFound(
                    f"Persistent commitment not found: {commitment_record_id}"
                )
            commitment = PersistentCommitment.model_validate_json(
                str(row["payload"])
            )
            if (
                commitment.portfolio_id != portfolio.portfolio_id
                or commitment.mandate_id != mandate_id
                or commitment.state is not PersistentCommitmentState.OPEN
            ):
                raise MandateOutcomePortfolioDenied(
                    "missing-outcome Help requires an open Mandate commitment"
                )
            self._require_active_task_link(
                connection,
                mandate_id=mandate_id,
                task_id=commitment.task_id,
                principal_id=workspace.mandate.principal_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
                workspace_digest=workspace_digest,
                operational_digest=operational_digest,
                correction_epoch=operational.correction_epoch,
                portfolio_id=portfolio.portfolio_id,
                actor=actor,
                help_deferred=help_deferred,
            )
            task = self._task_reader.get_task(commitment.task_id)
            if self._task_reader.current_outcome(commitment.task_id) is not None:
                raise MandateOutcomePortfolioConflict(
                    "current ObservedOutcome exists; missing-outcome Help is invalid"
                )
            pending_action_approval = (
                task.run is not None and task.run.status.value == "WAITING_APPROVAL"
            )
            pending_action = (
                self._task_reader.pending_action(commitment.task_id)
                if pending_action_approval
                else None
            )
            if pending_action_approval and pending_action is None:
                raise MandateOutcomePortfolioConflict(
                    "WAITING_APPROVAL Task has no exact pending action"
                )
            gap_kind = (
                OutcomePortfolioHelpGap.PENDING_ACTION_APPROVAL
                if pending_action_approval
                else OutcomePortfolioHelpGap.MISSING_OBSERVED_OUTCOME
            )
            if pending_action is not None:
                details = (
                    "Exact pending Task action requires an external decision: "
                    f"{pending_action.action_digest()}"
                )
            else:
                details = "Task current ObservedOutcome is required"
            help_request = self._emit_help_request(
                mandate_id=mandate_id,
                portfolio_id=portfolio.portfolio_id,
                task_id=commitment.task_id,
                actor=actor,
                gap_kind=gap_kind,
                details=details,
                pending_action_digest=(
                    pending_action.action_digest()
                    if pending_action is not None
                    else None
                ),
                connection=connection,
            )
            connection.commit()
            return help_request
        except Exception:
            connection.rollback()
            self._flush_help_deferred(help_deferred)
            raise
        finally:
            connection.close()

    def list_help_requests(
        self,
        mandate_id: str,
        actor: PrincipalIdentity,
        *,
        include_resolved: bool = False,
    ) -> tuple[OutcomePortfolioHelpRequest, ...]:
        connection = self._connect()
        try:
            self._read_authority(
                connection,
                mandate_id,
                actor,
                require_admin=True,
                require_active=False,
                now=self._clock(),
            )
            return self._load_help_requests(
                connection,
                mandate_id=mandate_id,
                tenant_id=actor.tenant_id,
                workspace_id=actor.workspace_id,
                portfolio_id=None,
                include_resolved=include_resolved,
            )
        finally:
            connection.close()

    def respond_help_request(
        self,
        command: OutcomePortfolioHelpRespondCommand,
        mandate_id: str,
        help_request_id: str,
        actor: PrincipalIdentity,
    ) -> OutcomePortfolioHelpRequest:
        if command.response_kind in (
            SrlHelpResponseKind.CAPABILITY_GRANT,
            SrlHelpResponseKind.REVOCATION_REQUEST,
        ):
            raise MandateOutcomePortfolioDenied(
                "outcome portfolio help respond cannot grant capability or revoke"
            )
        if command.response_kind not in (
            SrlHelpResponseKind.OPERATOR_DECISION,
            SrlHelpResponseKind.CANCELLATION,
        ):
            raise MandateOutcomePortfolioDenied(
                "unsupported help response kind for outcome portfolio"
            )
        now = self._clock()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._read_authority(
                connection,
                mandate_id,
                actor,
                require_admin=True,
                require_active=False,
                now=now,
            )
            row = connection.execute(
                f"SELECT * FROM {self._HELP_TABLE} WHERE help_request_id = ? "
                "AND mandate_id = ? AND tenant_id = ? AND workspace_id = ?",
                (
                    help_request_id,
                    mandate_id,
                    actor.tenant_id,
                    actor.workspace_id,
                ),
            ).fetchone()
            if row is None:
                raise MandateOutcomePortfolioNotFound(
                    f"Help request not found: {help_request_id}"
                )
            current = OutcomePortfolioHelpRequest.model_validate_json(
                str(row["payload"])
            )
            if not current.is_open:
                raise MandateOutcomePortfolioConflict(
                    "help request already has a response"
                )
            response = SrlHelpResponse(
                help_request_id=help_request_id,
                responded_at=now,
                responder_principal_id=actor.principal_id,
                response_kind=command.response_kind,
                decision=command.decision,
                notes=command.notes,
            )
            updated = self._write_help_response(connection, current, response)
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _load_help_requests(
        self,
        connection: sqlite3.Connection,
        *,
        mandate_id: str,
        tenant_id: str,
        workspace_id: str,
        portfolio_id: str | None,
        include_resolved: bool,
    ) -> tuple[OutcomePortfolioHelpRequest, ...]:
        if portfolio_id is None:
            rows = connection.execute(
                f"SELECT * FROM {self._HELP_TABLE} WHERE mandate_id = ? "
                "AND tenant_id = ? AND workspace_id = ? ORDER BY rowid",
                (mandate_id, tenant_id, workspace_id),
            ).fetchall()
        else:
            rows = connection.execute(
                f"SELECT * FROM {self._HELP_TABLE} WHERE portfolio_id = ? "
                "AND mandate_id = ? AND tenant_id = ? AND workspace_id = ? "
                "ORDER BY rowid",
                (portfolio_id, mandate_id, tenant_id, workspace_id),
            ).fetchall()
        records = tuple(
            OutcomePortfolioHelpRequest.model_validate_json(str(row["payload"]))
            for row in rows
        )
        if include_resolved:
            return records
        return tuple(record for record in records if record.is_open)

    def _write_help_response(
        self,
        connection: sqlite3.Connection,
        current: OutcomePortfolioHelpRequest,
        response: SrlHelpResponse,
    ) -> OutcomePortfolioHelpRequest:
        updated = OutcomePortfolioHelpRequest.model_validate(
            {
                **current.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            }
        )
        connection.execute(
            f"UPDATE {self._HELP_TABLE} SET payload = ?, record_digest = ? "
            "WHERE help_request_id = ?",
            (
                updated.model_dump_json(),
                content_digest(updated),
                updated.help_request_id,
            ),
        )
        return updated

    def _auto_cancel_open_help_for_task(
        self,
        connection: sqlite3.Connection,
        *,
        mandate_id: str,
        portfolio_id: str,
        task_id: str,
        actor: PrincipalIdentity,
        now: datetime,
        notes: str,
    ) -> None:
        rows = connection.execute(
            f"SELECT * FROM {self._HELP_TABLE} WHERE portfolio_id = ? "
            "AND mandate_id = ? AND task_id = ? AND tenant_id = ? "
            "AND workspace_id = ?",
            (
                portfolio_id,
                mandate_id,
                task_id,
                actor.tenant_id,
                actor.workspace_id,
            ),
        ).fetchall()
        for row in rows:
            current = OutcomePortfolioHelpRequest.model_validate_json(
                str(row["payload"])
            )
            if not current.is_open:
                continue
            response = SrlHelpResponse(
                help_request_id=current.help_request_id,
                responded_at=now,
                responder_principal_id=actor.principal_id,
                response_kind=SrlHelpResponseKind.CANCELLATION,
                notes=notes,
            )
            self._write_help_response(connection, current, response)
