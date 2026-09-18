"""Trace projection of a governed turn, and its public read surface.

Measured gap (2026-09-18, after PR #73 closed the metrics half): observability
was the durable task-event audit, `/task`, `/export` and the aggregated provider
metrics, but nothing projected *one turn* as a machine-readable, causally
labelled sequence of what happened. This module asserts:

- a trace is derived, read-only and re-derivable: it is a pure function over the
  task's own durable records, it writes nothing, and every span cites the exact
  records it was built from - a span the log does not substantiate cannot exist;
- the spans are the real steps of a turn (turn, model call, policy verdict,
  policy decision, approval, capability dispatch) and each one says which record
  kind opened and closed it and which durable id linked it to its turn;
- a denial, a rejection and a fail-closed policy verdict are projected, never
  dropped: a trace that quietly omits a refusal is worse than no trace;
- every hole is typed: a turn the log never closed, an action with no terminal
  record, an approval with no decision, an undetermined effect, an unreadable or
  non-contiguous stream and a provider failure with no durable invocation record
  all surface as gaps instead of being closed up;
- the projection carries no prompt, completion, tool argument, approval preview
  or credential - the durable records hold all of those, the trace holds none of
  them (asserted against a real turn whose log *does* carry the secret text);
- the public read path is the authenticated route
  ``GET /v1/surface/sessions/{session_id}/trace`` with a typed body, and it agrees
  with the projection function.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

import pytest

from agent_os_contracts import (
    ProviderErrorCode,
    ProviderFailure,
    TaskEventType,
    TurnTrace,
    TraceGapKind,
    TraceLinkKind,
    TraceSpanBasis,
    TraceSpanKind,
    TraceSpanStatus,
    TraceTurnState,
)
from agent_os_core import (
    DeferredApprovalGateway,
    DeterministicProvider,
    TurnTraceNotFoundError,
    build_turn_trace,
)

from apps.api_server.app import AgentOSApplication
from apps.api_server.server import Handler
from apps.api_server.surface_routes import SurfaceRoutes

_PROMPT = "SECRET-PROMPT-TEXT read the fixture"
_COMPLETION = "SECRET-COMPLETION-TEXT all done"
_CREDENTIAL = "sk-trace-DEADBEEF"

_SPAN_FIELDS = frozenset(
    {
        "text",
        "content",
        "prompt",
        "completion",
        "message",
        "messages",
        "user_text",
        "preview",
        "arguments",
        "arguments_json",
        "api_key",
        "credential",
        "token",
        "secret",
    }
)


# --- harness ----------------------------------------------------------------


def proposal(call_id: str, capability_id: str, arguments: dict[str, Any]) -> Any:
    from agent_os_core.provider import ProviderToolProposal

    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def read_proposal(path: str = "fixture.txt") -> Any:
    return proposal(f"call-read-{uuid4().hex[:6]}", "workspace.read", {"path": path})


def edit_proposal() -> Any:
    return proposal(
        f"call-edit-{uuid4().hex[:6]}",
        "workspace.edit",
        {"path": "fixture.txt", "old_string": "stable\n", "new_string": "changed\n"},
    )


def chat_app(root: Path, scripted: tuple = ()) -> AgentOSApplication:
    app = AgentOSApplication(
        database=root / "agent-os.sqlite3",
        workspace=root,
    )
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    return app


def open_session(app: AgentOSApplication, gateway: Any, statement: str = "work") -> Any:
    session, loop = app.open_chat_session(statement, gateway)
    return session, loop


def trace_of(app: AgentOSApplication, session_id: str, turn_id: str | None = None) -> TurnTrace:
    return app.surface_turn_trace(session_id, turn_id)


def spans_of(trace: TurnTrace, kind: TraceSpanKind) -> list[Any]:
    return [span for span in trace.spans if span.kind is kind]


def kinds(trace: TurnTrace) -> list[str]:
    return [span.kind.value for span in trace.spans]


class _FailingProvider(DeterministicProvider):
    """A provider that never answers: the turn stops on a provider failure."""

    def complete_streaming(self, request: Any, **kwargs: Any) -> Any:
        return ProviderFailure(
            failure_id=f"failure-{uuid4()}",
            request_id=request.request_id,
            code=ProviderErrorCode.RATE_LIMITED,
            retryable=False,
            safe_message="rate limited",
            occurred_at=datetime.now(timezone.utc),
        )


# --- the projection follows the durable log ---------------------------------


def test_the_trace_matches_the_durable_log_of_a_real_turn(tmp_path: Path) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(
        tmp_path,
        scripted=(
            ("", (read_proposal(),)),
            ("", (edit_proposal(),)),
            (_COMPLETION, ()),
        ),
    )
    session, loop = open_session(app, NonInteractiveDenyGateway())
    result = loop.run_turn(session, _PROMPT)
    assert result.stop_reason == "completed"

    events = tuple(app.store.read(session.task_id))
    trace = trace_of(app, session.session_id)

    assert trace.state is TraceTurnState.COMPLETE
    assert trace.stop_reason == "completed"
    assert trace.task_id == session.task_id
    assert trace.records_scanned == len(events)
    assert trace.first_sequence == events[0].sequence
    assert trace.last_sequence == events[-1].sequence

    # The saved workspace read really did dispatch (a receipt exists), and the
    # edit was refused by the operator, so the turn holds exactly one success and
    # one rejection - both visible.
    dispatched = {
        span.status for span in spans_of(trace, TraceSpanKind.CAPABILITY_DISPATCH)
    }
    assert dispatched == {TraceSpanStatus.COMPLETED, TraceSpanStatus.REJECTED}
    model_calls = spans_of(trace, TraceSpanKind.MODEL_CALL)
    assert len(model_calls) == 3
    assert all(span.status is TraceSpanStatus.COMPLETED for span in model_calls)
    decisions = spans_of(trace, TraceSpanKind.POLICY_DECISION)
    assert [span.status for span in decisions] == [TraceSpanStatus.ALLOWED]
    assert decisions[0].verdict == "ALLOW"
    approvals = spans_of(trace, TraceSpanKind.APPROVAL)
    assert [span.disposition for span in approvals] == ["REJECT"]
    succeeded = next(
        span
        for span in spans_of(trace, TraceSpanKind.CAPABILITY_DISPATCH)
        if span.status is TraceSpanStatus.COMPLETED
    )
    assert succeeded.effect_state == "SUCCEEDED"
    assert succeeded.capability_id == "workspace.read"
    # The model-call span carries the request id the provider log keys on, so a
    # trace and the metrics line up on one durable id.
    assert model_calls[0].request_id is not None
    assert model_calls[0].request_id.startswith("request-")
    assert trace.gaps == ()


def test_every_span_cites_records_of_this_task_and_is_sequence_ordered(
    tmp_path: Path,
) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(tmp_path, scripted=(("", (read_proposal(),)), ("done", ())))
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, "read it")

    events = {event.sequence: event for event in app.store.read(session.task_id)}
    trace = trace_of(app, session.session_id)

    assert trace.spans[0].kind is TraceSpanKind.TURN
    assert trace.spans[0].link is TraceLinkKind.ROOT
    previous = 0
    for span in trace.spans:
        assert span.event_sequences, "a span with no durable record is fabrication"
        assert span.turn_id == trace.turn_id
        assert span.session_id == trace.session_id
        assert span.started_sequence >= previous
        previous = span.started_sequence
        for sequence in span.event_sequences:
            event = events[sequence]
            assert event.task_id == trace.task_id
            assert trace.started_sequence <= sequence
        assert span.started_by in TraceSpanBasis
        if span.ended_sequence is None:
            assert span.ended_by is TraceSpanBasis.OPEN_NO_TERMINAL_RECORD
        else:
            assert span.ended_sequence in span.event_sequences
        assert span.parent_span_id == trace.spans[0].span_id
    # Rebuilding from the same log yields the same projection, ids included.
    assert trace_of(app, session.session_id).model_dump(
        mode="json"
    ) == trace.model_dump(mode="json")


def test_a_fail_closed_denial_is_projected_and_never_dropped(tmp_path: Path) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(
        tmp_path,
        scripted=(("", (read_proposal(),)), ("done", ())),
    )
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, "read it")

    app.provider = DeterministicProvider(
        text="",
        tool_proposals=(proposal("call-sql", "data_agent.run_sql", {}),),
        invocation_binding=app.provider.invocation_binding,
    )
    loop = app.restore_chat_session(session.session_id, NonInteractiveDenyGateway())[1]
    result = loop.run_turn(session, "now query the warehouse")
    assert result.stop_reason == "unauthorized_proposal"

    trace = trace_of(app, session.session_id)
    assert trace.stop_reason == "unauthorized_proposal"
    denials = [
        span
        for span in spans_of(trace, TraceSpanKind.POLICY_VERDICT)
        if span.status is TraceSpanStatus.DENIED
    ]
    assert len(denials) == 1, "a refusal the loop recorded must reach the trace"
    assert denials[0].verdict == "DENY"
    assert denials[0].capability_id == "data_agent.run_sql"
    assert denials[0].basis == "out_of_allowlist"
    # No Action was ever built for it, so no id joins the record to the turn and
    # the trace says so instead of implying a causal link.
    assert denials[0].link is TraceLinkKind.SEQUENCE_WINDOW


def test_an_operator_rejection_closes_its_dispatch_as_rejected(tmp_path: Path) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(tmp_path, scripted=(("", (edit_proposal(),)), ("stopped", ())))
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, "edit it")

    trace = trace_of(app, session.session_id)
    dispatch = spans_of(trace, TraceSpanKind.CAPABILITY_DISPATCH)[0]
    assert dispatch.status is TraceSpanStatus.REJECTED
    assert dispatch.ended_by is TraceSpanBasis.APPROVAL_REJECTED
    assert dispatch.effect_state is None, "a rejected action was never dispatched"

    approval = spans_of(trace, TraceSpanKind.APPROVAL)[0]
    assert approval.status is TraceSpanStatus.REJECTED
    assert approval.disposition == "REJECT"
    assert approval.link is TraceLinkKind.ACTION_DIGEST
    assert approval.action_digest == dispatch.action_digest


def test_a_turn_the_log_never_closed_is_open_with_typed_gaps(tmp_path: Path) -> None:
    app = chat_app(tmp_path, scripted=(("", (edit_proposal(),)),))
    session, loop = open_session(app, DeferredApprovalGateway())
    result = loop.run_turn(session, "edit it")
    assert result.stop_reason == "approval_required"

    trace = trace_of(app, session.session_id)
    assert trace.state is TraceTurnState.OPEN
    assert trace.stop_reason is None
    assert trace.ended_sequence is None
    assert trace.spans[0].status is TraceSpanStatus.OPEN
    assert trace.spans[0].ended_by is TraceSpanBasis.OPEN_NO_TERMINAL_RECORD

    pending = [
        span for span in spans_of(trace, TraceSpanKind.APPROVAL)
    ][0]
    assert pending.status is TraceSpanStatus.OPEN
    assert pending.started_by is TraceSpanBasis.APPROVAL_PENDING_RECORDED
    assert pending.link is TraceLinkKind.TURN_ID

    gap_kinds = {gap.kind for gap in trace.gaps}
    assert gap_kinds == {
        TraceGapKind.TURN_OPEN,
        TraceGapKind.DISPATCH_UNRESOLVED,
        TraceGapKind.APPROVAL_UNRESOLVED,
    }


def test_an_undetermined_dispatch_is_undetermined_not_failed(tmp_path: Path) -> None:
    app = chat_app(tmp_path, scripted=(("", (read_proposal(),)), ("after", ())))
    session, loop = open_session(app, DeferredApprovalGateway())

    def explode(action: Any) -> Any:
        raise RuntimeError("connector exploded after dispatch")

    app.sandbox.execute = explode  # type: ignore[method-assign]
    result = loop.run_turn(session, "read it")
    assert result.stop_reason == "unknown_requires_review"

    trace = trace_of(app, session.session_id)
    dispatch = spans_of(trace, TraceSpanKind.CAPABILITY_DISPATCH)[0]
    assert dispatch.status is TraceSpanStatus.UNDETERMINED
    assert dispatch.ended_by is TraceSpanBasis.EFFECT_UNDETERMINED
    assert dispatch.effect_state == "UNKNOWN"
    undetermined = [
        gap for gap in trace.gaps if gap.kind is TraceGapKind.EFFECT_UNDETERMINED
    ]
    assert len(undetermined) == 1
    assert undetermined[0].subject == dispatch.action_id
    assert undetermined[0].sequence == dispatch.ended_sequence


def test_a_provider_failure_says_the_failing_invocation_has_no_durable_record(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path)
    app.provider = _FailingProvider(
        invocation_binding=app.provider.invocation_binding,
    )
    session, loop = open_session(app, DeferredApprovalGateway())
    result = loop.run_turn(session, "answer me")
    assert result.stop_reason == "provider_failure:RATE_LIMITED"

    trace = trace_of(app, session.session_id)
    assert trace.state is TraceTurnState.COMPLETE
    assert spans_of(trace, TraceSpanKind.MODEL_CALL) == []
    gaps = [
        gap for gap in trace.gaps if gap.kind is TraceGapKind.MODEL_CALL_NOT_RECORDED
    ]
    assert len(gaps) == 1
    assert "provider_failure:RATE_LIMITED" in gaps[0].detail
    assert "request_id" in gaps[0].detail


# --- honesty about a damaged or absent stream -------------------------------


def test_an_unknown_session_is_a_typed_error(tmp_path: Path) -> None:
    app = chat_app(tmp_path)
    session, _loop = open_session(app, DeferredApprovalGateway())

    with pytest.raises(TurnTraceNotFoundError, match="not in the durable stream"):
        build_turn_trace(
            tuple(app.store.read(session.task_id)),
            session_id="session-does-not-exist",
        )
    with pytest.raises(TurnTraceNotFoundError, match="no durable records"):
        build_turn_trace((), session_id=session.session_id)


def test_an_unknown_turn_is_a_typed_error(tmp_path: Path) -> None:
    app = chat_app(tmp_path, scripted=(("done", ()),))
    session, loop = open_session(app, DeferredApprovalGateway())
    loop.run_turn(session, "hello")

    with pytest.raises(TurnTraceNotFoundError, match="has no turn 'turn-nope'"):
        trace_of(app, session.session_id, "turn-nope")


def test_a_turn_that_never_started_cannot_be_projected(tmp_path: Path) -> None:
    """A stream whose turn markers were lost is not a turn, and says so."""

    app = chat_app(tmp_path)
    session, _loop = open_session(app, DeferredApprovalGateway())
    events = tuple(
        event
        for event in app.store.read(session.task_id)
        if event.event_type
        not in {TaskEventType.SESSION_TURN_STARTED, TaskEventType.SESSION_TURN_COMPLETED}
    )

    with pytest.raises(TurnTraceNotFoundError, match="no SESSION_TURN_STARTED"):
        build_turn_trace(events, session_id=session.session_id)


def test_a_malformed_or_unreadable_record_becomes_a_typed_gap(tmp_path: Path) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(tmp_path, scripted=(("", (read_proposal(),)), ("done", ())))
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, "read it")

    events = list(app.store.read(session.task_id))
    # Corrupt one interior payload and drop another interior record: the
    # projection must report both rather than fail or silently shorten.
    damaged_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type is TaskEventType.POLICY_DECIDED
    )
    events[damaged_index] = events[damaged_index].model_copy(
        update={"payload_json": "{not json"}
    )
    dropped = next(
        index
        for index, event in enumerate(events)
        if event.event_type is TaskEventType.SESSION_MESSAGE_RECORDED
        and event.sequence > events[damaged_index].sequence
    )
    del events[dropped]

    trace = build_turn_trace(tuple(events), session_id=session.session_id)
    gap_kinds = {gap.kind for gap in trace.gaps}
    assert TraceGapKind.MALFORMED_EVENT in gap_kinds
    assert TraceGapKind.SEQUENCE_GAP in gap_kinds
    assert trace.records_scanned == len(events)
    # The record the projection could not decode backs no span...
    assert spans_of(trace, TraceSpanKind.POLICY_DECISION) == []
    # ...while the rest of the turn is still projected rather than abandoned: the
    # dispatch is real (a receipt exists for it), and the missing record is a gap.
    assert [
        span.status for span in spans_of(trace, TraceSpanKind.CAPABILITY_DISPATCH)
    ] == [TraceSpanStatus.COMPLETED]


def test_a_turn_with_an_unreadable_start_record_is_not_fabricated(
    tmp_path: Path,
) -> None:
    app = chat_app(tmp_path, scripted=(("done", ()),))
    session, loop = open_session(app, DeferredApprovalGateway())
    loop.run_turn(session, "hello")
    events = list(app.store.read(session.task_id))
    index = next(
        index
        for index, event in enumerate(events)
        if event.event_type is TaskEventType.SESSION_TURN_STARTED
    )
    events[index] = events[index].model_copy(update={"payload_json": "{not json"})

    with pytest.raises(TurnTraceNotFoundError) as excinfo:
        build_turn_trace(tuple(events), session_id=session.session_id)
    assert "unreadable start record" in str(excinfo.value)


# --- purity -----------------------------------------------------------------


def test_the_projection_writes_nothing_and_needs_no_authority(tmp_path: Path) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(tmp_path, scripted=(("", (read_proposal(),)), ("done", ())))
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, "read it")

    before = tuple(
        event.model_dump(mode="json") for event in app.store.read(session.task_id)
    )
    sequence_before = app.surface_current_sequence(session.task_id)

    first = trace_of(app, session.session_id)
    second = trace_of(app, session.session_id, first.turn_id)

    after = tuple(
        event.model_dump(mode="json") for event in app.store.read(session.task_id)
    )
    assert before == after, "a trace read must not append, seal or rewrite a record"
    assert app.surface_current_sequence(session.task_id) == sequence_before
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_the_default_turn_is_the_most_recently_started_one(tmp_path: Path) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(tmp_path, scripted=(("first", ()), ("second", ())))
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, "one")
    first_turn = trace_of(app, session.session_id).turn_id

    loop = app.restore_chat_session(session.session_id, NonInteractiveDenyGateway())[1]
    loop.run_turn(session, "two")
    second = trace_of(app, session.session_id)

    assert second.turn_id != first_turn
    assert second.stop_reason == "completed"
    assert trace_of(app, session.session_id, first_turn).turn_id == first_turn


# --- the content boundary ---------------------------------------------------


def test_the_trace_carries_no_prompt_completion_preview_or_credential(
    tmp_path: Path,
) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(tmp_path, scripted=(("", (edit_proposal(),)), (_COMPLETION, ())))
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, _PROMPT)

    # The premises: the durable records really do carry the text the trace must
    # not carry, so this test cannot pass by having nothing to leak.
    durable = json.dumps(
        [event.model_dump(mode="json") for event in app.store.read(session.task_id)]
    )
    assert _PROMPT in durable
    pending_preview = any(
        "preview" in (event.decoded_payload() or {})
        for event in app.store.read(session.task_id)
    )
    if not pending_preview:
        assert "new_string" in durable, "the arguments payload is in the durable log"

    rendered = json.dumps(
        trace_of(app, session.session_id).model_dump(mode="json")
    )
    for secret in (_PROMPT, _COMPLETION, _CREDENTIAL, "new_string", "changed\\n"):
        assert secret not in rendered, secret


def _string_leaves(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        found: list[tuple[str, str]] = []
        for key, item in value.items():
            found.extend(_string_leaves(item, f"{path}.{key}" if path else str(key)))
        return found
    if isinstance(value, (list, tuple)):
        found = []
        for index, item in enumerate(value):
            found.extend(_string_leaves(item, f"{path}[{index}]"))
        return found
    return []


def test_no_trace_field_can_carry_content(tmp_path: Path) -> None:
    """The structural half of the leak test: no field has room for text.

    Every string leaf of a real projection is a durable id, an enum, a timestamp
    or a digest - nothing longer than a 64-hex digest - and no field is named
    after content. A prompt, a completion or a message body has nowhere to go.
    """

    from agent_os_contracts import TraceGap, TraceSpan

    app = chat_app(tmp_path, scripted=(("", (read_proposal(),)), (_COMPLETION, ())))
    session, loop = open_session(app, DeferredApprovalGateway())
    loop.run_turn(session, _PROMPT)

    assert not set(TraceSpan.model_fields) & _SPAN_FIELDS
    assert not set(TraceGap.model_fields) & _SPAN_FIELDS
    assert not set(TurnTrace.model_fields) & _SPAN_FIELDS

    leaves = _string_leaves(trace_of(app, session.session_id).model_dump(mode="json"))
    assert leaves, "the walk itself must see the projection"
    for path, value in leaves:
        assert len(value) <= 80, (path, value)
        assert path.rsplit(".", 1)[-1] not in _SPAN_FIELDS, path


def test_a_message_payload_that_looks_like_a_trace_cannot_leak_through(
    tmp_path: Path,
) -> None:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(tmp_path, scripted=(("", (read_proposal(),)), (_COMPLETION, ())))
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, _PROMPT)

    # Rewrite a continuation checkpoint to carry hostile extra keys, then project
    # again: a record the projection does not read cannot push content through.
    events = list(app.store.read(session.task_id))
    hostile = False
    for index, event in enumerate(events):
        if event.event_type is not TaskEventType.SESSION_MESSAGE_RECORDED:
            continue
        payload = event.decoded_payload()
        payload["api_key"] = _CREDENTIAL
        payload["user_text"] = _PROMPT
        if isinstance(payload.get("message"), dict):
            payload["message"]["content"] = _COMPLETION
        events[index] = event.model_copy(
            update={"payload_json": json.dumps(payload, sort_keys=True)}
        )
        hostile = True
    assert hostile

    rendered = json.dumps(
        build_turn_trace(
            tuple(events), session_id=session.session_id
        ).model_dump(mode="json")
    )
    for secret in (_PROMPT, _COMPLETION, _CREDENTIAL):
        assert secret not in rendered, secret


# --- the public read path ---------------------------------------------------


class _TraceServer:
    def __init__(self, app: AgentOSApplication, base: str, token: str) -> None:
        self.app = app
        self.base = base
        self.token = token

    def get(self, path: str, *, authenticated: bool = True) -> tuple[int, Any]:
        request = urllib.request.Request(
            self.base + path,
            method="GET",
            headers={
                "Authorization": (
                    f"Bearer {self.token}" if authenticated else "Bearer wrong"
                )
            },
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def post(self, path: str) -> tuple[int, Any]:
        request = urllib.request.Request(
            self.base + path,
            method="POST",
            data=b"{}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


@pytest.fixture
def trace_server(tmp_path: Path) -> Generator[_TraceServer, None, None]:
    from agent_os_core import NonInteractiveDenyGateway

    app = chat_app(
        tmp_path,
        scripted=(
            ("", (read_proposal(),)),
            ("", (edit_proposal(),)),
            (_COMPLETION, ()),
        ),
    )
    session, loop = open_session(app, NonInteractiveDenyGateway())
    loop.run_turn(session, _PROMPT)
    app.trace_session_id = session.session_id  # type: ignore[attr-defined]

    token = "test-local-token"
    handler = type(
        "TestTraceHandler",
        (Handler,),
        {
            "application": app,
            "local_token": token,
            "surface_routes": SurfaceRoutes(app.surface, token),
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _TraceServer(
            app, f"http://127.0.0.1:{server.server_address[1]}", token
        )
    finally:
        server.shutdown()
        server.server_close()


def test_the_trace_route_serves_the_typed_projection(
    trace_server: _TraceServer,
) -> None:
    session_id = trace_server.app.trace_session_id  # type: ignore[attr-defined]

    status, body = trace_server.get(f"/v1/surface/sessions/{session_id}/trace")

    assert status == 200, body
    assert set(body) == {"trace"}
    trace = TurnTrace.model_validate(body["trace"])
    assert trace.session_id == session_id
    assert "CAPABILITY_DISPATCH" in kinds(trace)
    # The route serves the projection the application function builds, not a
    # second implementation of it.
    assert trace.model_dump(mode="json") == trace_server.app.surface_turn_trace(
        session_id
    ).model_dump(mode="json")
    assert _PROMPT not in json.dumps(body)


def test_the_trace_route_accepts_an_explicit_turn_and_rejects_a_repeat(
    trace_server: _TraceServer,
) -> None:
    session_id = trace_server.app.trace_session_id  # type: ignore[attr-defined]
    projected = trace_server.app.surface_turn_trace(session_id)

    status, body = trace_server.get(
        f"/v1/surface/sessions/{session_id}/trace?turn_id={projected.turn_id}"
    )
    assert status == 200, body
    assert body["trace"]["turn_id"] == projected.turn_id

    status, body = trace_server.get(
        f"/v1/surface/sessions/{session_id}/trace"
        f"?turn_id={projected.turn_id}&turn_id={projected.turn_id}"
    )
    assert status == 422, body
    assert "turn_id" in body["message"]


def test_the_trace_route_404s_an_unknown_session_and_turn(
    trace_server: _TraceServer,
) -> None:
    status, body = trace_server.get("/v1/surface/sessions/session-nope/trace")
    assert status == 404, body
    assert body["error"] == "SurfaceSessionNotFound"

    session_id = trace_server.app.trace_session_id  # type: ignore[attr-defined]
    status, body = trace_server.get(
        f"/v1/surface/sessions/{session_id}/trace?turn_id=turn-nope"
    )
    assert status == 404, body
    assert body["error"] == "TurnTraceNotFoundError"
    assert "turn-nope" in body["message"]


def test_the_trace_route_requires_the_local_token(trace_server: _TraceServer) -> None:
    session_id = trace_server.app.trace_session_id  # type: ignore[attr-defined]

    status, body = trace_server.get(
        f"/v1/surface/sessions/{session_id}/trace", authenticated=False
    )
    assert status == 401, body
    assert body == {"error": "local_authentication_failed"}


def test_the_trace_route_is_read_only(trace_server: _TraceServer) -> None:
    """The read surface adds no write path: POST to it is not a route."""

    session_id = trace_server.app.trace_session_id  # type: ignore[attr-defined]

    status, body = trace_server.post(f"/v1/surface/sessions/{session_id}/trace")
    assert status == 404, body
    assert body == {"error": "surface_route_not_found"}


def test_the_trace_route_does_not_grow_a_trailing_slash_route(
    trace_server: _TraceServer,
) -> None:
    session_id = trace_server.app.trace_session_id  # type: ignore[attr-defined]

    status, _body = trace_server.get(f"/v1/surface/sessions/{session_id}/trace/")
    assert status == 404
