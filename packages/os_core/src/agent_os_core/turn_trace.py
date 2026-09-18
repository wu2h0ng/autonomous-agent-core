"""Project one governed turn out of the durable Task event stream.

The durable task-event log is the truth spine: append-only, typed, per-task, and
the same records ``/task``, ``/export`` and the metrics pipeline read. Nothing
here writes, mutates or re-derives authority - :func:`build_turn_trace` is a pure
function over records the caller already read, so a trace can be rebuilt from the
log at any moment and can never become a second evidence spine.

What the projection does:

- delimit the turn by its own durable markers: ``SESSION_TURN_STARTED`` opens it,
  ``SESSION_TURN_COMPLETED`` closes it. Without the closing record the turn is
  ``OPEN`` - never inferred complete, never padded;
- build a span per real step of the turn, and only from records that substantiate
  it: the model response receipt (``PROVIDER_RESPONDED``), the loop's policy
  verdict (``POLICY_VERDICT_RECORDED``), the dispatcher's decision
  (``POLICY_DECIDED``), the proposal/pending/decision of an approval
  (``ACTION_PROPOSED``/``SESSION_APPROVAL_PENDING``/``APPROVAL_REQUESTED``/
  ``APPROVAL_RECORDED``) and the outcome of a dispatch (``ACTION_RECEIPT_RECORDED``
  / ``NODE_COMPLETED`` / ``NODE_FAILED`` / a ``RUN_PAUSED`` unknown-effect marker);
- link each span to the turn using ids the records already carry, and label which
  id did the linking (:class:`TraceLinkKind`). The weakest label, ``SEQUENCE_WINDOW``,
  is reserved for a record that no id joins to the turn (the loop's allowlist and
  deny-rule verdicts fall into this class: they are written before any Action
  exists). A consumer is told which links are causal and which are positional
  instead of being handed a uniform-looking timeline;
- state every hole it finds as a :class:`TraceGap` rather than closing it up. A
  record the projection cannot decode or interpret backs no span and is reported;
  an action with no terminal record, an approval with no decision, a turn with no
  completion, and a turn that stopped on a provider failure (whose failing
  invocation records no durable event; its attempt records live in the provider
  log, keyed by ``request_id``) all surface as typed gaps.

What the projection deliberately does not project: message text, completion text,
tool arguments, approval previews and credentials. The durable records carry all
of those (``SESSION_TURN_STARTED.user_text``, ``SESSION_MESSAGE_RECORDED.message``,
``SESSION_APPROVAL_PENDING.preview``, ``PROVIDER_RESPONDED.provider_output.text``);
only ids, enums, sequence numbers, timestamps and digests leave this module. A
trace is for structure and causation, not for replaying content.

Records outside that set - transcripts, continuation checkpoints, artifacts,
correction writes, context compaction - are not gaps: they are simply out of the
projection's scope, and ``records_scanned``/``first_sequence``/``last_sequence``
bound the window that was read.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_os_contracts import (
    ActionContract,
    ApprovalDisposition,
    PolicyDecision,
    PolicyVerdict,
    ReceiptStatus,
    TaskEvent,
    TaskEventType,
    TraceGap,
    TraceGapKind,
    TraceLinkKind,
    TraceSpan,
    TraceSpanBasis,
    TraceSpanKind,
    TraceSpanStatus,
    TraceTurnState,
    TurnTrace,
)

# The turn's own delimiters. Everything else the projection reads is dated by its
# position between them.
_TURN_STARTED = TaskEventType.SESSION_TURN_STARTED
_TURN_COMPLETED = TaskEventType.SESSION_TURN_COMPLETED

# A turn that stops on a provider failure records the code on its completion
# marker; the failing invocation itself writes no durable event.
_PROVIDER_FAILURE_PREFIX = "provider_failure:"

# A dispatch outcome the durable log states as undetermined requires external
# reconciliation, so it is a status of its own - never a failure and never a gap
# in the timeline.
_UNDETERMINED_EFFECT_STATES = frozenset({ReceiptStatus.UNKNOWN.value})


class TurnTraceNotFoundError(LookupError):
    """No durable record binds the requested session or turn.

    A missing session and a missing turn are the same class of answer - "the log
    holds no such turn" - and both are reads that must fail typed rather than
    return an empty, plausible-looking trace.
    """


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _payload(event: TaskEvent) -> dict[str, Any] | None:
    """The decoded payload, or ``None`` when the record cannot be decoded.

    A payload that is not a JSON object can only come from a foreign or damaged
    store - the writer validates it - and it must not crash a read surface.
    """

    try:
        payload = event.decoded_payload()
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _mapping(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _sequence_gaps(records: tuple[TaskEvent, ...]) -> list[TraceGap]:
    gaps: list[TraceGap] = []
    previous = 0
    for record in records:
        if record.sequence <= previous:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=record.sequence,
                    detail=(
                        f"record sequence {record.sequence} does not follow "
                        f"{previous}; the stream is out of order"
                    ),
                )
            )
            continue
        if record.sequence != previous + 1:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.SEQUENCE_GAP,
                    sequence=record.sequence,
                    detail=(
                        f"the durable stream jumps from {previous} to "
                        f"{record.sequence}; the records in between were not read"
                    ),
                )
            )
        previous = record.sequence
    return gaps


def _span(
    *,
    kind: TraceSpanKind,
    discriminator: str,
    status: TraceSpanStatus,
    started_by: TraceSpanBasis,
    started_event: TaskEvent,
    link: TraceLinkKind,
    turn_span_id: str,
    session_id: str,
    turn_id: str,
    ended_by: TraceSpanBasis,
    ended_event: TaskEvent | None = None,
    sequences: tuple[int, ...] | None = None,
    **fields: Any,
) -> TraceSpan:
    """Assemble one span; ``ended_event=None`` means no terminal record exists."""

    if sequences is None:
        if ended_event is None or ended_event.sequence == started_event.sequence:
            sequences = (started_event.sequence,)
        else:
            sequences = (started_event.sequence, ended_event.sequence)
    return TraceSpan(
        span_id=f"{kind.value}:{discriminator}:{started_event.sequence}",
        kind=kind,
        status=status,
        started_by=started_by,
        started_sequence=started_event.sequence,
        started_at=started_event.occurred_at,
        ended_by=ended_by,
        ended_sequence=None if ended_event is None else ended_event.sequence,
        ended_at=None if ended_event is None else ended_event.occurred_at,
        link=link,
        parent_span_id=turn_span_id,
        session_id=session_id,
        turn_id=turn_id,
        event_sequences=tuple(sorted(set(sequences))),
        **fields,
    )


def _verdict_status(verdict: PolicyVerdict) -> TraceSpanStatus:
    """ALLOW is the only verdict that lets an action proceed."""

    return (
        TraceSpanStatus.ALLOWED
        if verdict is PolicyVerdict.ALLOW
        else TraceSpanStatus.DENIED
    )


class _Proposal:
    """A durable ``ACTION_PROPOSED`` and the action contract it binds."""

    __slots__ = ("action", "digest", "event")

    def __init__(self, event: TaskEvent, action: ActionContract) -> None:
        self.event = event
        self.action = action
        self.digest = action.action_digest()


def _proposals(
    events: tuple[TaskEvent, ...], gaps: list[TraceGap]
) -> dict[str, _Proposal]:
    proposals: dict[str, _Proposal] = {}
    for event in events:
        if event.event_type is not TaskEventType.ACTION_PROPOSED:
            continue
        payload = _payload(event)
        action_payload = None if payload is None else _mapping(payload.get("action"))
        if action_payload is None:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=event.sequence,
                    detail=(
                        "ACTION_PROPOSED carries no decodable action contract, so "
                        "the proposal backs no span"
                    ),
                )
            )
            continue
        try:
            action = ActionContract.model_validate(action_payload)
        except (TypeError, ValueError):
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=event.sequence,
                    detail=(
                        "ACTION_PROPOSED action contract is invalid, so the "
                        "proposal backs no span"
                    ),
                )
            )
            continue
        # The exact digest the writer bound to this action: recomputed with the
        # contract's own digest function, so the join to an approval or a receipt
        # uses the durable identity rather than a new one.
        proposals[action.action_id] = _Proposal(event, action)
    return proposals


def build_turn_trace(
    events: Sequence[TaskEvent],
    *,
    session_id: str,
    turn_id: str | None = None,
    task_id: str | None = None,
) -> TurnTrace:
    """Project the trace of one turn from durable records.

    ``turn_id=None`` selects the session's most recently started turn, so an
    operator can ask for "the turn that just ran" without knowing its id.

    Raises :class:`TurnTraceNotFoundError` when the stream holds no such session
    or no such turn. A turn the log does not close is not an error: it is returned
    with ``state == OPEN`` and a ``TURN_OPEN`` gap.
    """

    if not session_id.strip():
        raise ValueError("session_id must be non-empty")
    if turn_id is not None and not turn_id.strip():
        raise ValueError("turn_id must be non-empty when provided")

    records = tuple(sorted(events, key=lambda event: event.sequence))
    if not records:
        raise TurnTraceNotFoundError(
            f"session {session_id!r} has no durable records to project"
        )
    gaps: list[TraceGap] = _sequence_gaps(tuple(events))

    run_id: str | None = None
    opened = False
    for record in records:
        if record.event_type is not TaskEventType.SESSION_OPENED:
            continue
        payload = _payload(record)
        if payload is not None and payload.get("session_id") == session_id:
            opened = True
            run_id = _text(payload.get("run_id"))
            break
    if not opened:
        raise TurnTraceNotFoundError(
            f"session {session_id!r} is not in the durable stream of this task"
        )

    starts: list[tuple[TaskEvent, dict[str, Any]]] = []
    unreadable_starts = 0
    for record in records:
        if record.event_type is not _TURN_STARTED:
            continue
        payload = _payload(record)
        if payload is None or payload.get("session_id") != session_id:
            if payload is None:
                unreadable_starts += 1
                gaps.append(
                    TraceGap(
                        kind=TraceGapKind.MALFORMED_EVENT,
                        sequence=record.sequence,
                        detail=(
                            "SESSION_TURN_STARTED has no decodable payload, so the "
                            "turn it opened cannot be identified"
                        ),
                    )
                )
            continue
        if _text(payload.get("turn_id")) is None:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=record.sequence,
                    detail=(
                        "SESSION_TURN_STARTED names no turn_id; the record backs no "
                        "turn"
                    ),
                )
            )
            continue
        starts.append((record, payload))

    if not starts:
        raise TurnTraceNotFoundError(
            f"session {session_id!r} has no SESSION_TURN_STARTED record"
            + (
                f" ({unreadable_starts} unreadable start record(s) may hold it)"
                if unreadable_starts
                else ""
            )
        )

    if turn_id is None:
        start_event, start_payload = starts[-1]
        turn = str(start_payload["turn_id"])
    else:
        turn = turn_id
        matches = [
            (event, payload)
            for event, payload in starts
            if payload.get("turn_id") == turn
        ]
        if not matches:
            raise TurnTraceNotFoundError(
                f"session {session_id!r} has no turn {turn!r}"
                + (
                    f" ({unreadable_starts} unreadable start record(s) may hold it)"
                    if unreadable_starts
                    else ""
                )
            )
        start_event, start_payload = matches[0]
        if len(matches) > 1:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=matches[1][0].sequence,
                    subject=turn,
                    detail=(
                        "SESSION_TURN_STARTED appears more than once for this turn; "
                        "the trace is built from the first one"
                    ),
                )
            )

    completion: TaskEvent | None = None
    for record in records:
        if record.sequence <= start_event.sequence:
            continue
        if record.event_type is not _TURN_COMPLETED:
            continue
        payload = _payload(record)
        if payload is None or payload.get("turn_id") != turn:
            continue
        if completion is None:
            completion = record
        else:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=record.sequence,
                    subject=turn,
                    detail=(
                        "SESSION_TURN_COMPLETED appears more than once for this "
                        "turn; the trace is closed by the first one"
                    ),
                )
            )

    if completion is not None:
        window_end = completion.sequence
    else:
        later_start = next(
            (
                record
                for record in records
                if record.sequence > start_event.sequence
                and record.event_type is _TURN_STARTED
                and (_payload(record) or {}).get("session_id") == session_id
            ),
            None,
        )
        window_end = (
            later_start.sequence - 1 if later_start is not None else records[-1].sequence
        )
        gaps.append(
            TraceGap(
                kind=TraceGapKind.TURN_OPEN,
                sequence=start_event.sequence,
                subject=turn,
                detail=(
                    "the durable log holds no SESSION_TURN_COMPLETED for this turn; "
                    "its status and stop reason are unknown"
                    + (
                        "; a later turn started before this one closed"
                        if later_start is not None
                        else ""
                    )
                ),
            )
        )

    window = tuple(
        record
        for record in records
        if start_event.sequence <= record.sequence <= window_end
    )

    stop_reason: str | None = None
    if completion is not None:
        completed_payload = _payload(completion) or {}
        stop_reason = _text(completed_payload.get("stop_reason"))

    turn_span_id = f"{TraceSpanKind.TURN.value}:{turn}:{start_event.sequence}"
    spans: list[TraceSpan] = [
        _span(
            kind=TraceSpanKind.TURN,
            discriminator=turn,
            status=(
                TraceSpanStatus.COMPLETED
                if completion is not None
                else TraceSpanStatus.OPEN
            ),
            started_by=TraceSpanBasis.TURN_STARTED,
            started_event=start_event,
            ended_by=(
                TraceSpanBasis.TURN_COMPLETED
                if completion is not None
                else TraceSpanBasis.OPEN_NO_TERMINAL_RECORD
            ),
            ended_event=completion,
            link=TraceLinkKind.ROOT,
            turn_span_id=turn_span_id,
            session_id=session_id,
            turn_id=turn,
            run_id=run_id,
            stop_reason=stop_reason,
        )
    ]

    if (
        completion is not None
        and stop_reason is not None
        and stop_reason.startswith(_PROVIDER_FAILURE_PREFIX)
    ):
        gaps.append(
            TraceGap(
                kind=TraceGapKind.MODEL_CALL_NOT_RECORDED,
                sequence=completion.sequence,
                subject=turn,
                detail=(
                    f"the turn stopped on {stop_reason}; the failing invocation "
                    "wrote no durable record of its own (its attempt records live "
                    "in the provider log, keyed by request_id)"
                ),
            )
        )

    proposals = _proposals(window, gaps)
    by_digest = {proposal.digest: proposal for proposal in proposals.values()}

    # ---- model calls ----------------------------------------------------
    for record in window:
        if record.event_type is not TaskEventType.PROVIDER_RESPONDED:
            continue
        payload = _payload(record)
        receipt = None if payload is None else _mapping(
            payload.get("provider_execution_receipt")
        )
        node_id = None if payload is None else _text(payload.get("node_id"))
        if payload is None or receipt is None or node_id is None:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=record.sequence,
                    detail=(
                        "PROVIDER_RESPONDED has no decodable receipt or node_id, so "
                        "it backs no model-call span"
                    ),
                )
            )
            continue
        # The node id the loop mints is "<turn_id>-step-<n>", so it names its own
        # turn; anything else is placed by sequence and labelled as such.
        if node_id.startswith(f"{turn}-"):
            link = TraceLinkKind.NODE_ID_TURN_PREFIX
        else:
            link = TraceLinkKind.SEQUENCE_WINDOW
        spans.append(
            _span(
                kind=TraceSpanKind.MODEL_CALL,
                discriminator=node_id,
                status=TraceSpanStatus.COMPLETED,
                started_by=TraceSpanBasis.MODEL_RESPONSE_RECORDED,
                started_event=record,
                ended_by=TraceSpanBasis.MODEL_RESPONSE_RECORDED,
                ended_event=record,
                link=link,
                turn_span_id=turn_span_id,
                session_id=session_id,
                turn_id=turn,
                run_id=_text(receipt.get("run_id")) or run_id,
                node_id=node_id,
                request_id=_text(receipt.get("request_id")),
                response_id=_text(receipt.get("response_id")),
            )
        )

    # ---- the loop's E2 policy verdicts ---------------------------------
    for record in window:
        if record.event_type is not TaskEventType.POLICY_VERDICT_RECORDED:
            continue
        payload = _payload(record)
        raw_verdict = None if payload is None else _text(payload.get("verdict"))
        try:
            verdict = PolicyVerdict(raw_verdict) if raw_verdict else None
        except ValueError:
            verdict = None
        if payload is None or verdict is None:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=record.sequence,
                    detail=(
                        "POLICY_VERDICT_RECORDED carries no recognised verdict, so "
                        "it backs no span"
                    ),
                )
            )
            continue
        digest = _text(payload.get("action_digest"))
        proposal = by_digest.get(digest) if digest is not None else None
        spans.append(
            _span(
                kind=TraceSpanKind.POLICY_VERDICT,
                discriminator=digest or f"verdict-{record.sequence}",
                status=_verdict_status(verdict),
                started_by=TraceSpanBasis.POLICY_VERDICT_RECORDED,
                started_event=record,
                ended_by=TraceSpanBasis.POLICY_VERDICT_RECORDED,
                ended_event=record,
                link=(
                    TraceLinkKind.ACTION_DIGEST
                    if proposal is not None
                    else TraceLinkKind.SEQUENCE_WINDOW
                ),
                turn_span_id=turn_span_id,
                session_id=session_id,
                turn_id=turn,
                run_id=proposal.action.run_id if proposal is not None else run_id,
                action_id=proposal.action.action_id if proposal is not None else None,
                action_digest=digest,
                node_id=proposal.action.node_id if proposal is not None else None,
                capability_id=_text(payload.get("capability_id")),
                rule_id=_text(payload.get("rule_id")),
                verdict=verdict.value,
                basis=_text(payload.get("basis")),
            )
        )

    # ---- the dispatcher's decisions ------------------------------------
    for record in window:
        if record.event_type is not TaskEventType.POLICY_DECIDED:
            continue
        payload = _payload(record)
        decision_payload = None if payload is None else _mapping(
            payload.get("decision")
        )
        decision: PolicyDecision | None = None
        if decision_payload is not None:
            try:
                decision = PolicyDecision.model_validate(decision_payload)
            except (TypeError, ValueError):
                decision = None
        if decision is None:
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.MALFORMED_EVENT,
                    sequence=record.sequence,
                    detail=(
                        "POLICY_DECIDED carries no decodable decision, so it backs "
                        "no span"
                    ),
                )
            )
            continue
        proposal = proposals.get(decision.action_id) or by_digest.get(
            decision.action_digest
        )
        if proposal is None:
            link = TraceLinkKind.SEQUENCE_WINDOW
        elif proposal.action.action_id == decision.action_id:
            link = TraceLinkKind.ACTION_ID
        else:
            link = TraceLinkKind.ACTION_DIGEST
        spans.append(
            _span(
                kind=TraceSpanKind.POLICY_DECISION,
                discriminator=decision.action_id,
                status=_verdict_status(decision.verdict),
                started_by=TraceSpanBasis.POLICY_DECIDED,
                started_event=record,
                ended_by=TraceSpanBasis.POLICY_DECIDED,
                ended_event=record,
                link=link,
                turn_span_id=turn_span_id,
                session_id=session_id,
                turn_id=turn,
                run_id=proposal.action.run_id if proposal is not None else run_id,
                action_id=decision.action_id,
                action_digest=decision.action_digest,
                node_id=proposal.action.node_id if proposal is not None else None,
                capability_id=(
                    proposal.action.capability_id if proposal is not None else None
                ),
                decision_id=decision.decision_id,
                verdict=decision.verdict.value,
                reason_codes=decision.reason_codes,
            )
        )

    # ---- approvals ------------------------------------------------------
    decisions_by_digest: dict[str, tuple[TaskEvent, dict[str, Any]]] = {}
    pendings_by_digest: dict[str, TaskEvent] = {}
    requested_by_action_id: dict[str, TaskEvent] = {}
    for record in window:
        payload = _payload(record)
        if payload is None:
            continue
        if record.event_type is TaskEventType.APPROVAL_RECORDED:
            approval = _mapping(payload.get("approval"))
            digest = None if approval is None else _text(approval.get("action_digest"))
            if approval is None or digest is None:
                gaps.append(
                    TraceGap(
                        kind=TraceGapKind.MALFORMED_EVENT,
                        sequence=record.sequence,
                        detail=(
                            "APPROVAL_RECORDED carries no decodable decision, so it "
                            "backs no span"
                        ),
                    )
                )
                continue
            decisions_by_digest.setdefault(digest, (record, approval))
        elif record.event_type is TaskEventType.SESSION_APPROVAL_PENDING:
            digest = _text(payload.get("action_digest"))
            if digest is not None:
                pendings_by_digest.setdefault(digest, record)
        elif record.event_type is TaskEventType.APPROVAL_REQUESTED:
            action_id = _text(payload.get("action_id"))
            if action_id is not None:
                requested_by_action_id.setdefault(action_id, record)

    approval_spans: dict[str, TraceSpan] = {}
    approval_status: dict[str, ApprovalDisposition] = {}
    for proposal in proposals.values():
        digest = proposal.digest
        decision_record = decisions_by_digest.get(digest)
        disposition = None
        if decision_record is not None:
            try:
                disposition = ApprovalDisposition(decision_record[1].get("disposition"))
            except ValueError:
                gaps.append(
                    TraceGap(
                        kind=TraceGapKind.MALFORMED_EVENT,
                        sequence=decision_record[0].sequence,
                        subject=proposal.action.action_id,
                        detail=(
                            "APPROVAL_RECORDED carries no recognised disposition, so "
                            "it backs no span"
                        ),
                    )
                )
                decision_record = None
        pending = pendings_by_digest.get(digest)
        requested = requested_by_action_id.get(proposal.action.action_id)
        if pending is not None:
            started_by = TraceSpanBasis.APPROVAL_PENDING_RECORDED
            span_start = pending
            link = TraceLinkKind.TURN_ID
        elif requested is not None:
            started_by = TraceSpanBasis.APPROVAL_REQUESTED
            span_start = requested
            link = TraceLinkKind.ACTION_ID
        elif decision_record is not None:
            # The interactive ASK path records the decision alone: the request was
            # the prompt itself, and inventing a request span would be fabrication.
            started_by = TraceSpanBasis.APPROVAL_RECORDED
            span_start = decision_record[0]
            link = TraceLinkKind.ACTION_DIGEST
        else:
            continue
        span_end = (
            decision_record[0]
            if decision_record is not None
            and decision_record[0].sequence >= span_start.sequence
            else None
        )
        if disposition is not None and span_end is not None:
            approval_status[digest] = disposition
            status = (
                TraceSpanStatus.APPROVED
                if disposition is ApprovalDisposition.APPROVE
                else TraceSpanStatus.REJECTED
            )
        else:
            status = TraceSpanStatus.OPEN
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.APPROVAL_UNRESOLVED,
                    sequence=span_start.sequence,
                    subject=proposal.action.action_id,
                    detail=(
                        "an approval was requested for this action and no decision "
                        "is recorded"
                    ),
                )
            )
        sequences = {span_start.sequence}
        if span_end is not None:
            sequences.add(span_end.sequence)
        span = _span(
            kind=TraceSpanKind.APPROVAL,
            discriminator=proposal.action.action_id,
            status=status,
            started_by=started_by,
            started_event=span_start,
            ended_by=(
                TraceSpanBasis.APPROVAL_RECORDED
                if span_end is not None
                else TraceSpanBasis.OPEN_NO_TERMINAL_RECORD
            ),
            ended_event=span_end,
            sequences=tuple(sequences),
            link=link,
            turn_span_id=turn_span_id,
            session_id=session_id,
            turn_id=turn,
            run_id=proposal.action.run_id,
            action_id=proposal.action.action_id,
            action_digest=digest,
            node_id=proposal.action.node_id,
            capability_id=proposal.action.capability_id,
            approval_id=(
                _text(decision_record[1].get("approval_id"))
                if decision_record is not None
                else None
            ),
            disposition=None if disposition is None else disposition.value,
        )
        approval_spans[digest] = span
        spans.append(span)

    # ---- dispatch outcomes ---------------------------------------------
    receipts: dict[str, tuple[TaskEvent, dict[str, Any], dict[str, Any]]] = {}
    nodes: dict[str, tuple[TaskEvent, TaskEventType, dict[str, Any]]] = {}
    undetermined: dict[str, tuple[TaskEvent, dict[str, Any]]] = {}
    for record in window:
        payload = _payload(record)
        if payload is None:
            continue
        if record.event_type is TaskEventType.ACTION_RECEIPT_RECORDED:
            decision_payload = _mapping(payload.get("decision"))
            receipt_payload = _mapping(payload.get("receipt"))
            action_id = (
                None if decision_payload is None else _text(decision_payload.get("action_id"))
            )
            if decision_payload is None or receipt_payload is None or action_id is None:
                gaps.append(
                    TraceGap(
                        kind=TraceGapKind.MALFORMED_EVENT,
                        sequence=record.sequence,
                        detail=(
                            "ACTION_RECEIPT_RECORDED carries no decodable decision or "
                            "receipt, so it backs no span"
                        ),
                    )
                )
                continue
            receipts.setdefault(action_id, (record, decision_payload, receipt_payload))
        elif record.event_type in {
            TaskEventType.NODE_COMPLETED,
            TaskEventType.NODE_FAILED,
        }:
            action_id = _text(payload.get("action_id"))
            if action_id is not None:
                nodes.setdefault(
                    action_id, (record, record.event_type, payload)
                )
        elif record.event_type is TaskEventType.RUN_PAUSED:
            unknown = _mapping(payload.get("unknown_action"))
            if unknown is None:
                continue
            action = _mapping(unknown.get("action"))
            action_id = None if action is None else _text(action.get("action_id"))
            digest = _text(unknown.get("action_digest"))
            key = action_id or digest
            if key is not None:
                undetermined.setdefault(key, (record, unknown))

    for proposal in proposals.values():
        action = proposal.action
        sequences = {proposal.event.sequence}
        receipt = receipts.get(action.action_id)
        node = nodes.get(action.action_id)
        unknown = undetermined.get(action.action_id) or undetermined.get(
            proposal.digest
        )
        disposition = approval_status.get(proposal.digest)
        status: TraceSpanStatus
        ended_by: TraceSpanBasis
        ended_event: TaskEvent | None = None
        effect_state: str | None = None
        provider_tool_call_id: str | None = None
        if receipt is not None:
            ended_event, decision_payload, receipt_payload = receipt
            sequences.add(ended_event.sequence)
            effect_state = _text(receipt_payload.get("status"))
            if effect_state in _UNDETERMINED_EFFECT_STATES:
                status = TraceSpanStatus.UNDETERMINED
            elif effect_state == ReceiptStatus.SUCCEEDED.value:
                status = TraceSpanStatus.COMPLETED
            else:
                # Every other durable receipt status (FAILED, CANCELLED,
                # DISPATCHED, ACKNOWLEDGED, COMPENSATED) is the system's own "the
                # dispatch did not succeed" - the loop raises on all of them. The
                # literal status stays visible in effect_state.
                status = TraceSpanStatus.FAILED
            ended_by = TraceSpanBasis.EFFECT_RECEIPT_RECORDED
        elif node is not None:
            ended_event, node_type, node_payload = node
            sequences.add(ended_event.sequence)
            provider_tool_call_id = _text(node_payload.get("provider_tool_call_id"))
            if node_type is TaskEventType.NODE_COMPLETED:
                status = TraceSpanStatus.COMPLETED
                ended_by = TraceSpanBasis.NODE_COMPLETED
            else:
                status = TraceSpanStatus.FAILED
                ended_by = TraceSpanBasis.NODE_FAILED
        elif unknown is not None:
            ended_event, unknown_payload = unknown
            sequences.add(ended_event.sequence)
            status = TraceSpanStatus.UNDETERMINED
            ended_by = TraceSpanBasis.EFFECT_UNDETERMINED
            effect_state = ReceiptStatus.UNKNOWN.value
            provider_tool_call_id = _text(unknown_payload.get("proposal_id"))
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.EFFECT_UNDETERMINED,
                    sequence=ended_event.sequence,
                    subject=action.action_id,
                    detail=(
                        "the dispatched effect is UNKNOWN in durable truth and "
                        "requires external reconciliation; the action is not "
                        "auto-retried"
                    ),
                )
            )
        elif disposition is ApprovalDisposition.REJECT:
            status = TraceSpanStatus.REJECTED
            ended_by = TraceSpanBasis.APPROVAL_REJECTED
            rejection = decisions_by_digest.get(proposal.digest)
            if rejection is not None:
                ended_event = rejection[0]
                sequences.add(ended_event.sequence)
        else:
            status = TraceSpanStatus.OPEN
            ended_by = TraceSpanBasis.OPEN_NO_TERMINAL_RECORD
            gaps.append(
                TraceGap(
                    kind=TraceGapKind.DISPATCH_UNRESOLVED,
                    sequence=proposal.event.sequence,
                    subject=action.action_id,
                    detail=(
                        "the action was proposed and the durable log holds no "
                        "terminal record for it: no receipt, no node outcome and no "
                        "rejection"
                    ),
                )
            )
        spans.append(
            _span(
                kind=TraceSpanKind.CAPABILITY_DISPATCH,
                discriminator=action.action_id,
                status=status,
                started_by=TraceSpanBasis.ACTION_PROPOSED,
                started_event=proposal.event,
                ended_by=ended_by,
                ended_event=ended_event,
                sequences=tuple(sequences),
                link=TraceLinkKind.ACTION_ID,
                turn_span_id=turn_span_id,
                session_id=session_id,
                turn_id=turn,
                run_id=action.run_id,
                action_id=action.action_id,
                action_digest=proposal.digest,
                node_id=action.node_id,
                capability_id=action.capability_id,
                provider_tool_call_id=provider_tool_call_id,
                permit_id=(
                    _text(_mapping(receipt[2]).get("permit_id"))
                    if receipt is not None
                    else None
                ),
                effect_state=effect_state,
            )
        )

    spans.sort(key=lambda span: (span.started_sequence, span.kind.value))
    gaps.sort(key=lambda gap: (gap.sequence or 0, gap.kind.value))

    first_sequence = records[0].sequence
    return TurnTrace(
        task_id=task_id or records[0].task_id,
        session_id=session_id,
        turn_id=turn,
        state=(
            TraceTurnState.COMPLETE
            if completion is not None
            else TraceTurnState.OPEN
        ),
        stop_reason=stop_reason,
        started_sequence=start_event.sequence,
        started_at=start_event.occurred_at,
        ended_sequence=None if completion is None else completion.sequence,
        ended_at=None if completion is None else completion.occurred_at,
        records_scanned=len(records),
        first_sequence=first_sequence,
        last_sequence=records[-1].sequence,
        spans=tuple(spans),
        gaps=tuple(gaps),
    )


__all__ = ["TurnTraceNotFoundError", "build_turn_trace"]
