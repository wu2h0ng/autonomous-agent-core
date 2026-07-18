from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from agent_os_contracts import (
    Goal,
    MandateResponsibilityView,
    MandateResponsibilityViewStatus,
    MandateOperationalStatus,
    MandateStatus,
    MandateTaskLink,
    MandateTaskLinkCommand,
    MandateTaskLinkRevocation,
    MandateTaskLinkRevocationCommand,
    MandateWorkspaceRecord,
    ObservedOutcome,
    OutcomeStatus,
    PrincipalIdentity,
    PrincipalRole,
    RatifiedMandateRef,
    ResponsibilityActivePerceptionSummary,
    ResponsibilityAttentionReason,
    ResponsibilityItem,
    ResponsibilityItemState,
    RunStatus,
    TaskEvent,
    TaskEventType,
    TaskStatus,
    canonical_json,
    content_digest,
)

from .task_aggregate import TaskAggregate
from .task_service import expected_outcome_contract_error


class MandateResponsibilityDenied(PermissionError):
    pass


class MandateResponsibilityNotFound(LookupError):
    pass


class MandateResponsibilityConflict(RuntimeError):
    pass


class MandateResponsibilityPersistenceConflict(RuntimeError):
    pass


class ResponsibilityTaskReader(Protocol):
    def get_task(self, task_id: str) -> TaskAggregate: ...

    def current_outcome(self, task_id: str) -> ObservedOutcome | None: ...


class _SQLiteMandateResponsibilitySchema:
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


