from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import Iterator, Protocol

from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    EnvironmentEvent,
    EnvironmentEventAdmissionReceipt,
    HelpRequest,
    LedgerAccessScope,
    OperationalProjectionRef,
    RatifiedMandateRef,
    SituatedAssessmentOutcomeKind,
    SituatedAssessmentRecord,
    SituatedEvaluationTrace,
    SituatedTraceReason,
    SituatedTraceStatus,
    TaskDraftProposal,
    TrustedWorkingSet,
    content_digest,
)

from .errors import SituationalPersistenceConflict, SituationalTrustDenied
from .situated import (
    OperationalProposalService,
    SituationalTrustResolver,
    situated_input_binding_digest,
)
from .situated_persistence import (
    ProposalResult,
    ScopedSituatedAssessmentReader,
    proposal_result,
)
from .srl_event_store import ScopedEventAdmissionReader


class _SituatedTraceWriterPort(Protocol):
    def begin_trace(self, trace: SituatedEvaluationTrace) -> SituatedEvaluationTrace: ...

    def increment_delegation_attempt(
        self, trace_id: str, *, recorded_at: datetime | None = None
    ) -> SituatedEvaluationTrace: ...

    def transition_trace(
        self, terminal: SituatedEvaluationTrace
    ) -> SituatedEvaluationTrace: ...


class _Flight:
    def __init__(self) -> None:
        self.lock = RLock()
        self.references = 0


_FLIGHTS_LOCK = Lock()
_FLIGHTS: dict[str, _Flight] = {}


@contextmanager
def _single_flight(trace_id: str) -> Iterator[None]:
    with _FLIGHTS_LOCK:
        flight = _FLIGHTS.setdefault(trace_id, _Flight())
        flight.references += 1
    try:
        with flight.lock:
            yield
    finally:
        with _FLIGHTS_LOCK:
            flight.references -= 1
            if flight.references == 0 and _FLIGHTS.get(trace_id) is flight:
                del _FLIGHTS[trace_id]


def _utc(value: datetime) -> datetime:
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            raise SituationalTrustDenied("steward time must be timezone-aware")
        return value.astimezone(timezone.utc)
    except (AttributeError, OverflowError, TypeError, ValueError):
        raise SituationalTrustDenied("steward time cannot be normalized") from None


def _trace_id(receipt: EnvironmentEventAdmissionReceipt, projection_id: str) -> str:
    digest = content_digest(
        {
            "admission_receipt_digest": receipt.receipt_digest,
            "projection_id": projection_id,
        }
    )
    return f"situated-evaluation:{digest}"


