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
from agent_os_contracts.evidence import Sha256Digest

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

        selected = tuple(
            event
            for event in stream
            if event.sequence <= run_event.sequence
            and (event.event_type in _SETUP_EVENTS or event is run_event)
            or event.sequence > run_event.sequence
            and event.correlation_id == run_id
        )
        if not selected:
            raise EventStreamError("trajectory selected no events")
        self._validate_scopes(
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
        self._validate_correction_epoch_use(selected, correction_epoch)

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
            source_stream_last_sequence=selected[-1].sequence,
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
    def _validate_correction_epoch_use(
        events: tuple[TaskEvent, ...], current_epoch: int | None
    ) -> None:
        if current_epoch is None:
            return
        for event in events:
            payload = event.decoded_payload()
            vectors = _all_values(payload, "observed_correction_epochs")
            for value in vectors:
                vector = _mapping(value)
                task_epoch = vector.get("task_epoch")
                if isinstance(task_epoch, int) and task_epoch < current_epoch:
                    raise ScopeMismatchError(
                        "trajectory correction epoch regressed within the source stream"
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
    """Append-only credit evidence ledger; it has no policy/authority write port."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = RLock()
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS credit_assignments (
              credit_id TEXT PRIMARY KEY,
              assignment_json TEXT NOT NULL,
              assignment_digest TEXT NOT NULL UNIQUE
            )
            """
        )
        self._db.commit()

    def append(self, assignment: CreditAssignment) -> CreditAssignment:
        encoded = canonical_json(assignment)
        digest = content_digest(assignment)
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO credit_assignments"
                    "(credit_id, assignment_json, assignment_digest) VALUES (?, ?, ?)",
                    (assignment.credit_id, encoded, digest),
                )
                self._db.commit()
            except sqlite3.IntegrityError as exc:
                self._db.rollback()
                raise DuplicateEventError(
                    f"credit replay or overwrite rejected: {assignment.credit_id}"
                ) from exc
        return assignment

    def read(self, credit_id: str) -> CreditAssignment | None:
        with self._lock:
            row = self._db.execute(
                "SELECT assignment_json, assignment_digest "
                "FROM credit_assignments WHERE credit_id = ?",
                (credit_id,),
            ).fetchone()
        if row is None:
            return None
        return self._validated_row(row)

    def list_for_episode(
        self, episode_digest: Sha256Digest
    ) -> tuple[CreditAssignment, ...]:
        with self._lock:
            rows = self._db.execute(
                "SELECT assignment_json, assignment_digest "
                "FROM credit_assignments ORDER BY rowid"
            ).fetchall()
        assignments = tuple(self._validated_row(row) for row in rows)
        return tuple(
            item for item in assignments if item.episode_digest == episode_digest
        )

    @staticmethod
    def _validated_row(row: sqlite3.Row) -> CreditAssignment:
        assignment = CreditAssignment.model_validate_json(str(row["assignment_json"]))
        if content_digest(assignment) != str(row["assignment_digest"]):
            raise EventStreamError("credit ledger assignment digest mismatch")
        return assignment

    def close(self) -> None:
        with self._lock:
            self._db.close()