class MandateResponsibilityProjector:
    """Live read projection over canonical Mandate, Task and outcome truth."""

    def __init__(
        self,
        store: SQLiteMandateResponsibilityStore,
        task_service: ResponsibilityTaskReader,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._tasks = task_service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def classify(
        aggregate: TaskAggregate,
        current_outcome: ObservedOutcome | None,
        *,
        computed_at: datetime,
        completed_at: datetime | None,
    ) -> tuple[ResponsibilityItemState, tuple[ResponsibilityAttentionReason, ...]]:
        status = aggregate.status
        expected = aggregate.expected_outcome
        commitment = aggregate.commitment
        run = aggregate.run
        if status is None or aggregate.goal is None:
            return (
                ResponsibilityItemState.UNKNOWN,
                (ResponsibilityAttentionReason.TASK_SOURCE_MALFORMED,),
            )
        if expected is not None and expected_outcome_contract_error(expected) is not None:
            return (
                ResponsibilityItemState.UNKNOWN,
                (ResponsibilityAttentionReason.UNSUPPORTED_EVALUATOR,),
            )
        if current_outcome is not None and expected is not None and (
            current_outcome.task_id != aggregate.task_id
            or current_outcome.expected_outcome_id != expected.expected_outcome_id
            or current_outcome.tenant_id != expected.tenant_id
            or current_outcome.workspace_id != expected.workspace_id
            or current_outcome.evaluator_type != expected.evaluator_type
            or current_outcome.evaluator_version != expected.evaluator_version
        ):
            return (
                ResponsibilityItemState.UNKNOWN,
                (ResponsibilityAttentionReason.TASK_SOURCE_MALFORMED,),
            )

        reasons: set[ResponsibilityAttentionReason] = set()
        if current_outcome is not None:
            outcome_reason = {
                OutcomeStatus.NOT_MET: ResponsibilityAttentionReason.OUTCOME_NOT_MET,
                OutcomeStatus.UNRESOLVED: ResponsibilityAttentionReason.OUTCOME_UNRESOLVED,
                OutcomeStatus.INVALID: ResponsibilityAttentionReason.OUTCOME_INVALID,
            }.get(current_outcome.status)
            if outcome_reason is not None:
                reasons.add(outcome_reason)
        task_reason = {
            TaskStatus.FAILED: ResponsibilityAttentionReason.TASK_FAILED,
            TaskStatus.CANCELLED: ResponsibilityAttentionReason.TASK_CANCELLED,
            TaskStatus.PAUSED: ResponsibilityAttentionReason.TASK_PAUSED,
        }.get(status)
        if task_reason is not None:
            reasons.add(task_reason)
        if reasons:
            return (
                ResponsibilityItemState.NEEDS_ATTENTION,
                tuple(sorted(reasons, key=lambda item: item.value)),
            )

        if status is TaskStatus.WAITING:
            if run is None:
                return (
                    ResponsibilityItemState.UNKNOWN,
                    (ResponsibilityAttentionReason.WAIT_CONDITION_MISSING,),
                )
            if run.status is RunStatus.WAITING_APPROVAL:
                return (
                    ResponsibilityItemState.NEEDS_ATTENTION,
                    (ResponsibilityAttentionReason.WAITING_APPROVAL,),
                )
            if run.status is RunStatus.WAITING_EVENT:
                if run.wait_condition is None:
                    return (
                        ResponsibilityItemState.UNKNOWN,
                        (ResponsibilityAttentionReason.WAIT_CONDITION_MISSING,),
                    )
                if computed_at >= run.wait_condition.deadline:
                    return (
                        ResponsibilityItemState.NEEDS_ATTENTION,
                        (ResponsibilityAttentionReason.WAIT_DEADLINE_ARRIVED,),
                    )
                return ResponsibilityItemState.TRACKED, ()
            return (
                ResponsibilityItemState.UNKNOWN,
                (ResponsibilityAttentionReason.UNHANDLED_TASK_RUN_STATE,),
            )

        completed_and_current = (
            status is TaskStatus.COMPLETED
            and current_outcome is not None
            and current_outcome.status is OutcomeStatus.VERIFIED
            and completed_at is not None
            and commitment is not None
            and completed_at <= commitment.expires_at
        )
        if (
            commitment is not None
            and computed_at >= commitment.expires_at
            and not completed_and_current
        ):
            reasons.add(ResponsibilityAttentionReason.COMMITMENT_EXPIRED)

        if status is TaskStatus.COMPLETED:
            if current_outcome is None:
                reasons.add(ResponsibilityAttentionReason.TERMINAL_WITHOUT_OUTCOME)
            elif current_outcome.status is OutcomeStatus.VERIFIED:
                if completed_at is None or commitment is None:
                    return (
                        ResponsibilityItemState.UNKNOWN,
                        (ResponsibilityAttentionReason.TASK_SOURCE_MALFORMED,),
                    )
                if completed_at <= commitment.expires_at:
                    return ResponsibilityItemState.DONE_VERIFIED, ()
                reasons.add(ResponsibilityAttentionReason.COMMITMENT_EXPIRED)
        if reasons:
            return (
                ResponsibilityItemState.NEEDS_ATTENTION,
                tuple(sorted(reasons, key=lambda item: item.value)),
            )

        allowed = {
            TaskStatus.DRAFT: {None},
            TaskStatus.COMMITTED: {None},
            TaskStatus.RUNNING: {
                RunStatus.CREATED,
                RunStatus.QUEUED,
                RunStatus.RUNNING,
            },
            TaskStatus.VERIFYING: {
                RunStatus.RUNNING,
                RunStatus.VERIFYING,
                RunStatus.SUCCEEDED,
            },
        }
        run_status = None if run is None else run.status
        if status in allowed and run_status in allowed[status]:
            return ResponsibilityItemState.TRACKED, ()
        return (
            ResponsibilityItemState.UNKNOWN,
            (ResponsibilityAttentionReason.UNHANDLED_TASK_RUN_STATE,),
        )

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp is not timezone-aware")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _raw_schedule_fingerprint(rows: tuple[sqlite3.Row, ...]) -> str:
        return content_digest(
            {
                "rows": [
                    {key: row[key] for key in row.keys()}
                    for row in rows
                ]
            }
        )

    def _read_schedule(
        self,
        connection: sqlite3.Connection,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        mandate_id: str,
    ) -> tuple[
        ResponsibilityActivePerceptionSummary | None,
        tuple[ResponsibilityAttentionReason, ...],
        str,
    ]:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'mandate_active_perception_schedule'"
        ).fetchone()
        if exists is None:
            return None, (), content_digest({"rows": []})
        rows = tuple(
            connection.execute(
                "SELECT * FROM mandate_active_perception_schedule "
                "WHERE principal_id = ? AND tenant_id = ? "
                "AND workspace_id = ? AND mandate_id = ? ORDER BY schedule_id",
                (principal_id, tenant_id, workspace_id, mandate_id),
            ).fetchall()
        )
        fingerprint = self._raw_schedule_fingerprint(rows)
        if not rows:
            return None, (), fingerprint
        if len(rows) != 1:
            return (
                None,
                (ResponsibilityAttentionReason.SCHEDULE_SOURCE_MALFORMED,),
                fingerprint,
            )
        row = rows[0]
        try:
            integer_names = (
                "interval_seconds",
                "budget_window_seconds",
                "wake_budget_per_window",
                "query_budget_per_window",
                "feed_limit",
                "lease_seconds",
                "wake_used",
                "query_used",
                "lease_fence",
            )
            integers = {name: row[name] for name in integer_names}
            if any(type(value) is not int or value < 0 for value in integers.values()):
                raise ValueError("schedule integer is invalid")
            if (
                integers["interval_seconds"] < 1
                or integers["budget_window_seconds"] < integers["interval_seconds"]
                or integers["wake_budget_per_window"] < 1
                or integers["query_budget_per_window"] < 1
                or not 1 <= integers["feed_limit"] <= 100
                or integers["lease_seconds"] < 1
            ):
                raise ValueError("schedule bounds are invalid")
            config_payload = {
                key: row[key]
                for key in (
                    "schedule_id",
                    "principal_id",
                    "tenant_id",
                    "workspace_id",
                    "mandate_id",
                    "environment_binding_id",
                    "interval_seconds",
                    "budget_window_seconds",
                    "wake_budget_per_window",
                    "query_budget_per_window",
                    "feed_limit",
                    "lease_seconds",
                )
            }
            if content_digest(config_payload) != str(row["config_digest"]):
                raise ValueError("schedule config digest is invalid")
            next_wake = self._parse_timestamp(row["next_wake_at"])
            self._parse_timestamp(row["window_started_at"])
            lease_owner = row["lease_owner"]
            lease_expires = row["lease_expires_at"]
            if (lease_owner is None) != (lease_expires is None):
                raise ValueError("schedule lease binding is invalid")
            if lease_expires is not None:
                self._parse_timestamp(lease_expires)
            summary = ResponsibilityActivePerceptionSummary(
                schedule_digest=fingerprint,
                schedule_status="LEASE_HELD" if lease_owner is not None else "SCHEDULED",
                next_observation_at=next_wake,
            )
        except Exception:
            return (
                None,
                (ResponsibilityAttentionReason.SCHEDULE_SOURCE_MALFORMED,),
                fingerprint,
            )
        return summary, (), fingerprint

    def _read_active_links(
        self,
        connection: sqlite3.Connection,
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        mandate_id: str,
    ) -> tuple[tuple[MandateTaskLink, ...], str]:
        link_rows = connection.execute(
            f"SELECT * FROM {self._store._LINK_TABLE} "
            "WHERE principal_id = ? AND tenant_id = ? "
            "AND workspace_id = ? AND mandate_id = ? ORDER BY rowid",
            (principal_id, tenant_id, workspace_id, mandate_id),
        ).fetchall()
        links = tuple(self._store._decode_link(row) for row in link_rows)
        revocations = self._store._validated_revocations_for_links(
            connection,
            links,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            mandate_id=mandate_id,
        )
        revoked_link_ids = {revocation.link_id for revocation in revocations}
        active_links = tuple(
            link for link in links if link.link_id not in revoked_link_ids
        )
        associations = [link.association_id for link in active_links]
        if len(associations) != len(set(associations)):
            raise MandateResponsibilityPersistenceConflict(
                "multiple active links exist for one responsibility association"
            )
        source_digest = content_digest(
            {
                "links": tuple(
                    (link.link_id, link.record_digest) for link in links
                ),
                "revocations": tuple(
                    (
                        revocation.revocation_id,
                        revocation.link_id,
                        revocation.record_digest,
                    )
                    for revocation in revocations
                ),
            }
        )
        return active_links, source_digest

    @staticmethod
    def _task_event_source_digest(
        connection: sqlite3.Connection,
        task_id: str,
    ) -> str:
        rows = connection.execute(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY sequence",
            (task_id,),
        ).fetchall()
        return content_digest(
            {
                "events": tuple(
                    {key: row[key] for key in row.keys()} for row in rows
                )
            }
        )

    def _project_link(
        self,
        link: MandateTaskLink,
        *,
        operational: RatifiedMandateRef,
        computed_at: datetime,
    ) -> ResponsibilityItem:
        if link.correction_epoch != operational.correction_epoch:
            return ResponsibilityItem(
                link=link,
                task_status=None,
                run_status=None,
                state=ResponsibilityItemState.UNKNOWN,
                attention_reasons=(
                    ResponsibilityAttentionReason.MANDATE_CORRECTION_DRIFT,
                ),
            )
        connection = self._store._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM task_events WHERE task_id = ? ORDER BY sequence",
                (link.task_id,),
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            return ResponsibilityItem(
                link=link,
                task_status=None,
                run_status=None,
                state=ResponsibilityItemState.UNKNOWN,
                attention_reasons=(ResponsibilityAttentionReason.TASK_SOURCE_MISSING,),
            )
        try:
            events = tuple(TaskEvent.model_validate(dict(row)) for row in rows)
            raw_aggregate = TaskAggregate.rehydrate(events)
        except Exception:
            return ResponsibilityItem(
                link=link,
                task_status=None,
                run_status=None,
                state=ResponsibilityItemState.UNKNOWN,
                attention_reasons=(ResponsibilityAttentionReason.TASK_SOURCE_MALFORMED,),
            )
        created_digest = content_digest(events[0])
        if created_digest != link.task_created_event_digest:
            return ResponsibilityItem(
                link=link,
                task_status=None,
                run_status=None,
                state=ResponsibilityItemState.UNKNOWN,
                attention_reasons=(ResponsibilityAttentionReason.TASK_IDENTITY_CHANGED,),
                task_event_position=events[-1].sequence,
                task_event_head_digest=content_digest(events[-1]),
            )
        try:
            aggregate = self._tasks.get_task(link.task_id)
            if aggregate != raw_aggregate:
                raise ValueError("Task reader disagrees with canonical event stream")
            current_outcome = self._tasks.current_outcome(link.task_id)
        except Exception:
            return ResponsibilityItem(
                link=link,
                task_status=None,
                run_status=None,
                state=ResponsibilityItemState.UNKNOWN,
                attention_reasons=(ResponsibilityAttentionReason.TASK_SOURCE_MALFORMED,),
                task_event_position=events[-1].sequence,
                task_event_head_digest=content_digest(events[-1]),
            )
        completed_at = next(
            (
                event.occurred_at
                for event in reversed(events)
                if event.event_type is TaskEventType.RUN_SUCCEEDED
            ),
            None,
        )
        state, reasons = self.classify(
            aggregate,
            current_outcome,
            computed_at=computed_at,
            completed_at=completed_at,
        )
        historical_digest = (
            None
            if aggregate.observed_outcome is None
            else content_digest(aggregate.observed_outcome)
        )
        if aggregate.observed_outcome is None and current_outcome is None:
            validation_status = "NO_OUTCOME"
            validation_reason = None
        elif current_outcome == aggregate.observed_outcome:
            validation_status = "CURRENT_TRUSTED"
            validation_reason = None
        else:
            validation_status = (
                "CURRENT_DEMOTED:" + current_outcome.status.value
                if current_outcome is not None
                else "CURRENT_MISSING"
            )
            validation_reason = (
                None
                if current_outcome is None
                else ";".join(current_outcome.unresolved_gaps) or None
            )
        return ResponsibilityItem(
            link=link,
            goal=aggregate.goal,
            commitment=aggregate.commitment,
            expected_outcome=aggregate.expected_outcome,
            current_outcome=current_outcome,
            task_status=aggregate.status,
            run_status=None if aggregate.run is None else aggregate.run.status,
            wait_condition=None if aggregate.run is None else aggregate.run.wait_condition,
            state=state,
            attention_reasons=reasons,
            task_event_position=events[-1].sequence,
            task_event_head_digest=content_digest(events[-1]),
            historical_outcome_digest=historical_digest,
            outcome_validation_status=validation_status,
            outcome_validation_reason=validation_reason,
            completed_at=completed_at,
        )

    @staticmethod
    def _view_digest(
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        mandate_id: str,
        mandate_status: MandateOperationalStatus,
        desired_outcomes: tuple[str, ...],
        status: MandateResponsibilityViewStatus,
        items: tuple[ResponsibilityItem, ...],
        active_perception: ResponsibilityActivePerceptionSummary | None,
        global_gaps: tuple[ResponsibilityAttentionReason, ...],
        workspace_record_digest: str,
        operational_mandate_ref_digest: str,
        schedule_source_digest: str,
    ) -> str:
        stable_items = tuple(
            item.model_dump(mode="json", exclude={"current_outcome"}) for item in items
        )
        return content_digest(
            {
                "principal_id": principal_id,
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "mandate_id": mandate_id,
                "mandate_status": mandate_status.value,
                "desired_outcomes": desired_outcomes,
                "status": status.value,
                "items": stable_items,
                "active_perception": (
                    None
                    if active_perception is None
                    else active_perception.model_dump(mode="json")
                ),
                "global_gaps": tuple(reason.value for reason in global_gaps),
                "workspace_record_digest": workspace_record_digest,
                "operational_mandate_ref_digest": operational_mandate_ref_digest,
                "schedule_source_digest": schedule_source_digest,
            }
        )

    def project(
        self,
        mandate_id: str,
        reader: PrincipalIdentity,
    ) -> MandateResponsibilityView:
        computed_at = self._clock()
        connection = self._store._connect()
        try:
            workspace, workspace_digest, operational, operational_digest = (
                self._store._read_authority(
                    connection,
                    mandate_id,
                    reader,
                    require_admin=False,
                    require_active=False,
                    now=computed_at,
                )
            )
            if (
                computed_at < operational.valid_from
                or computed_at >= operational.expires_at
            ):
                raise MandateResponsibilityDenied(
                    "operational Mandate is not active at projection time"
                )
            links, responsibility_source_digest = self._read_active_links(
                connection,
                principal_id=workspace.mandate.principal_id,
                tenant_id=reader.tenant_id,
                workspace_id=reader.workspace_id,
                mandate_id=mandate_id,
            )
            task_source_digests = {
                link.link_id: self._task_event_source_digest(
                    connection, link.task_id
                )
                for link in links
            }
            active_perception, schedule_gaps, schedule_digest = self._read_schedule(
                connection,
                principal_id=workspace.mandate.principal_id,
                tenant_id=reader.tenant_id,
                workspace_id=reader.workspace_id,
                mandate_id=mandate_id,
            )
        finally:
            connection.close()
        items = tuple(
            self._project_link(
                link,
                operational=operational,
                computed_at=computed_at,
            )
            for link in links
        )

        final_connection = self._store._connect()
        try:
            (
                final_workspace,
                final_workspace_digest,
                final_operational,
                final_operational_digest,
            ) = self._store._read_authority(
                final_connection,
                mandate_id,
                reader,
                require_admin=False,
                require_active=False,
                now=computed_at,
            )
            final_schedule, final_schedule_gaps, final_schedule_digest = (
                self._read_schedule(
                    final_connection,
                    principal_id=final_workspace.mandate.principal_id,
                    tenant_id=reader.tenant_id,
                    workspace_id=reader.workspace_id,
                    mandate_id=mandate_id,
                )
            )
            final_links, final_responsibility_source_digest = (
                self._read_active_links(
                    final_connection,
                    principal_id=final_workspace.mandate.principal_id,
                    tenant_id=reader.tenant_id,
                    workspace_id=reader.workspace_id,
                    mandate_id=mandate_id,
                )
            )
            final_task_source_digests = {
                link.link_id: self._task_event_source_digest(
                    final_connection, link.task_id
                )
                for link in links
            }
        except MandateResponsibilityPersistenceConflict:
            raise MandateResponsibilityPersistenceConflict(
                "responsibility source changed during projection"
            ) from None
        finally:
            final_connection.close()
        if (
            final_workspace_digest != workspace_digest
            or final_workspace != workspace
            or final_operational_digest != operational_digest
            or final_operational != operational
            or final_links != links
            or final_responsibility_source_digest != responsibility_source_digest
            or final_task_source_digests != task_source_digests
        ):
            raise MandateResponsibilityPersistenceConflict(
                "responsibility source changed during projection"
            )
        if final_schedule_digest != schedule_digest:
            active_perception = None
            schedule_gaps = (
                ResponsibilityAttentionReason.SCHEDULE_SOURCE_MALFORMED,
            )
            schedule_digest = content_digest(
                {
                    "drifted_from": schedule_digest,
                    "drifted_to": final_schedule_digest,
                }
            )
        else:
            active_perception = final_schedule
            schedule_gaps = final_schedule_gaps
        global_gaps = tuple(sorted(set(schedule_gaps), key=lambda item: item.value))
        if operational.status is MandateOperationalStatus.REVOKED:
            view_status = MandateResponsibilityViewStatus.REVOKED
        elif global_gaps or any(
            item.state is ResponsibilityItemState.UNKNOWN for item in items
        ):
            view_status = MandateResponsibilityViewStatus.PARTIAL_UNKNOWN
        else:
            view_status = MandateResponsibilityViewStatus.COMPLETE
        desired_outcomes = tuple(sorted(set(workspace.mandate.desired_outcomes)))
        view_digest = self._view_digest(
            principal_id=workspace.mandate.principal_id,
            tenant_id=reader.tenant_id,
            workspace_id=reader.workspace_id,
            mandate_id=mandate_id,
            mandate_status=operational.status,
            desired_outcomes=desired_outcomes,
            status=view_status,
            items=items,
            active_perception=active_perception,
            global_gaps=global_gaps,
            workspace_record_digest=workspace_digest,
            operational_mandate_ref_digest=operational_digest,
            schedule_source_digest=schedule_digest,
        )
        return MandateResponsibilityView(
            principal_id=workspace.mandate.principal_id,
            tenant_id=reader.tenant_id,
            workspace_id=reader.workspace_id,
            mandate_id=mandate_id,
            mandate_status=operational.status,
            desired_outcomes=desired_outcomes,
            status=view_status,
            items=items,
            active_perception=active_perception,
            global_gaps=global_gaps,
            workspace_record_digest=workspace_digest,
            operational_mandate_ref_digest=operational_digest,
            schedule_source_digest=schedule_digest,
            computed_at=computed_at,
            view_digest=view_digest,
        )