class MandateSteward:
    """Admission-required, proposal-only facade over situated assessment."""

    def __init__(
        self,
        *,
        trust: SituationalTrustResolver,
        authority: ScopedSituatedAssessmentReader,
        proposal_service: OperationalProposalService,
        admission_reader: ScopedEventAdmissionReader,
        trace_writer: _SituatedTraceWriterPort,
        principal_id: str,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not principal_id.strip():
            raise ValueError("principal_id must be nonempty")
        if (
            admission_reader.scope != authority.scope
            or admission_reader.scope.principal_id != principal_id
        ):
            raise ValueError("admission and assessment reader scope must match principal")
        self._trust = trust
        self._authority = authority
        self._proposal_service = proposal_service
        if type(proposal_service) is not OperationalProposalService:
            raise TypeError("steward requires the internal operational proposal service")
        self._working_set_authority = proposal_service
        self._admission_reader = admission_reader
        self._trace_writer = trace_writer
        self._principal_id = principal_id
        self._clock = clock
        self._monotonic = monotonic

    @property
    def scope(self) -> LedgerAccessScope:
        """Return the authenticated ledger scope bound at construction."""

        return self._authority.scope

    def observe_event(
        self,
        event_id: str,
        projection_id: str,
        admission_receipt_id: str,
    ) -> TaskDraftProposal | HelpRequest | None:
        now = _utc(self._clock())
        # Resolve every dependency-owned trust decision before touching either
        # durable ledger.  Unexpected adapter exceptions are translated to one
        # fixed sentinel and can neither leak their message nor mutate an
        # already-existing PENDING trace.
        try:
            event = self._trust.resolve_event(event_id)
            projection = self._trust.resolve_projection(projection_id)
        except Exception:
            raise SituationalTrustDenied(
                "situated trust dependency is unavailable"
            ) from None
        if event is None or projection is None:
            raise SituationalTrustDenied("admitted event or projection is unavailable")
        binding_tuple = (
            self._principal_id,
            event.tenant_id,
            event.workspace_id,
            event.mandate_id,
            event.environment_binding_id,
        )
        try:
            binding_authorized = self._trust.binding_is_authorized(binding_tuple)
        except Exception:
            raise SituationalTrustDenied(
                "situated trust dependency is unavailable"
            ) from None
        if not binding_authorized:
            raise SituationalTrustDenied("situated input binding is not authorized")
        receipt = self._admission_reader.by_receipt_id(admission_receipt_id)
        if receipt is None:
            raise SituationalTrustDenied("admitted event or projection is unavailable")
        if (
            receipt.receipt_id != admission_receipt_id
            or receipt.environment_event_id != event_id
            or event.environment_event_id != event_id
            or projection.projection_id != projection_id
        ):
            raise SituationalTrustDenied("admission, event, or projection identity conflicts")
        trace_id = _trace_id(receipt, projection_id)
        with _single_flight(trace_id):
            active_start = self._monotonic()
            existing_trace = self._admission_reader.by_trace_id(trace_id)
            try:
                mandate, binding = self._resolve_and_validate(
                    receipt, event, projection, evaluated_at=now
                )
            except SituationalTrustDenied:
                if (
                    existing_trace is not None
                    and existing_trace.status is SituatedTraceStatus.PENDING
                ):
                    self._deny_pending(existing_trace)
                raise
            working_set = self._working_set_authority.trusted_working_set(
                event_id,
                projection_id,
                admission_receipt_id=receipt.receipt_id,
                evaluated_at=now,
            )
            if working_set is not None:
                self._validate_working_set_anchors(
                    working_set, receipt, mandate, event
                )
            expected_digest = situated_input_binding_digest(
                mandate,
                binding,
                event,
                projection,
                mandate.relevance_assessor,
                working_set,
            )
            trace = existing_trace
            if trace is not None:
                self._validate_trace_binding(trace, receipt, event, projection)
                if trace.status is not SituatedTraceStatus.PENDING:
                    return self._terminal_result(trace, expected_digest)
            else:
                trace = self._trace_writer.begin_trace(
                    SituatedEvaluationTrace(
                        trace_id=trace_id,
                        admission_receipt_digest=receipt.receipt_digest,
                        event_id=event.environment_event_id,
                        projection_id=projection.projection_id,
                        mandate_id=mandate.mandate_id,
                        tenant_id=event.tenant_id,
                        workspace_id=event.workspace_id,
                        status=SituatedTraceStatus.PENDING,
                        reason=SituatedTraceReason.ASSESSMENT_PENDING,
                        result_binding_digest=None,
                        delegation_attempt_count=0,
                        committed_provider_call_attempted=None,
                        input_tokens=None,
                        output_tokens=None,
                        duration_ms=0,
                        recorded_at=now,
                    )
                )

            record = self._authority.record_by_input_binding(expected_digest)
            if record is not None:
                self._validate_record(
                    record,
                    mandate,
                    binding,
                    event,
                    projection,
                    working_set,
                    expected_digest,
                )
                return self._complete(trace, record, active_start=active_start)

            trace = self._trace_writer.increment_delegation_attempt(
                trace.trace_id, recorded_at=now
            )
            before_provider = self._monotonic()
            try:
                returned = self._proposal_service.propose(
                    event_id,
                    projection_id,
                    evaluated_at=now,
                    admission_receipt_id=receipt.receipt_id,
                )
            except (SituationalPersistenceConflict, SituationalTrustDenied):
                raise
            except Exception:
                raise SituationalPersistenceConflict(
                    "situated assessment delegation failed"
                ) from None
            after_provider = self._monotonic()
            record = self._authority.record_by_input_binding(expected_digest)
            if record is None:
                raise SituationalPersistenceConflict(
                    "proposal service returned without a persisted assessment"
                )
            self._validate_record(
                record,
                mandate,
                binding,
                event,
                projection,
                working_set,
                expected_digest,
            )
            persisted_result = proposal_result(record)
            if returned != persisted_result:
                raise SituationalPersistenceConflict(
                    "proposal result does not match persisted assessment"
                )
            current_trace = self._admission_reader.by_trace_id(trace.trace_id)
            if current_trace is None or current_trace.status is not SituatedTraceStatus.PENDING:
                raise SituationalPersistenceConflict("pending trace changed during delegation")
            try:
                current_mandate, current_binding = self._resolve_and_validate(
                    receipt, event, projection, evaluated_at=_utc(self._clock())
                )
            except SituationalTrustDenied:
                self._deny_pending(current_trace, record=record)
                raise
            if current_mandate != mandate or current_binding != binding:
                self._deny_pending(current_trace, record=record)
                raise SituationalTrustDenied("authority changed during situated assessment")
            active_ms = max(
                0,
                int(
                    (
                        (before_provider - active_start)
                        + (self._monotonic() - after_provider)
                    )
                    * 1000
                ),
            )
            return self._complete(
                current_trace, record, duration_ms=active_ms
            )

    def observe_event_record(
        self,
        event_id: str,
        projection_id: str,
        admission_receipt_id: str,
    ) -> SituatedAssessmentRecord:
        result = self.observe_event(event_id, projection_id, admission_receipt_id)
        receipt = self._admission_reader.by_receipt_id(admission_receipt_id)
        if receipt is None:
            raise SituationalPersistenceConflict(
                "completed situated assessment lacks admission receipt"
            )
        trace = self._admission_reader.by_trace_id(_trace_id(receipt, projection_id))
        if (
            trace is None
            or trace.status is not SituatedTraceStatus.COMPLETED
            or trace.result_binding_digest is None
        ):
            raise SituationalPersistenceConflict(
                "completed situated assessment lacks durable result binding"
            )
        record = self._authority.record_by_result_digest(trace.result_binding_digest)
        if record is None or proposal_result(record) != result:
            raise SituationalPersistenceConflict(
                "completed situated assessment result binding conflicts"
            )
        return record

    def _resolve_and_validate(
        self,
        receipt: EnvironmentEventAdmissionReceipt,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        *,
        evaluated_at: datetime,
    ) -> tuple[RatifiedMandateRef, EnvironmentBindingAuthorization]:
        if (
            receipt.event_digest != content_digest(event)
            or receipt.mandate_id != event.mandate_id
            or receipt.environment_binding_id != event.environment_binding_id
            or receipt.principal_id != self._principal_id
            or receipt.tenant_id != event.tenant_id
            or receipt.workspace_id != event.workspace_id
            or projection.mandate_id != event.mandate_id
            or projection.environment_binding_id != event.environment_binding_id
            or projection.tenant_id != event.tenant_id
            or projection.workspace_id != event.workspace_id
            or event.environment_event_id not in projection.source_event_ids
        ):
            raise SituationalTrustDenied("admission, event, and projection bindings conflict")
        mandate, binding = self._authority.resolve_active(
            event.mandate_id,
            event.environment_binding_id,
            evaluated_at=evaluated_at,
        )
        if (
            mandate.mandate_id != receipt.mandate_id
            or mandate.owner_principal_id != receipt.principal_id
            or mandate.tenant_id != receipt.tenant_id
            or mandate.workspace_id != receipt.workspace_id
            or mandate.correction_epoch != receipt.correction_epoch
            or binding.environment_binding_id != receipt.environment_binding_id
            or binding.version != receipt.environment_binding_version
            or binding.binding_digest != receipt.environment_binding_digest
        ):
            raise SituationalTrustDenied("current authority differs from admission receipt")
        return mandate, binding

    @staticmethod
    def _validate_trace_binding(
        trace: SituatedEvaluationTrace,
        receipt: EnvironmentEventAdmissionReceipt,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
    ) -> None:
        if (
            trace.admission_receipt_digest != receipt.receipt_digest
            or trace.event_id != event.environment_event_id
            or trace.projection_id != projection.projection_id
            or trace.mandate_id != event.mandate_id
            or trace.tenant_id != event.tenant_id
            or trace.workspace_id != event.workspace_id
        ):
            raise SituationalPersistenceConflict("situated trace binding conflicts")

    @staticmethod
    def _validate_record(
        record: SituatedAssessmentRecord,
        mandate: RatifiedMandateRef,
        binding: EnvironmentBindingAuthorization,
        event: EnvironmentEvent,
        projection: OperationalProjectionRef,
        working_set: TrustedWorkingSet | None,
        expected_digest: str,
    ) -> None:
        assessment = record.assessment
        exact = (
            assessment.input_binding_digest == expected_digest,
            assessment.mandate_id == mandate.mandate_id,
            assessment.mandate_version == mandate.version,
            assessment.mandate_digest == mandate.mandate_digest,
            assessment.correction_epoch == mandate.correction_epoch,
            assessment.environment_binding_id == binding.environment_binding_id,
            assessment.environment_binding_version == binding.version,
            assessment.environment_binding_digest == binding.binding_digest,
            assessment.assessor == mandate.relevance_assessor,
            assessment.environment_event_id == event.environment_event_id,
            assessment.event_observation_digest == event.observation.content_digest,
            assessment.projection_id == projection.projection_id,
            assessment.projection_digest == projection.projection_artifact.content_digest,
            assessment.input_binding_digest
            == situated_input_binding_digest(
                mandate,
                binding,
                event,
                projection,
                mandate.relevance_assessor,
                working_set,
            ),
            record.tenant_id == event.tenant_id,
            record.workspace_id == event.workspace_id,
        )
        if not all(exact):
            raise SituationalPersistenceConflict("persisted assessment binding conflicts")

    @staticmethod
    def _validate_working_set_anchors(
        working_set: TrustedWorkingSet,
        receipt: EnvironmentEventAdmissionReceipt,
        mandate: RatifiedMandateRef,
        event: EnvironmentEvent,
    ) -> None:
        request = working_set.request
        exact = (
            request.principal_id == receipt.principal_id,
            request.tenant_id == receipt.tenant_id == event.tenant_id,
            request.workspace_id == receipt.workspace_id == event.workspace_id,
            request.mandate_id == receipt.mandate_id == mandate.mandate_id,
            request.mandate_version == mandate.version,
            request.mandate_digest == mandate.mandate_digest,
            request.admission_receipt_id == receipt.receipt_id,
            request.admission_receipt_digest == receipt.receipt_digest,
            request.correction_epoch
            == receipt.correction_epoch
            == mandate.correction_epoch,
            request.relevance_policy_digest
            == mandate.relevance_assessor.policy_digest,
        )
        if not all(exact):
            raise SituationalTrustDenied(
                "working set mandatory anchors are unavailable or drifted"
            )

    def _terminal_result(
        self, trace: SituatedEvaluationTrace, expected_digest: str
    ) -> ProposalResult:
        if trace.status is SituatedTraceStatus.DENIED:
            raise SituationalTrustDenied(f"situated evaluation denied: {trace.reason.value}")
        record = self._authority.record_by_input_binding(expected_digest)
        if record is None or content_digest(record) != trace.result_binding_digest:
            raise SituationalPersistenceConflict("terminal trace result binding conflicts")
        return proposal_result(record)

    def _complete(
        self,
        pending: SituatedEvaluationTrace,
        record: SituatedAssessmentRecord,
        *,
        duration_ms: int | None = None,
        active_start: float | None = None,
    ) -> ProposalResult:
        if pending.status is not SituatedTraceStatus.PENDING:
            raise SituationalPersistenceConflict("only pending traces may complete")
        if duration_ms is None:
            started = self._monotonic() if active_start is None else active_start
            duration_ms = max(
                0,
                int((self._monotonic() - started) * 1000),
            )
        reason = {
            SituatedAssessmentOutcomeKind.TASK_DRAFT: SituatedTraceReason.TASK_DRAFT,
            SituatedAssessmentOutcomeKind.HELP_REQUEST: SituatedTraceReason.HELP_REQUEST,
            SituatedAssessmentOutcomeKind.NO_PROPOSAL: SituatedTraceReason.NO_PROPOSAL,
        }[record.outcome_kind]
        terminal = pending.model_copy(
            update={
                "status": SituatedTraceStatus.COMPLETED,
                "reason": reason,
                "result_binding_digest": content_digest(record),
                "committed_provider_call_attempted": record.assessment.provider_call_attempted,
                "input_tokens": None,
                "output_tokens": None,
                "duration_ms": duration_ms,
                "recorded_at": _utc(self._clock()),
            }
        )
        persisted = self._trace_writer.transition_trace(terminal)
        if persisted != terminal:
            raise SituationalPersistenceConflict("terminal trace write result conflicts")
        return proposal_result(record)

    def _deny_pending(
        self,
        pending: SituatedEvaluationTrace,
        *,
        record: SituatedAssessmentRecord | None = None,
    ) -> None:
        terminal = pending.model_copy(
            update={
                "status": SituatedTraceStatus.DENIED,
                "reason": SituatedTraceReason.AUTHORITY_CHANGED,
                "result_binding_digest": None,
                "committed_provider_call_attempted": (
                    record.assessment.provider_call_attempted
                    if record is not None
                    else None
                ),
                "input_tokens": None,
                "output_tokens": None,
                "recorded_at": _utc(self._clock()),
            }
        )
        self._trace_writer.transition_trace(terminal)


__all__ = ["MandateSteward"]
