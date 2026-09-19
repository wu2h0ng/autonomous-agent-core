"""What the durable log holds for a model call that failed.

Before this evidence existed, a turn that stopped on a provider failure left one
marker: ``SESSION_TURN_COMPLETED.stop_reason = "provider_failure:<CODE>"``. That
names the failure class and nothing else - not which call failed, not which
attempt out of how many, not when, not whether the attempt had already streamed
output, and not the message the operator read. A per-turn trace projecting the
log therefore had to report that the failing model call was not recorded at all.

These cases pin the replacement: one durable, typed ``PROVIDER_ATTEMPT_FAILED``
record per failed attempt, carrying exactly what an audit needs and nothing the
metrics precedent excludes (no prompt, no completion, no credential), bounded so
a retry storm cannot grow the log without limit, and unable to change what the
log says about the turn itself - ``SESSION_TURN_STARTED`` / ``SESSION_TURN_COMPLETED``
stay the only turn delimiters.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from agent_os_contracts import (
    ProviderAttemptFailure,
    ProviderErrorCode,
    ProviderFailure,
    ProviderRequest,
    TaskEventDraft,
    TaskEventType,
)
from agent_os_core import (
    AgentLoopConfig,
    AutoApproveGateway,
    DeterministicProvider,
    InvalidTransitionError,
    SessionProjectionError,
)
from apps.api_server.app import AgentOSApplication

_PROMPT = "PROMPT-MARKER-do-not-store-this"
_COMPLETION = "COMPLETION-MARKER-do-not-store-this"
_CREDENTIAL = "sk-attempt-evidence-DEADBEEF"

_ATTEMPT_EVENT = TaskEventType.PROVIDER_ATTEMPT_FAILED
_TURN_STARTED = TaskEventType.SESSION_TURN_STARTED
_TURN_COMPLETED = TaskEventType.SESSION_TURN_COMPLETED

# The complete field set of a durable attempt record: ids, counters, a failure
# class, two booleans, a bounded message and a timing. No prompt, no completion.
_ATTEMPT_FIELDS = frozenset(
    {
        "schema_version",
        "attempt_failure_id",
        "request_id",
        "node_id",
        "task_id",
        "run_id",
        "session_id",
        "turn_id",
        "attempt_index",
        "attempts_planned",
        "code",
        "retryable",
        "emitted_output",
        "provider_profile_id",
        "model_id",
        "safe_message",
        "latency_ms",
        "started_at",
    }
)


class _FailingProvider:
    """A typed ProviderPort that returns a chosen failure for every attempt.

    ``emitted_before_failure`` streams one text delta before failing, which is the
    case the adapter's own rule refuses to replay ("a stream that has already
    emitted a delta is never retried").
    """

    def __init__(
        self,
        binding: Any,
        *,
        code: ProviderErrorCode = ProviderErrorCode.UNAVAILABLE,
        retryable: bool = True,
        message: str = "provider unavailable",
        emitted_before_failure: bool = False,
    ) -> None:
        self._binding = binding
        self._code = code
        self._retryable = retryable
        self._message = message
        self._emitted_before_failure = emitted_before_failure
        self.calls = 0

    @property
    def invocation_binding(self) -> Any:
        return self._binding

    def complete(self, request: ProviderRequest) -> ProviderFailure:
        return self.complete_streaming(request)

    def complete_streaming(
        self,
        request: ProviderRequest,
        *,
        on_text_delta: Any = None,
        on_reasoning_delta: Any = None,
    ) -> ProviderFailure:
        self.calls += 1
        if self._emitted_before_failure and on_text_delta is not None:
            on_text_delta("partial answer")
        return ProviderFailure(
            failure_id=f"failure-{self.calls}",
            request_id=request.request_id,
            code=self._code,
            retryable=self._retryable,
            safe_message=self._message,
            occurred_at=datetime.now(timezone.utc),
        )


def _open_app(root: Path) -> AgentOSApplication:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    return AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)


def _failing_turn(
    root: Path,
    *,
    code: ProviderErrorCode = ProviderErrorCode.UNAVAILABLE,
    retryable: bool = True,
    max_provider_retries: int = 2,
    emitted_before_failure: bool = False,
    message: str = "provider unavailable",
) -> tuple[AgentOSApplication, Any, Any, _FailingProvider]:
    app = _open_app(root)
    provider = _FailingProvider(
        app.provider.invocation_binding,
        code=code,
        retryable=retryable,
        message=message,
        emitted_before_failure=emitted_before_failure,
    )
    app.provider = cast(Any, provider)
    app.provider_configured = True
    session, loop = app.open_chat_session(
        "failing",
        AutoApproveGateway(),
        loop_config=AgentLoopConfig(max_provider_retries=max_provider_retries),
    )
    loop._text_delta_sink = lambda _chunk: None
    return app, session, loop.run_turn(session, _PROMPT), provider


def _attempt_records(app: AgentOSApplication, task_id: str) -> list[dict[str, Any]]:
    return [
        event.decoded_payload()
        for event in app.tasks._event_store.read(task_id)
        if event.event_type is _ATTEMPT_EVENT
    ]


def _attempts(app: AgentOSApplication, task_id: str) -> list[dict[str, Any]]:
    return [
        payload["provider_attempt_failure"]
        for payload in _attempt_records(app, task_id)
    ]


def _started_turn_id(app: AgentOSApplication, task_id: str) -> str:
    return json.loads(
        next(
            event.payload_json
            for event in app.tasks._event_store.read(task_id)
            if event.event_type is _TURN_STARTED
        )
    )["turn_id"]


def test_a_failed_model_call_leaves_a_durable_attempt_record(tmp_path: Path) -> None:
    # Before this evidence existed the turn left no provider-scoped record at all:
    # the log said a turn stopped on provider_failure:UNAVAILABLE and named
    # neither the call, the attempt, the timing nor the failure's message.
    app, session, result, provider = _failing_turn(tmp_path)

    assert result.stop_reason == "provider_failure:UNAVAILABLE"
    assert provider.calls == 3

    records = _attempts(app, session.task_id)
    assert [record["attempt_index"] for record in records] == [0, 1, 2]
    first = records[0]
    assert first["attempts_planned"] == 3
    assert first["code"] == ProviderErrorCode.UNAVAILABLE.value
    assert first["retryable"] is True
    assert first["emitted_output"] is False
    assert first["safe_message"] == "provider unavailable"
    assert first["latency_ms"] >= 0.0
    assert first["turn_id"] == _started_turn_id(app, session.task_id)
    assert first["node_id"] == f"{first['turn_id']}-step-1"
    assert first["task_id"] == session.task_id
    assert first["run_id"] == session.run_id
    assert first["session_id"] == session.session_id


@pytest.mark.parametrize(
    ("code", "retryable", "expected_attempts"),
    [
        (ProviderErrorCode.RATE_LIMITED, True, 3),
        (ProviderErrorCode.UNAVAILABLE, True, 3),
        (ProviderErrorCode.TIMEOUT, True, 3),
        (ProviderErrorCode.REFUSED, False, 1),
        (ProviderErrorCode.AUTHENTICATION_FAILED, False, 1),
        (ProviderErrorCode.MALFORMED, False, 1),
    ],
)
def test_every_failure_class_records_its_own_code_and_retryability(
    tmp_path: Path,
    code: ProviderErrorCode,
    retryable: bool,
    expected_attempts: int,
) -> None:
    app, session, result, provider = _failing_turn(
        tmp_path, code=code, retryable=retryable
    )

    assert result.stop_reason == f"provider_failure:{code.value}"
    assert provider.calls == expected_attempts
    records = _attempts(app, session.task_id)
    # One record per attempt the loop actually made: a retryable failure is
    # retried and leaves its own evidence each time, a terminal one stops here.
    assert len(records) == expected_attempts, records
    assert {record["code"] for record in records} == {code.value}
    assert {record["retryable"] for record in records} == {retryable}


def test_a_failed_attempt_after_streamed_output_is_marked_as_emitting_output(
    tmp_path: Path,
) -> None:
    # The adapter will not replay a stream that already produced output, and the
    # record has to say so: an operator asking "had the model already said
    # something before this failed?" reads it off the event, not the terminal.
    app, session, _result, _provider = _failing_turn(
        tmp_path,
        code=ProviderErrorCode.TIMEOUT,
        retryable=True,
        emitted_before_failure=True,
        message="provider request timed out",
    )

    records = _attempts(app, session.task_id)
    assert records
    assert all(record["emitted_output"] is True for record in records)


def test_a_failed_attempt_without_output_says_so(tmp_path: Path) -> None:
    app, session, _result, _provider = _failing_turn(tmp_path)

    records = _attempts(app, session.task_id)
    assert records
    assert all(record["emitted_output"] is False for record in records)


def test_the_attempt_record_carries_no_prompt_completion_or_credential(
    tmp_path: Path,
) -> None:
    # The metrics precedent: the attempt evidence excludes everything a user typed
    # and everything the model said, and a credential echoed back by a provider
    # must not land in a file that outlives the session.
    app, session, result, _provider = _failing_turn(
        tmp_path,
        code=ProviderErrorCode.REFUSED,
        retryable=False,
        message=f"provider refused: {_COMPLETION}",
    )

    payloads = [
        event.payload_json
        for event in app.tasks._event_store.read(session.task_id)
        if event.event_type is _ATTEMPT_EVENT
    ]
    assert payloads
    joined = "\n".join(payloads)
    assert _PROMPT not in joined
    assert _CREDENTIAL not in joined
    assert not any(part in joined for part in (_CREDENTIAL, _CREDENTIAL[3:]))
    for record in _attempts(app, session.task_id):
        assert set(record) == _ATTEMPT_FIELDS, set(record) ^ _ATTEMPT_FIELDS
    # The operator still gets the message the provider produced.
    assert result.text == f"provider refused: {_COMPLETION}"


def test_a_failed_attempt_record_does_not_disturb_the_turn_delimiters(
    tmp_path: Path,
) -> None:
    app, session, _result, _provider = _failing_turn(tmp_path)
    events = app.tasks._event_store.read(session.task_id)

    started = [event for event in events if event.event_type is _TURN_STARTED]
    completed = [event for event in events if event.event_type is _TURN_COMPLETED]
    assert len(started) == 1
    assert len(completed) == 1
    assert started[0].sequence < completed[0].sequence
    # Every attempt record sits strictly between them and is not a delimiter, so
    # the uncommitted-turn computation (started - completed) is unaffected.
    attempt_events = [event for event in events if event.event_type is _ATTEMPT_EVENT]
    assert attempt_events
    for event in attempt_events:
        assert started[0].sequence < event.sequence < completed[0].sequence
    assert _open_turns(events) == set()
    assert app.surface_has_uncommitted_turn(session.session_id) is False


def test_the_session_projection_is_unchanged_by_the_attempt_records(
    tmp_path: Path,
) -> None:
    app, session, _result, _provider = _failing_turn(tmp_path)

    projected = app.tasks.project_session(session.task_id, session.session_id)
    # The turn is closed and the session is simply idle: an attempt record is
    # evidence about a turn, never a state of it.
    assert projected.resumable_turn_id is None
    assert projected.pending_continuation is None
    assert projected.closed is False
    assert [message.role.value for message in projected.history] == ["SYSTEM", "USER"]


def test_the_attempt_record_cannot_use_the_generic_write_path(tmp_path: Path) -> None:
    # The rule PROVIDER_RESPONDED follows: protected truth is written by its typed
    # writer or not at all, so no second write path can appear beside it.
    app, session, _result, _provider = _failing_turn(tmp_path)

    with pytest.raises(InvalidTransitionError):
        app.tasks.append_event(
            session.task_id,
            _ATTEMPT_EVENT,
            {"session_id": session.session_id},
        )


def test_the_typed_writer_rejects_a_foreign_binding(tmp_path: Path) -> None:
    app, session, _result, _provider = _failing_turn(tmp_path)

    payload = dict(_attempts(app, session.task_id)[0])
    payload["run_id"] = "run-not-this-one"
    with pytest.raises(InvalidTransitionError):
        app.tasks.record_provider_attempt_failure(
            session.task_id, ProviderAttemptFailure.model_validate(payload)
        )


def test_a_failing_attempt_record_does_not_fail_the_turn(tmp_path: Path) -> None:
    # Evidence about a failure must never be worse than the failure. With the
    # write path broken the turn still ends truthfully, with the same stop reason,
    # and the failure still reaches the caller.
    app = _open_app(tmp_path)
    app.provider = cast(Any, _FailingProvider(app.provider.invocation_binding))
    app.provider_configured = True

    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("storage is gone")

    app.tasks.record_provider_attempt_failure = _explode  # type: ignore[method-assign]
    session, loop = app.open_chat_session(
        "broken",
        AutoApproveGateway(),
        loop_config=AgentLoopConfig(max_provider_retries=1),
    )
    result = loop.run_turn(session, _PROMPT)

    assert result.stop_reason == "provider_failure:UNAVAILABLE"
    assert _attempt_records(app, session.task_id) == []
    assert (
        len(
            [
                event
                for event in app.tasks._event_store.read(session.task_id)
                if event.event_type is _TURN_COMPLETED
            ]
        )
        == 1
    )


def test_a_retry_storm_cannot_grow_the_log_without_bound(tmp_path: Path) -> None:
    # The loop makes max_provider_retries + 1 attempts; the product default is 3.
    # A session configured with an absurd retry budget is still bounded, and the
    # turn still ends on the same failure.
    app, session, result, provider = _failing_turn(tmp_path, max_provider_retries=40)

    assert provider.calls == 41
    assert result.stop_reason == "provider_failure:UNAVAILABLE"
    records = _attempts(app, session.task_id)
    assert len(records) == 16, len(records)
    assert [record["attempt_index"] for record in records] == list(range(16))
    # The records say how many attempts the turn planned, so a bounded log is
    # still self-describing rather than silently short.
    assert {record["attempts_planned"] for record in records} == {41}


def test_a_malformed_durable_attempt_record_stops_the_projection(
    tmp_path: Path,
) -> None:
    # The session projection is the strict reader of session-scoped records: one it
    # cannot trust must fail closed instead of being silently ignored.
    app, session, _result, _provider = _failing_turn(tmp_path)
    store = app.tasks._event_store
    aggregate = app.tasks.get_task(session.task_id)
    draft = TaskEventDraft.build(
        event_id="event:malformed-attempt",
        task_id=session.task_id,
        event_type=_ATTEMPT_EVENT,
        payload={
            "session_id": session.session_id,
            "turn_id": "turn-other",
            "provider_attempt_failure": _attempts(app, session.task_id)[0],
        },
        occurred_at=datetime.now(timezone.utc),
        correlation_id=session.run_id,
        causation_id=aggregate.last_event_id,
    )
    store.append(
        session.task_id,
        expected_sequence=aggregate.sequence,
        drafts=(draft,),
    )

    with pytest.raises(SessionProjectionError):
        app.tasks.project_session(session.task_id, session.session_id)


def test_a_successful_turn_writes_no_attempt_record(tmp_path: Path) -> None:
    # Guard the other direction: a turn whose call succeeds writes the response
    # record it always did, and no attempt-failure record at all.
    app = _open_app(tmp_path)
    app.provider = DeterministicProvider(
        text="done",
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    session, loop = app.open_chat_session("ok", AutoApproveGateway())
    result = loop.run_turn(session, "hello")

    assert result.stop_reason == "completed"
    assert _attempt_records(app, session.task_id) == []
    assert [
        event.event_type
        for event in app.tasks._event_store.read(session.task_id)
        if event.event_type is TaskEventType.PROVIDER_RESPONDED
    ] == [TaskEventType.PROVIDER_RESPONDED]


def test_the_log_answers_which_call_failed_when_and_after_how_many_attempts(
    tmp_path: Path,
) -> None:
    # The whole point: the durable log, on its own, answers the audit question -
    # which model call, when, after how many attempts, and why - without the
    # adapter's operator log, which is opt-in and off by default.
    app, session, _result, _provider = _failing_turn(tmp_path)
    events = app.tasks._event_store.read(session.task_id)
    attempts = [
        (event, event.decoded_payload()["provider_attempt_failure"])
        for event in events
        if event.event_type is _ATTEMPT_EVENT
    ]

    assert len(attempts) == 3
    turn_id = _started_turn_id(app, session.task_id)
    for _event, record in attempts:
        assert record["turn_id"] == turn_id
        assert record["node_id"] == f"{turn_id}-step-1"
        assert record["provider_profile_id"] == "provider-profile:default"
        assert record["model_id"] == "deterministic-v1"
    assert [record["attempt_index"] for _event, record in attempts] == [0, 1, 2]
    assert attempts[0][0].occurred_at <= attempts[-1][0].occurred_at
    assert attempts[0][1]["started_at"] <= attempts[-1][1]["started_at"]


def test_an_over_long_failure_message_is_bounded_not_dropped() -> None:
    # The ceiling must bound a message, never lose the attempt: a record that is
    # refused at construction would silently drop the evidence the operator needs.
    from agent_os_contracts.provider import _PROVIDER_ATTEMPT_MESSAGE_MAX_CHARS

    oversize = "x" * (_PROVIDER_ATTEMPT_MESSAGE_MAX_CHARS * 3)
    record = ProviderAttemptFailure(
        attempt_failure_id="failure-1",
        request_id="request-1",
        node_id="turn-1-step-1",
        task_id="task-1",
        run_id="run-1",
        session_id="session-1",
        turn_id="turn-1",
        attempt_index=0,
        attempts_planned=1,
        code=ProviderErrorCode.UNAVAILABLE,
        retryable=False,
        emitted_output=False,
        provider_profile_id="provider-profile:default",
        model_id="stub-model",
        safe_message=oversize,
        latency_ms=1.0,
        started_at=datetime.now(timezone.utc),
    )

    assert len(record.safe_message) == _PROVIDER_ATTEMPT_MESSAGE_MAX_CHARS


def test_an_attempt_index_outside_the_planned_attempts_is_rejected() -> None:
    with pytest.raises(ValueError):
        ProviderAttemptFailure(
            attempt_failure_id="failure-1",
            request_id="request-1",
            node_id="turn-1-step-1",
            task_id="task-1",
            run_id="run-1",
            session_id="session-1",
            turn_id="turn-1",
            attempt_index=3,
            attempts_planned=3,
            code=ProviderErrorCode.UNAVAILABLE,
            retryable=False,
            emitted_output=False,
            provider_profile_id="provider-profile:default",
            model_id="stub-model",
            safe_message="provider unavailable",
            latency_ms=1.0,
            started_at=datetime.now(timezone.utc),
        )


def _open_turns(events: Any) -> set[str]:
    """The uncommitted-turn computation, over the same two delimiter types."""

    started: set[str] = set()
    completed: set[str] = set()
    for event in events:
        if event.event_type not in {_TURN_STARTED, _TURN_COMPLETED}:
            continue
        turn_id = json.loads(event.payload_json).get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            continue
        if event.event_type is _TURN_STARTED:
            started.add(turn_id)
        else:
            completed.add(turn_id)
    return started - completed
