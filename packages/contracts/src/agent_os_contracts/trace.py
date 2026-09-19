"""Typed read-out of one governed turn: what happened, in what order, caused by what.

One shape for the answer to "replay the structure of a turn without replaying its
content", served by ``GET /v1/surface/sessions/{session_id}/trace`` and produced by
``agent_os_core.turn_trace``.

A trace is a *derived projection* of the durable Task event stream - never new
truth, never a second evidence spine, never a write path. Every span names the
exact durable records it was built from (``event_sequences``) and the record kind
that opened and closed it (``started_by``/``ended_by``), so the trace stays
re-derivable from the log at any time and cannot drift into an independent story.

Content boundary, by construction: these models have no field that can carry a
prompt, a completion, a tool argument payload, an approval preview or a
credential. The durable records *do* carry such content (``SESSION_TURN_STARTED``
holds the operator's text, ``SESSION_MESSAGE_RECORDED`` holds whole messages, the
approval continuation holds an action preview, ``PROVIDER_RESPONDED`` holds the
completion and its tool arguments); only ids, enums, sequence numbers, timestamps
and digests are projected. A trace is for structure and causation, not for
replaying content - ``/export`` already serves the operator's own transcript.

Honesty, by construction: a span exists only when a durable record substantiates
it, and anything the projection cannot interpret becomes a :class:`TraceGap`
(never a fabricated span, never a silently shorter timeline). ``state == OPEN``
means the durable log holds no ``SESSION_TURN_COMPLETED`` for the turn.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from .common import ContractModel, NonEmptyStr, UtcDateTime


class TraceSpanKind(str, Enum):
    """What a span is, i.e. which durable record family it projects.

    ``TURN`` (``SESSION_TURN_STARTED``/``SESSION_TURN_COMPLETED``),
    ``MODEL_CALL`` (``PROVIDER_RESPONDED``), ``POLICY_VERDICT``
    (``POLICY_VERDICT_RECORDED``: the chat loop's E2 verdict on a proposed
    capability - allowlist, operator deny rule, permission mode),
    ``POLICY_DECISION`` (``POLICY_DECIDED``: the dispatcher's decision on a built
    action, with its permit basis), ``APPROVAL`` (``APPROVAL_REQUESTED`` /
    ``APPROVAL_RECORDED``) and ``CAPABILITY_DISPATCH`` (``ACTION_PROPOSED`` to its
    receipt/node outcome).
    """

    TURN = "TURN"
    MODEL_CALL = "MODEL_CALL"
    POLICY_VERDICT = "POLICY_VERDICT"
    POLICY_DECISION = "POLICY_DECISION"
    APPROVAL = "APPROVAL"
    CAPABILITY_DISPATCH = "CAPABILITY_DISPATCH"


class TraceSpanStatus(str, Enum):
    """The span's state, always read off durable records - never inferred.

    Which values a kind can take:

    - ``TURN``: ``COMPLETED`` (its ``SESSION_TURN_COMPLETED`` is in the log) or
      ``OPEN`` (it is not - the turn is still in flight, or it was interrupted).
    - ``MODEL_CALL``: ``COMPLETED`` (a response receipt was recorded). A model
      invocation that failed and was retried, or that ended the turn in
      ``provider_failure:<code>``, writes no durable record of its own: it appears
      as a :class:`TraceGap` on the turn instead.
    - ``POLICY_VERDICT``/``POLICY_DECISION``: ``ALLOWED`` or ``DENIED``.
    - ``APPROVAL``: ``APPROVED``, ``REJECTED``, or ``OPEN`` when a request is
      recorded and no decision is.
    - ``CAPABILITY_DISPATCH``: ``COMPLETED`` (a terminal success record),
      ``FAILED`` (a terminal failure record), ``REJECTED`` (the bound operator
      decision rejected the action, so it was never dispatched), ``UNDETERMINED``
      (a durable record says the external effect is UNKNOWN and needs external
      reconciliation) or ``OPEN`` (proposed, with no terminal record in the log).
    """

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    UNDETERMINED = "UNDETERMINED"
    OPEN = "OPEN"


class TraceSpanBasis(str, Enum):
    """The durable record kind that started or ended a span.

    A span may only cite one of these, so "what closed this dispatch?" always has
    a durable answer. ``OPEN_NO_TERMINAL_RECORD`` is not a record: it is the
    explicit statement that the scan found none.
    """

    TURN_STARTED = "TURN_STARTED"
    TURN_COMPLETED = "TURN_COMPLETED"
    MODEL_RESPONSE_RECORDED = "MODEL_RESPONSE_RECORDED"
    POLICY_VERDICT_RECORDED = "POLICY_VERDICT_RECORDED"
    POLICY_DECIDED = "POLICY_DECIDED"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    APPROVAL_PENDING_RECORDED = "APPROVAL_PENDING_RECORDED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    EFFECT_RECEIPT_RECORDED = "EFFECT_RECEIPT_RECORDED"
    NODE_COMPLETED = "NODE_COMPLETED"
    NODE_FAILED = "NODE_FAILED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    EFFECT_UNDETERMINED = "EFFECT_UNDETERMINED"
    OPEN_NO_TERMINAL_RECORD = "OPEN_NO_TERMINAL_RECORD"


class TraceLinkKind(str, Enum):
    """Which durable fact placed a span in this turn - strongest available first.

    ``ROOT`` is the turn span itself. ``TURN_ID``, ``NODE_ID_TURN_PREFIX``,
    ``ACTION_ID`` and ``ACTION_DIGEST`` are explicit joins on ids the records
    themselves carry. ``SEQUENCE_WINDOW`` is the weakest and says so: no id joins
    the record to the turn, so it is in the trace only because its sequence falls
    inside the turn's window. A consumer that needs causation rather than ordering
    must treat ``SEQUENCE_WINDOW`` as positional evidence.
    """

    ROOT = "ROOT"
    TURN_ID = "TURN_ID"
    NODE_ID_TURN_PREFIX = "NODE_ID_TURN_PREFIX"
    ACTION_ID = "ACTION_ID"
    ACTION_DIGEST = "ACTION_DIGEST"
    SEQUENCE_WINDOW = "SEQUENCE_WINDOW"


class TraceGapKind(str, Enum):
    """A hole in the evidence, stated instead of papered over.

    - ``TURN_OPEN``: no ``SESSION_TURN_COMPLETED`` for the turn.
    - ``DISPATCH_UNRESOLVED``: an action was proposed and the log holds no
      terminal record for it (no receipt, no node outcome, no rejection).
    - ``EFFECT_UNDETERMINED``: a durable record says the dispatched effect is
      UNKNOWN and requires external reconciliation.
    - ``APPROVAL_UNRESOLVED``: an approval was requested and no decision is
      recorded.
    - ``MODEL_CALL_NOT_RECORDED``: the turn stopped on a provider failure, so the
      failing invocation has no durable record of its own. The attempt records
      behind it live in the provider log, keyed by ``request_id``.
    - ``MALFORMED_EVENT``: a durable record could not be decoded or interpreted,
      so it backs no span and is reported here.
    - ``SEQUENCE_GAP``: the scanned stream is not contiguous, so the window may be
      incomplete.
    """

    TURN_OPEN = "TURN_OPEN"
    DISPATCH_UNRESOLVED = "DISPATCH_UNRESOLVED"
    EFFECT_UNDETERMINED = "EFFECT_UNDETERMINED"
    APPROVAL_UNRESOLVED = "APPROVAL_UNRESOLVED"
    MODEL_CALL_NOT_RECORDED = "MODEL_CALL_NOT_RECORDED"
    MALFORMED_EVENT = "MALFORMED_EVENT"
    SEQUENCE_GAP = "SEQUENCE_GAP"


class TraceGap(ContractModel):
    """One honest hole: what is missing, where, and about what.

    ``sequence`` is the durable record the gap is anchored to where one exists.
    ``subject`` is a durable id (turn/action/node/capability), never content.
    """

    kind: TraceGapKind
    sequence: int | None = Field(default=None, ge=1)
    subject: NonEmptyStr | None = None
    detail: NonEmptyStr


class TraceSpan(ContractModel):
    """One step of a turn, built only from records that substantiate it.

    ``span_id`` is derived from the span's kind and its durable discriminator, so
    rebuilding the trace from the same log yields the same ids.
    """

    span_id: NonEmptyStr
    kind: TraceSpanKind
    status: TraceSpanStatus
    started_by: TraceSpanBasis
    started_sequence: int = Field(ge=1)
    started_at: UtcDateTime
    ended_by: TraceSpanBasis | None = None
    ended_sequence: int | None = Field(default=None, ge=1)
    ended_at: UtcDateTime | None = None
    link: TraceLinkKind
    parent_span_id: NonEmptyStr
    session_id: NonEmptyStr
    turn_id: NonEmptyStr
    run_id: NonEmptyStr | None = None
    action_id: NonEmptyStr | None = None
    action_digest: NonEmptyStr | None = None
    node_id: NonEmptyStr | None = None
    capability_id: NonEmptyStr | None = None
    provider_tool_call_id: NonEmptyStr | None = None
    request_id: NonEmptyStr | None = None
    response_id: NonEmptyStr | None = None
    decision_id: NonEmptyStr | None = None
    permit_id: NonEmptyStr | None = None
    approval_id: NonEmptyStr | None = None
    rule_id: NonEmptyStr | None = None
    verdict: str | None = None
    basis: str | None = None
    reason_codes: tuple[NonEmptyStr, ...] = ()
    disposition: str | None = None
    effect_state: str | None = None
    stop_reason: str | None = None
    # Every durable record this span was built from, in sequence order. A span
    # with none would be fabrication, so the field has a floor of one.
    event_sequences: tuple[int, ...] = Field(min_length=1)


class TraceTurnState(str, Enum):
    """Whether the durable log closes the turn."""

    COMPLETE = "COMPLETE"
    OPEN = "OPEN"


class TurnTrace(ContractModel):
    """One turn projected from the durable Task event stream of its session.

    ``records_scanned``, ``first_sequence`` and ``last_sequence`` describe the
    window the projection read, so a consumer can tell a short trace from a
    partially read one. ``spans`` is ordered by ``started_sequence``.
    """

    task_id: NonEmptyStr
    session_id: NonEmptyStr
    turn_id: NonEmptyStr
    state: TraceTurnState
    stop_reason: str | None = None
    started_sequence: int = Field(ge=1)
    started_at: UtcDateTime
    ended_sequence: int | None = Field(default=None, ge=1)
    ended_at: UtcDateTime | None = None
    records_scanned: int = Field(ge=1)
    first_sequence: int = Field(ge=1)
    last_sequence: int = Field(ge=1)
    spans: tuple[TraceSpan, ...] = ()
    gaps: tuple[TraceGap, ...] = ()
