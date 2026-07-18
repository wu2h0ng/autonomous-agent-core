from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from agent_os_contracts import (
    ObservedOutcome,
    OutcomePortfolio,
    OutcomePortfolioCreateCommand,
    OutcomePortfolioView,
    OutcomeStatus,
    PersistentCommitment,
    PersistentCommitmentAttachCommand,
    PersistentCommitmentState,
    PrincipalIdentity,
    SettlementCommand,
    SettlementRecord,
    content_digest,
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
            return OutcomePortfolioView(
                portfolio=portfolio,
                commitments=commitments,
                settlements=settlements,
            )
        finally:
            connection.close()

    def attach_commitment(
        self,
        command: PersistentCommitmentAttachCommand,
        mandate_id: str,
        actor: PrincipalIdentity,
    ) -> PersistentCommitment:
        if self._task_reader is None:
            raise MandateOutcomePortfolioDenied("task reader is required")
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
            portfolio = self._require_portfolio(
                connection, mandate_id, actor, workspace_digest, operational_digest
            )
            task = self._task_reader.get_task(command.task_id)
            commitment = task.commitment
            expected = task.expected_outcome
            if commitment is None or expected is None:
                raise MandateOutcomePortfolioDenied(
                    "Task Commitment and ExpectedOutcome are required"
                )
            if (
                content_digest(commitment) != command.commitment_digest
                or content_digest(expected) != command.expected_outcome_digest
            ):
                raise MandateOutcomePortfolioDenied(
                    "commitment digests do not match Task truth"
                )
            if (
                expected.tenant_id != actor.tenant_id
                or expected.workspace_id != actor.workspace_id
                or expected.task_id != command.task_id
            ):
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
        try:
            connection.execute("BEGIN IMMEDIATE")
            _, workspace_digest, _, operational_digest = self._read_authority(
                connection,
                mandate_id,
                actor,
                require_admin=True,
                require_active=True,
                now=now,
            )
            portfolio = self._require_portfolio(
                connection, mandate_id, actor, workspace_digest, operational_digest
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
            if commitment.state is not PersistentCommitmentState.OPEN:
                raise MandateOutcomePortfolioConflict(
                    "commitment is not open for settlement"
                )
            if commitment.expected_outcome_digest != command.expected_outcome_digest:
                raise MandateOutcomePortfolioDenied(
                    "expected outcome digest drift prevents settlement"
                )
            current = self._task_reader.current_outcome(commitment.task_id)
            if current is None:
                raise MandateOutcomePortfolioDenied(
                    "Task current ObservedOutcome is required"
                )
            if content_digest(current) != command.observed_outcome_digest:
                raise MandateOutcomePortfolioDenied(
                    "observed outcome digest does not match Task current outcome"
                )
            if current.status is not command.observed_status:
                raise MandateOutcomePortfolioDenied(
                    "observed status does not match Task current outcome"
                )
            task = self._task_reader.get_task(commitment.task_id)
            if task.expected_outcome is None or content_digest(
                task.expected_outcome
            ) != command.expected_outcome_digest:
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
            connection.commit()
            return settlement
        except Exception:
            connection.rollback()
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
    ) -> OutcomePortfolio:
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
            raise MandateOutcomePortfolioDenied("portfolio authority digest drift")
        return portfolio
