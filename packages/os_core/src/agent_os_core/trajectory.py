from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from agent_os_contracts import (
    BindingStatus,
    CapabilityInvocationRef,
    CorrectionLink,
    CreditAssignment,
    EpisodeManifest,
    ModelInvocationRef,
    OutcomeLink,
    TaskEvent,
    TaskEventType,
    TrajectoryProjection,
    TrajectoryStep,
    WorkingSetRef,
    canonical_json,
    content_digest,
)
from .errors import DuplicateEventError, EventStreamError, ScopeMismatchError
from .event_store import TaskEventStore


_SETUP_EVENTS = {
    TaskEventType.TASK_CREATED,
    TaskEventType.TASK_COMMITTED,
    TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED,
}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _find_first(value: object, key: str) -> object | None:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        for nested in value.values():
            found = _find_first(nested, key)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_first(nested, key)
            if found is not None:
                return found
    return None


def _all_values(value: object, key: str) -> tuple[object, ...]:
    found: list[object] = []
    if isinstance(value, Mapping):
        if key in value:
            found.append(value[key])
        for nested in value.values():
            found.extend(_all_values(nested, key))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_all_values(nested, key))
    return tuple(found)


def _optional_str(value: object | None) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


class TrajectoryProjector:
    """Read-only deterministic projection of original TaskEvent truth.

    The projector never writes to the event store and never fills missing
    provider, model, policy, working-set, or correction bindings by inference.
    """

    def project(
        self, event_store: TaskEventStore, task_id: str, run_id: str
    ) -> TrajectoryProjection:
        stream = event_store.read(task_id)
        if not stream:
            raise EventStreamError("trajectory requires a non-empty task stream")
        run_event, run = self._find_run(stream, task_id, run_id)
        tenant_id = _optional_str(run.get("tenant_id"))
        workspace_id = _optional_str(run.get("workspace_id"))
        if tenant_id is None or workspace_id is None:
            raise ScopeMismatchError("run lacks tenant/workspace authority scope")

        selected = self._select_events(stream, run_event, task_id, run_id)
        if not selected:
            raise EventStreamError("trajectory selected no events")
        self._validate_scopes(
            selected,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        self._validate_truth_event_bindings(
            selected,
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )

        workflow_digest = _optional_str(run.get("workflow_digest"))
        if workflow_digest is None:
            workflow_digest = _optional_str(
                _find_first(run_event.decoded_payload(), "workflow_digest")
            )
        if workflow_digest is None:
            for event in selected:
                workflow_digest = _optional_str(
                    _find_first(event.decoded_payload(), "workflow_digest")
                )
                if workflow_digest is not None:
                    break
        policy_version = _optional_str(run.get("policy_version"))
        policy_digest = None
        for event in selected:
            policy_digest = _optional_str(
                _find_first(event.decoded_payload(), "policy_digest")
            )
            if policy_digest is not None:
                break
        working_set_ref = self._working_set_ref(selected)
        correction_epoch = self._correction_epoch(selected)
        self._validate_correction_epoch_use(selected)

        missing: list[str] = []
        if workflow_digest is None:
            missing.append("workflow_digest")
        if policy_version is None:
            missing.append("policy_version")
        if policy_digest is None:
            missing.append("policy_digest")
        if working_set_ref.status is BindingStatus.MISSING:
            missing.append("working_set_digest")
        if correction_epoch is None:
            missing.append("correction_epoch")

        steps: list[TrajectoryStep] = []
        outcomes: list[OutcomeLink] = []
        corrections: list[CorrectionLink] = []
        provider_profile_id = _optional_str(run.get("provider_profile_id"))
        for event in selected:
            payload = event.decoded_payload()
            step_id = f"step:{event.sequence}:{event.event_id}"
            prior_step_ids = tuple(step.step_id for step in steps)
            model_ref = self._model_ref(
                event, payload, provider_profile_id, working_set_ref
            )
            capability_ref = self._capability_ref(
                event, payload, policy_version, policy_digest
            )
            step = TrajectoryStep(
                step_id=step_id,
                sequence=event.sequence,
                source_event_id=event.event_id,
                event_type=event.event_type.value,
                event_digest=content_digest(event),
                occurred_at=event.occurred_at,
                model_invocation=model_ref,
                capability_invocation=capability_ref,
            )
            steps.append(step)
            if event.event_type is TaskEventType.OUTCOME_OBSERVED:
                outcome = _mapping(payload.get("outcome"))
                outcomes.append(
                    OutcomeLink(
                        outcome_id=_optional_str(outcome.get("observed_outcome_id"))
                        or f"unbound:{event.event_id}",
                        source_event_id=event.event_id,
                        status=_optional_str(outcome.get("status")) or "UNKNOWN",
                        linked_step_ids=prior_step_ids,
                        evidence_refs=tuple(
                            str(item)
                            for item in outcome.get("evidence_refs", ())
                            if isinstance(item, str) and item.strip()
                        ),
                    )
                )
            if event.event_type is TaskEventType.CORRECTION_WRITTEN:
                nested_correction = _mapping(payload.get("correction"))
                correction = nested_correction or payload
                epoch_value = correction.get("epoch")
                epoch = epoch_value if isinstance(epoch_value, int) else 0
                corrections.append(
                    CorrectionLink(
                        correction_id=_optional_str(correction.get("correction_id"))
                        or f"correction:{event.event_id}",
                        source_event_id=event.event_id,
                        epoch=epoch,
                        linked_step_ids=prior_step_ids,
                    )
                )

        manifest = EpisodeManifest(
            episode_id=f"episode:{task_id}:{run_id}",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            task_id=task_id,
            run_id=run_id,
            source_stream_last_sequence=stream[-1].sequence,
            workflow_digest=workflow_digest,
            workflow_status=(
                BindingStatus.BOUND
                if workflow_digest is not None
                else BindingStatus.MISSING
            ),
            policy_version=policy_version,
            policy_digest=policy_digest,
            policy_status=(
                BindingStatus.BOUND
                if policy_digest is not None
                else BindingStatus.MISSING
            ),
            working_set_ref=working_set_ref,
            correction_epoch=correction_epoch,
            correction_epoch_status=(
                BindingStatus.BOUND
                if correction_epoch is not None
                else BindingStatus.MISSING
            ),
            missing_bindings=tuple(missing),
        )
        digest_payload = {
            "manifest": manifest.model_dump(mode="json"),
            "steps": [step.model_dump(mode="json") for step in steps],
            "outcome_links": [item.model_dump(mode="json") for item in outcomes],
            "correction_links": [item.model_dump(mode="json") for item in corrections],
        }
        return TrajectoryProjection(
            manifest=manifest,
            steps=tuple(steps),
            outcome_links=tuple(outcomes),
            correction_links=tuple(corrections),
            trajectory_digest=content_digest(digest_payload),
        )

    @staticmethod
    def _select_events(
        stream: tuple[TaskEvent, ...],
        run_event: TaskEvent,
        task_id: str,
        run_id: str,
    ) -> tuple[TaskEvent, ...]:
        selected: list[TaskEvent] = []
        for event in stream:
            if event.sequence <= run_event.sequence:
                if event.event_type in _SETUP_EVENTS or event is run_event:
                    selected.append(event)
                continue
            if event.correlation_id == run_id:
                selected.append(event)
                continue
            if event.event_type in {
                TaskEventType.OUTCOME_OBSERVED,
                TaskEventType.CORRECTION_WRITTEN,
            }:
                raise ScopeMismatchError(
                    "relevant truth event has missing or mismatched correlation"
                )
        return tuple(selected)

    @staticmethod
    def _find_run(
        stream: tuple[TaskEvent, ...], task_id: str, run_id: str
    ) -> tuple[TaskEvent, Mapping[str, Any]]:
        for event in stream:
            if event.event_type is not TaskEventType.RUN_STARTED:
                continue
            run = _mapping(event.decoded_payload().get("run"))
            if run.get("run_id") == run_id:
                if run.get("task_id") != task_id:
                    raise ScopeMismatchError("run task scope mismatch")
                return event, run
        raise EventStreamError(f"run not found in task stream: {run_id}")

    @staticmethod
    def _validate_scopes(
        events: tuple[TaskEvent, ...],
        *,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> None:
        expected = {
            "task_id": task_id,
            "run_id": run_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }
        for event in events:
            payload = event.decoded_payload()
            for key, expected_value in expected.items():
                for actual in _all_values(payload, key):
                    if actual != expected_value:
                        raise ScopeMismatchError(
                            f"trajectory {key} scope mismatch in {event.event_id}"
                        )

    @staticmethod
    def _validate_truth_event_bindings(
        events: tuple[TaskEvent, ...],
        *,
        task_id: str,
        run_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> None:
        expected = {
            "task_id": task_id,
            "run_id": run_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
        }
        for event in events:
            if event.event_type is not TaskEventType.OUTCOME_OBSERVED:
                continue
            outcome = _mapping(event.decoded_payload().get("outcome"))
            if any(outcome.get(field) != value for field, value in expected.items()):
                raise ScopeMismatchError(
                    "outcome payload scope is missing or mismatched"
                )

    @staticmethod
    def _working_set_ref(events: tuple[TaskEvent, ...]) -> WorkingSetRef:
        for event in reversed(events):
            payload = event.decoded_payload()
            digest = _optional_str(_find_first(payload, "working_set_digest"))
            if digest is not None:
                identity = _optional_str(_find_first(payload, "working_set_id"))
                return WorkingSetRef(
                    status=BindingStatus.BOUND,
                    working_set_id=identity or f"digest:{digest}",
                    digest=digest,
                )
        return WorkingSetRef(
            status=BindingStatus.MISSING,
            gap_reason="no working-set digest exists in the source event stream",
        )

    @staticmethod
    def _correction_epoch(events: tuple[TaskEvent, ...]) -> int | None:
        epochs: list[int] = []
        for event in events:
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.CORRECTION_WRITTEN:
                value = _find_first(payload, "epoch")
                if isinstance(value, int) and value >= 0:
                    epochs.append(value)
        return max(epochs) if epochs else None

    @staticmethod
    def _validate_correction_epoch_use(events: tuple[TaskEvent, ...]) -> None:
        current: dict[str, int] = {}
        for event in events:
            payload = event.decoded_payload()
            if event.event_type is TaskEventType.CORRECTION_WRITTEN:
                correction = _mapping(payload.get("correction")) or payload
                scope = _optional_str(correction.get("scope")) or "TASK"
                epoch = correction.get("epoch")
                if not isinstance(epoch, int) or epoch < 0:
                    raise ScopeMismatchError(
                        "trajectory correction epoch is missing or invalid"
                    )
                previous = current.get(scope)
                if previous is not None and epoch < previous:
                    raise ScopeMismatchError(
                        "trajectory correction epoch regressed within the source stream"
                    )
                current[scope] = epoch
                continue
            vectors = _all_values(payload, "observed_correction_epochs")
            for value in vectors:
                vector = _mapping(value)
                for scope, field in (
                    ("TASK", "task_epoch"),
                    ("RUN", "run_epoch"),
                    ("CAPABILITY", "capability_epoch"),
                ):
                    expected = current.get(scope)
                    observed = vector.get(field)
                    if expected is not None and observed != expected:
                        raise ScopeMismatchError(
                            "trajectory correction epoch is stale or future-dated"
                        )

    @staticmethod
    def _model_ref(
        event: TaskEvent,
        payload: Mapping[str, Any],
        provider_profile_id: str | None,
        working_set_ref: WorkingSetRef,
    ) -> ModelInvocationRef | None:
        if event.event_type is not TaskEventType.PROVIDER_RESPONDED:
            return None
        missing: list[str] = []
        values: dict[str, str | None] = {}
        for field in (
            "provider_profile_digest",
            "provider_id",
            "model_id",
            "model_revision_digest",
            "request_digest",
            "invocation_binding_digest",
        ):
            value = _optional_str(_find_first(payload, field))
            values[field] = value
            if value is None:
                missing.append(field)
        if provider_profile_id is None:
            missing.append("provider_profile_id")
        if working_set_ref.status is BindingStatus.MISSING:
            missing.append("working_set_digest")
        return ModelInvocationRef(
            source_event_id=event.event_id,
            provider_profile_id=provider_profile_id,
            provider_profile_digest=values["provider_profile_digest"],
            provider_id=values["provider_id"],
            model_id=values["model_id"],
            model_revision_digest=values["model_revision_digest"],
            request_digest=values["request_digest"],
            response_digest=content_digest(payload),
            invocation_binding_digest=values["invocation_binding_digest"],
            working_set_ref=working_set_ref,
            missing_fields=tuple(missing),
        )

    @staticmethod
    def _capability_ref(
        event: TaskEvent,
        payload: Mapping[str, Any],
        policy_version: str | None,
        policy_digest: str | None,
    ) -> CapabilityInvocationRef | None:
        if event.event_type not in {
            TaskEventType.ACTION_PROPOSED,
            TaskEventType.ACTION_RECEIPT_RECORDED,
        }:
            return None
        missing: list[str] = []
        field_values: dict[str, str | None] = {}
        for field in (
            "capability_id",
            "capability_version",
            "capability_spec_digest",
            "action_id",
            "action_digest",
            "receipt_id",
        ):
            value = _optional_str(_find_first(payload, field))
            field_values[field] = value
            if value is None:
                missing.append(field)
        if policy_version is None:
            missing.append("policy_version")
        if policy_digest is None:
            missing.append("policy_digest")
        receipt = _find_first(payload, "receipt")
        return CapabilityInvocationRef(
            source_event_id=event.event_id,
            capability_id=field_values["capability_id"],
            capability_version=field_values["capability_version"],
            capability_spec_digest=field_values["capability_spec_digest"],
            action_id=field_values["action_id"],
            action_digest=field_values["action_digest"],
            receipt_id=field_values["receipt_id"],
            receipt_digest=(
                content_digest(_mapping(receipt)) if receipt is not None else None
            ),
            policy_version=policy_version,
            policy_digest=policy_digest,
            missing_fields=tuple(missing),
        )


class CreditLedger:
    """Projection-bound append-only credit ledger with scoped CAS and hash chain.

    This ledger records uncertain offline attribution only.  It intentionally
    exposes no policy, grant, evaluator, Task, or adaptation write port.
    """

    _GENESIS = "0" * 64

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = RLock()
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS credit_assignments (
              tenant_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              task_id TEXT NOT NULL,
              run_id TEXT NOT NULL,
              credit_id TEXT NOT NULL,
              sequence INTEGER NOT NULL UNIQUE,
              assignment_json TEXT NOT NULL,
              assignment_digest TEXT NOT NULL,
              previous_record_digest TEXT NOT NULL,
              record_digest TEXT NOT NULL UNIQUE,
              PRIMARY KEY (tenant_id, workspace_id, task_id, run_id, credit_id)
            );
            CREATE TABLE IF NOT EXISTS credit_ledger_head (
              singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
              record_count INTEGER NOT NULL,
              head_digest TEXT NOT NULL
            )
            """
        )
        self._db.execute(
            "INSERT OR IGNORE INTO credit_ledger_head"
            "(singleton, record_count, head_digest) VALUES (1, 0, ?)",
            (self._GENESIS,),
        )
        self._db.commit()

    def append(
        self,
        assignment: CreditAssignment,
        projection: TrajectoryProjection,
    ) -> CreditAssignment:
        assignment = CreditAssignment.model_validate(assignment.model_dump())
        self._validate_projection(projection)
        self._validate_assignment_binding(assignment, projection)
        encoded = canonical_json(assignment)
        digest = content_digest(assignment)
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                count, head = self._verify_chain_in_transaction()
                sequence = count + 1
                record_digest = content_digest(
                    {
                        "sequence": sequence,
                        "tenant_id": assignment.tenant_id,
                        "workspace_id": assignment.workspace_id,
                        "task_id": assignment.task_id,
                        "run_id": assignment.run_id,
                        "credit_id": assignment.credit_id,
                        "assignment_digest": digest,
                        "previous_record_digest": head,
                    }
                )
                self._db.execute(
                    "INSERT INTO credit_assignments"
                    "(tenant_id, workspace_id, task_id, run_id, credit_id, sequence, "
                    "assignment_json, assignment_digest, previous_record_digest, "
                    "record_digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        assignment.tenant_id,
                        assignment.workspace_id,
                        assignment.task_id,
                        assignment.run_id,
                        assignment.credit_id,
                        sequence,
                        encoded,
                        digest,
                        head,
                        record_digest,
                    ),
                )
                updated = self._db.execute(
                    "UPDATE credit_ledger_head SET record_count = ?, head_digest = ? "
                    "WHERE singleton = 1 AND record_count = ? AND head_digest = ?",
                    (sequence, record_digest, count, head),
                )
                if updated.rowcount != 1:
                    raise EventStreamError("credit ledger head CAS failed")
                self._db.commit()
            except sqlite3.IntegrityError as exc:
                self._db.rollback()
                raise DuplicateEventError(
                    f"credit replay or overwrite rejected: {assignment.credit_id}"
                ) from exc
            except Exception:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
        return assignment

    def read(
        self, credit_id: str, projection: TrajectoryProjection
    ) -> CreditAssignment | None:
        self._validate_projection(projection)
        manifest = projection.manifest
        with self._lock:
            self._verify_chain_in_transaction()
            row = self._db.execute(
                "SELECT assignment_json, assignment_digest "
                "FROM credit_assignments WHERE tenant_id = ? "
                "AND workspace_id = ? AND task_id = ? AND run_id = ? "
                "AND credit_id = ?",
                (
                    manifest.tenant_id,
                    manifest.workspace_id,
                    manifest.task_id,
                    manifest.run_id,
                    credit_id,
                ),
            ).fetchone()
        if row is None:
            return None
        assignment = self._validated_row(row)
        self._validate_assignment_binding(assignment, projection)
        return assignment

    def list_for_episode(
        self, projection: TrajectoryProjection
    ) -> tuple[CreditAssignment, ...]:
        self._validate_projection(projection)
        manifest = projection.manifest
        with self._lock:
            self._verify_chain_in_transaction()
            rows = self._db.execute(
                "SELECT assignment_json, assignment_digest "
                "FROM credit_assignments WHERE tenant_id = ? AND workspace_id = ? "
                "AND task_id = ? AND run_id = ? "
                "ORDER BY sequence",
                (
                    manifest.tenant_id,
                    manifest.workspace_id,
                    manifest.task_id,
                    manifest.run_id,
                ),
            ).fetchall()
        assignments = tuple(self._validated_row(row) for row in rows)
        selected = tuple(
            item
            for item in assignments
            if item.episode_digest == projection.trajectory_digest
        )
        for item in selected:
            self._validate_assignment_binding(item, projection)
        return selected

    @staticmethod
    def _validate_projection(projection: TrajectoryProjection) -> None:
        digest_payload = {
            "manifest": projection.manifest.model_dump(mode="json"),
            "steps": [step.model_dump(mode="json") for step in projection.steps],
            "outcome_links": [
                item.model_dump(mode="json") for item in projection.outcome_links
            ],
            "correction_links": [
                item.model_dump(mode="json") for item in projection.correction_links
            ],
        }
        if content_digest(digest_payload) != projection.trajectory_digest:
            raise EventStreamError("trajectory projection digest mismatch")

    @staticmethod
    def _validate_assignment_binding(
        assignment: CreditAssignment, projection: TrajectoryProjection
    ) -> None:
        manifest = projection.manifest
        expected = (
            (assignment.episode_digest, projection.trajectory_digest, "episode digest"),
            (assignment.tenant_id, manifest.tenant_id, "tenant"),
            (assignment.workspace_id, manifest.workspace_id, "workspace"),
            (assignment.task_id, manifest.task_id, "task"),
            (assignment.run_id, manifest.run_id, "run"),
        )
        for actual, trusted, label in expected:
            if actual != trusted:
                raise ScopeMismatchError(f"credit {label} binding mismatch")
        if manifest.correction_epoch is None:
            raise EventStreamError(
                "credit requires a projection with a bound correction epoch"
            )
        if assignment.correction_epoch != manifest.correction_epoch:
            raise ScopeMismatchError("credit correction epoch binding mismatch")
        step_ids = {step.step_id for step in projection.steps}
        if not set(assignment.target_step_ids).issubset(step_ids):
            raise EventStreamError("credit targets a step outside the projection")

    def _verify_chain_in_transaction(self) -> tuple[int, str]:
        head_row = self._db.execute(
            "SELECT record_count, head_digest FROM credit_ledger_head "
            "WHERE singleton = 1"
        ).fetchone()
        if head_row is None:
            raise EventStreamError("credit ledger head is missing")
        expected_previous = self._GENESIS
        expected_sequence = 1
        rows = self._db.execute(
            "SELECT tenant_id, workspace_id, task_id, run_id, credit_id, sequence, "
            "assignment_json, assignment_digest, previous_record_digest, record_digest "
            "FROM credit_assignments ORDER BY sequence"
        ).fetchall()
        for row in rows:
            if int(row["sequence"]) != expected_sequence:
                raise EventStreamError("credit ledger sequence gap")
            assignment = self._validated_row(row)
            if str(row["previous_record_digest"]) != expected_previous:
                raise EventStreamError("credit ledger hash-chain predecessor mismatch")
            expected_record = content_digest(
                {
                    "sequence": expected_sequence,
                    "tenant_id": str(row["tenant_id"]),
                    "workspace_id": str(row["workspace_id"]),
                    "task_id": str(row["task_id"]),
                    "run_id": str(row["run_id"]),
                    "credit_id": assignment.credit_id,
                    "assignment_digest": str(row["assignment_digest"]),
                    "previous_record_digest": expected_previous,
                }
            )
            if expected_record != str(row["record_digest"]):
                raise EventStreamError("credit ledger record digest mismatch")
            expected_previous = expected_record
            expected_sequence += 1
        count = expected_sequence - 1
        if int(head_row["record_count"]) != count:
            raise EventStreamError("credit ledger head count mismatch")
        if str(head_row["head_digest"]) != expected_previous:
            raise EventStreamError("credit ledger head digest mismatch")
        return count, expected_previous

    @staticmethod
    def _validated_row(row: sqlite3.Row) -> CreditAssignment:
        assignment = CreditAssignment.model_validate_json(str(row["assignment_json"]))
        if content_digest(assignment) != str(row["assignment_digest"]):
            raise EventStreamError("credit ledger assignment digest mismatch")
        return assignment

    def close(self) -> None:
        with self._lock:
            self._db.close()