class SQLiteMandateResponsibilityStore(_SQLiteMandateResponsibilitySchema):
    """Append-only store plus exact canonical-source validation."""

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

    def _validated_revocations_for_links(
        self,
        connection: sqlite3.Connection,
        links: tuple[MandateTaskLink, ...],
        *,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        mandate_id: str,
    ) -> tuple[MandateTaskLinkRevocation, ...]:
        scope_clause = (
            "principal_id = ? AND tenant_id = ? AND workspace_id = ? "
            "AND mandate_id = ?"
        )
        scope_values = (principal_id, tenant_id, workspace_id, mandate_id)
        if links:
            placeholders = ",".join("?" for _ in links)
            rows = connection.execute(
                f"SELECT * FROM {self._REVOCATION_TABLE} "
                f"WHERE link_id IN ({placeholders}) OR ({scope_clause}) "
                "ORDER BY rowid",
                (*(link.link_id for link in links), *scope_values),
            ).fetchall()
        else:
            rows = connection.execute(
                f"SELECT * FROM {self._REVOCATION_TABLE} "
                f"WHERE {scope_clause} ORDER BY rowid",
                scope_values,
            ).fetchall()
        revocations = tuple(self._decode_revocation(row) for row in rows)
        links_by_id = {link.link_id: link for link in links}
        for revocation in revocations:
            link = links_by_id.get(revocation.link_id)
            if link is None or (
                revocation.association_id != link.association_id
                or revocation.link_record_digest != link.record_digest
                or revocation.principal_id != link.principal_id
                or revocation.tenant_id != link.tenant_id
                or revocation.workspace_id != link.workspace_id
                or revocation.mandate_id != link.mandate_id
                or revocation.task_id != link.task_id
                or revocation.correction_epoch != link.correction_epoch
            ):
                raise MandateResponsibilityPersistenceConflict(
                    "durable responsibility revocation scope binding is invalid"
                )
        return revocations

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
            revocations = self._validated_revocations_for_links(
                connection,
                links,
                principal_id=workspace.mandate.principal_id,
                tenant_id=reader.tenant_id,
                workspace_id=reader.workspace_id,
                mandate_id=mandate_id,
            )
            if include_revoked:
                return links
            revoked = {revocation.link_id for revocation in revocations}
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
