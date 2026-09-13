from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from importlib import import_module
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Generator, cast

import pytest
from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ActionReceipt,
    PolicyDecision,
    ProviderErrorCode,
    ProviderFailure,
    ProviderMessageRole,
    ProviderToolProposal,
    PolicyVerdict,
    RunStatus,
    TaskEventType,
    TaskEventDraft,
)
from agent_os_core import (
    AgentLoopConfig,
    AutoApproveGateway,
    CapabilityBroker,
    CapabilityDenied,
    DeterministicProvider,
    ExecutionLease,
    PolicyInput,
    InvalidTransitionError,
    SQLiteTaskEventStore,
    SessionProjector,
)
from agent_os_core.action_pipeline import ActionPipeline
from apps.api_server.app import AgentOSApplication
from apps.api_server.server import build_server
from domain_packs.developer_agent import WorkspaceSandbox


def _test_claim(run_id: str) -> ExecutionLease:
    return ExecutionLease(
        run_id=run_id,
        owner="test:worker",
        fence=1,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


def _held_claim(app: Any, run_id: str) -> ExecutionLease:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    fence = app.store.acquire_lease(run_id, "test:worker", expiry.isoformat())
    return ExecutionLease(
        run_id=run_id,
        owner="test:worker",
        fence=fence,
        expires_at=expiry,
    )


def _proposal(
    call_id: str, capability_id: str, arguments: dict
) -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=call_id,
        capability_id=capability_id,
        arguments_json=json.dumps(arguments),
    )


def _prepare_workspace(root: Path) -> None:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")
    (root / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'stable\\n'\n",
        encoding="utf-8",
    )


def _chat_app(root: Path, scripted=()) -> AgentOSApplication:
    _prepare_workspace(root)
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=scripted,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _event_types(app: AgentOSApplication, task_id: str) -> list[TaskEventType]:
    return [event.event_type for event in app.tasks._event_store.read(task_id)]


def _tool_messages(loop) -> list:
    return [
        message for message in loop.history if message.role is ProviderMessageRole.TOOL
    ]


class _DispatchCountingSandbox(WorkspaceSandbox):
    def __init__(self, root: Path, *, idempotency_store: object) -> None:
        super().__init__(root, idempotency_store=idempotency_store)
        self.dispatch_count = 0

    def _dispatch(
        self,
        capability_id: str,
        args: dict[str, object],
        action_key: str,
    ) -> dict[str, object]:
        self.dispatch_count += 1
        return super()._dispatch(capability_id, args, action_key)


class _ReceiptCrash(BaseException):
    pass


def test_multi_turn_edit_applies_and_records_governance(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            (
                "",
                (
                    _proposal(
                        "call-2",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "fixed",
                        },
                    ),
                ),
            ),
            ("edit applied", ()),
        ),
    )
    session, loop = app.open_chat_session("fix fixture", AutoApproveGateway())
    result = loop.run_turn(session, "please fix the fixture")

    assert result.stop_reason == "completed"
    assert result.text == "edit applied"
    assert result.steps == 3
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"

    tool_messages = _tool_messages(loop)
    assert [message.tool_call_id for message in tool_messages] == ["call-1", "call-2"]
    edit_result = json.loads(tool_messages[1].content)
    assert "sha256" in edit_result

    events = _event_types(app, session.task_id)
    assert TaskEventType.SESSION_TURN_STARTED in events
    assert TaskEventType.SESSION_TURN_COMPLETED in events
    assert TaskEventType.ACTION_PROPOSED in events
    assert TaskEventType.POLICY_DECIDED in events
    assert TaskEventType.ACTION_RECEIPT_RECORDED in events
    projected = SessionProjector(app.store).project(session.task_id, session.session_id)
    assert projected.history == loop.history


def test_known_action_outcome_replay_writes_no_second_policy_or_receipt(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "fixed\n",
                        },
                    ),
                ),
            ),
            ("done", ()),
        ),
    )
    session, loop = app.open_chat_session("replay", AutoApproveGateway())
    loop.run_turn(session, "edit")
    events = app.store.read(session.task_id)
    action = ActionContract.model_validate(
        next(
            event.decoded_payload()["action"]
            for event in events
            if event.event_type is TaskEventType.ACTION_PROPOSED
        )
    )
    original_receipt = ActionReceipt.model_validate(
        next(
            event.decoded_payload()["receipt"]
            for event in events
            if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
        )
    )
    before_policy = sum(
        event.event_type is TaskEventType.POLICY_DECIDED for event in events
    )
    before_receipts = sum(
        event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED for event in events
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(app.sandbox, app.correction),
        app.policy,
        app.correction,
        app._chat_grants(),
    )

    replayed = pipeline.execute(
        action,
        app.principal,
        capability_spec=app.sandbox.specs()[action.capability_id],
        record_artifacts=False,
        execution_claim=_held_claim(app, action.run_id),
    )

    after = app.store.read(session.task_id)
    assert replayed.receipt == original_receipt
    assert (
        sum(event.event_type is TaskEventType.POLICY_DECIDED for event in after)
        == before_policy
    )
    assert (
        sum(
            event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED for event in after
        )
        == before_receipts
    )


def test_outcome_only_recovery_appends_original_receipt_without_second_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
        ),
    )
    sandbox = _DispatchCountingSandbox(tmp_path, idempotency_store=app.store)
    app.sandbox = sandbox
    session, loop = app.open_chat_session("outcome only", AutoApproveGateway())
    original_record = app.tasks._record_action_receipt

    def crash_before_task_receipt(*_args: object, **_kwargs: object) -> None:
        raise _ReceiptCrash("outcome sealed before Task receipt")

    monkeypatch.setattr(
        app.tasks,
        "_record_action_receipt",
        crash_before_task_receipt,
    )
    with pytest.raises(_ReceiptCrash, match="outcome sealed"):
        loop.run_turn(session, "search")
    monkeypatch.setattr(app.tasks, "_record_action_receipt", original_record)

    events = app.store.read(session.task_id)
    action = ActionContract.model_validate(
        next(
            event.decoded_payload()["action"]
            for event in events
            if event.event_type is TaskEventType.ACTION_PROPOSED
        )
    )
    assert sandbox.dispatch_count == 1
    assert not any(
        event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED for event in events
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(sandbox, app.correction),
        app.policy,
        app.correction,
        app._chat_grants(),
    )

    replay = pipeline.execute(
        action,
        app.principal,
        capability_spec=sandbox.specs()[action.capability_id],
        record_artifacts=False,
        execution_claim=_held_claim(app, action.run_id),
    )

    assert replay.receipt.receipt_id
    assert sandbox.dispatch_count == 1
    after = app.store.read(session.task_id)
    assert sum(event.event_type is TaskEventType.POLICY_DECIDED for event in after) == 1
    assert (
        sum(
            event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED for event in after
        )
        == 1
    )


def test_task_receipt_store_read_failure_is_typed_unknown_before_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (_proposal("call-1", "workspace.search", {"mode": "ls"}),),
            ),
            ("done", ()),
        ),
    )
    session, loop = app.open_chat_session("task read failure", AutoApproveGateway())
    loop.run_turn(session, "search")
    events = app.store.read(session.task_id)
    action = ActionContract.model_validate(
        next(
            event.decoded_payload()["action"]
            for event in events
            if event.event_type is TaskEventType.ACTION_PROPOSED
        )
    )
    before_policy = sum(
        event.event_type is TaskEventType.POLICY_DECIDED for event in events
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(app.sandbox, app.correction),
        app.policy,
        app.correction,
        app._chat_grants(),
    )

    def fail_task_read(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("transient Task store read failure")

    monkeypatch.setattr(app.tasks, "_find_exact_action_receipt", fail_task_read)
    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW") as caught:
        pipeline.execute(
            action,
            app.principal,
            capability_spec=app.sandbox.specs()[action.capability_id],
            record_artifacts=False,
            execution_claim=_held_claim(app, action.run_id),
        )

    assert caught.value.__class__.__name__ == "CapabilityEffectUnknown"
    assert (
        sum(
            event.event_type is TaskEventType.POLICY_DECIDED
            for event in app.store.read(session.task_id)
        )
        == before_policy
    )


def test_outcome_only_policy_codec_failure_is_typed_unknown_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (_proposal("call-1", "workspace.search", {"mode": "ls"}),),
            ),
        ),
    )
    sandbox = _DispatchCountingSandbox(tmp_path, idempotency_store=app.store)
    app.sandbox = sandbox
    session, loop = app.open_chat_session("policy codec failure", AutoApproveGateway())

    def crash_before_task_receipt(*_args: object, **_kwargs: object) -> None:
        raise _ReceiptCrash("outcome sealed before Task receipt")

    monkeypatch.setattr(
        app.tasks,
        "_record_action_receipt",
        crash_before_task_receipt,
    )
    with pytest.raises(_ReceiptCrash, match="outcome sealed"):
        loop.run_turn(session, "search")
    events = app.store.read(session.task_id)
    action = ActionContract.model_validate(
        next(
            event.decoded_payload()["action"]
            for event in events
            if event.event_type is TaskEventType.ACTION_PROPOSED
        )
    )
    before_policy = sum(
        event.event_type is TaskEventType.POLICY_DECIDED for event in events
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(sandbox, app.correction),
        app.policy,
        app.correction,
        app._chat_grants(),
    )

    def fail_policy_codec(*_args: object, **_kwargs: object) -> None:
        raise ValueError("malformed durable PolicyDecision")

    monkeypatch.setattr(app.tasks, "_recover_action_receipt", fail_policy_codec)
    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW") as caught:
        pipeline.execute(
            action,
            app.principal,
            capability_spec=sandbox.specs()[action.capability_id],
            record_artifacts=False,
            execution_claim=_held_claim(app, action.run_id),
        )

    assert caught.value.__class__.__name__ == "CapabilityEffectUnknown"
    assert sandbox.dispatch_count == 1
    assert (
        sum(
            event.event_type is TaskEventType.POLICY_DECIDED
            for event in app.store.read(session.task_id)
        )
        == before_policy
    )


def test_task_receipt_without_capability_outcome_stops_before_policy_or_dispatch(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "fixed\n",
                        },
                    ),
                ),
            ),
            ("done", ()),
        ),
    )
    session, loop = app.open_chat_session("receipt only", AutoApproveGateway())
    loop.run_turn(session, "edit")
    events = app.store.read(session.task_id)
    action = ActionContract.model_validate(
        next(
            event.decoded_payload()["action"]
            for event in events
            if event.event_type is TaskEventType.ACTION_PROPOSED
        )
    )
    before_policy = sum(
        event.event_type is TaskEventType.POLICY_DECIDED for event in events
    )
    empty_outcome_store = SQLiteTaskEventStore(tmp_path / "empty-outcome.sqlite3")
    sandbox = _DispatchCountingSandbox(
        tmp_path,
        idempotency_store=empty_outcome_store,
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(sandbox, app.correction),
        app.policy,
        app.correction,
        app._chat_grants(),
    )

    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW") as caught:
        pipeline.execute(
            action,
            app.principal,
            capability_spec=sandbox.specs()[action.capability_id],
            record_artifacts=False,
            execution_claim=_held_claim(app, action.run_id),
        )

    assert caught.value.__class__.__name__ == "CapabilityEffectUnknown"
    assert sandbox.dispatch_count == 0
    assert (
        sum(
            event.event_type is TaskEventType.POLICY_DECIDED
            for event in app.store.read(session.task_id)
        )
        == before_policy
    )


def test_action_receipt_identity_conflict_and_duplicate_fail_closed(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable\n",
                            "new_string": "fixed\n",
                        },
                    ),
                ),
            ),
            ("done", ()),
        ),
    )
    session, loop = app.open_chat_session("receipt identity", AutoApproveGateway())
    loop.run_turn(session, "edit")
    events = app.store.read(session.task_id)
    action = ActionContract.model_validate(
        next(
            event.decoded_payload()["action"]
            for event in events
            if event.event_type is TaskEventType.ACTION_PROPOSED
        )
    )
    receipt_event = next(
        event
        for event in events
        if event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
    )
    payload = receipt_event.decoded_payload()
    decision = PolicyDecision.model_validate(payload["decision"])
    permit = ActionPermit.model_validate(payload["permit"])
    receipt = ActionReceipt.model_validate(payload["receipt"])

    with pytest.raises(InvalidTransitionError, match="identity conflict"):
        app.tasks._record_action_receipt(
            session.task_id,
            action=action,
            decision=decision,
            permit=permit,
            receipt=receipt.model_copy(update={"receipt_id": "receipt:forged"}),
            effect=receipt_event.decoded_payload().get("effect"),
            writer_token=app.tasks._runtime_writer_token,
        )

    aggregate = app.tasks.get_task(session.task_id)
    app.store.append(
        session.task_id,
        expected_sequence=aggregate.sequence,
        drafts=(
            TaskEventDraft.build(
                event_id="event:duplicate-receipt",
                task_id=session.task_id,
                event_type=TaskEventType.ACTION_RECEIPT_RECORDED,
                payload=payload,
                occurred_at=app.tasks.now(),
                correlation_id=session.run_id,
                causation_id=aggregate.last_event_id,
            ),
        ),
    )
    pipeline = ActionPipeline(
        app.tasks,
        CapabilityBroker(app.sandbox, app.correction),
        app.policy,
        app.correction,
        app._chat_grants(),
    )
    with pytest.raises(CapabilityDenied, match="UNKNOWN_REQUIRES_REVIEW") as caught:
        pipeline.execute(
            action,
            app.principal,
            capability_spec=app.sandbox.specs()[action.capability_id],
            record_artifacts=False,
            execution_claim=_held_claim(app, action.run_id),
        )
    assert caught.value.__class__.__name__ == "CapabilityEffectUnknown"


def test_end_to_end_fixes_failing_test_and_returns_green_result(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            (
                "",
                (
                    _proposal(
                        "call-2",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "fixed",
                        },
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-3",
                        "workspace.run_tests",
                        {"command": "pytest"},
                    ),
                ),
            ),
            ("fixture fixed and tests pass", ()),
        ),
    )
    (tmp_path / "test_fixture.py").write_text(
        "def test_fixture():\n    assert open('fixture.txt').read() == 'fixed\\n'\n",
        encoding="utf-8",
    )

    session, loop = app.open_chat_session(
        "fix the failing fixture test",
        AutoApproveGateway(),
    )
    result = loop.run_turn(session, "make the test pass")

    assert result.stop_reason == "completed"
    assert result.text == "fixture fixed and tests pass"
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "fixed\n"
    test_result = json.loads(_tool_messages(loop)[-1].content)
    assert test_result["exit_code"] == 0
    receipt_count = sum(
        event.event_type is TaskEventType.ACTION_RECEIPT_RECORDED
        for event in app.tasks._event_store.read(session.task_id)
    )
    assert receipt_count == 3


def test_tool_results_are_fed_back_to_provider(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            ("read complete", ()),
        ),
    )
    session, loop = app.open_chat_session("inspect", AutoApproveGateway())
    result = loop.run_turn(session, "read the fixture")
    assert result.stop_reason == "completed"

    provider = app.provider
    assert isinstance(provider, DeterministicProvider)
    assert len(provider.requests) == 2
    second_messages = provider.requests[1].messages
    assistant = next(
        message
        for message in second_messages
        if message.role is ProviderMessageRole.ASSISTANT and message.tool_calls
    )
    assert assistant.tool_calls[0].tool_call_id == "call-1"
    assert assistant.tool_calls[0].capability_id == "workspace.read"
    tool = next(
        message
        for message in second_messages
        if message.role is ProviderMessageRole.TOOL
    )
    assert tool.tool_call_id == "call-1"
    assert "stable" in tool.content


def test_unauthorized_capability_proposal_stops_turn(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(("", (_proposal("call-1", "system.exec", {"cmd": "rm -rf /"}),)),),
    )
    session, loop = app.open_chat_session("evil", AutoApproveGateway())
    result = loop.run_turn(session, "do something")

    assert result.stop_reason == "unauthorized_proposal"
    events = _event_types(app, session.task_id)
    assert TaskEventType.ACTION_RECEIPT_RECORDED not in events


def test_policy_denial_is_reported_to_model_not_hidden(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            ("cannot read, giving up", ()),
        ),
    )
    session, loop = app.open_chat_session("halted read", AutoApproveGateway())
    app.correction_admin.correct("capability", "workspace.read", "test halt")
    result = loop.run_turn(session, "read it")

    assert result.stop_reason == "completed"
    tool_messages = _tool_messages(loop)
    assert len(tool_messages) == 1
    assert "policy denied" in tool_messages[0].content
    assert "CORRECTION_HALTED" in tool_messages[0].content


def test_edit_requires_exactly_one_match(tmp_path: Path) -> None:
    (tmp_path / "multi.txt").write_text("dup dup\n", encoding="utf-8")
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "multi.txt",
                            "old_string": "dup",
                            "new_string": "uniq",
                        },
                    ),
                ),
            ),
            ("edit failed as expected", ()),
        ),
    )
    session, loop = app.open_chat_session("ambiguous edit", AutoApproveGateway())
    loop.run_turn(session, "edit it")

    tool_messages = _tool_messages(loop)
    assert "must match exactly once" in tool_messages[0].content
    assert (tmp_path / "multi.txt").read_text(encoding="utf-8") == "dup dup\n"


def test_search_glob_and_grep(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-2",
                        "workspace.search",
                        {"mode": "grep", "pattern": "stable"},
                    ),
                ),
            ),
            ("search done", ()),
        ),
    )
    session, loop = app.open_chat_session("search", AutoApproveGateway())
    loop.run_turn(session, "find things")

    tool_messages = _tool_messages(loop)
    glob_result = json.loads(tool_messages[0].content)
    assert "fixture.txt" in glob_result["matches"]
    grep_result = json.loads(tool_messages[1].content)
    assert any("fixture.txt:1:stable" in line for line in grep_result["matches"])


def test_search_does_not_follow_workspace_symlinks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("EXTERNAL_SECRET_SENTINEL\n", encoding="utf-8")
    app = _chat_app(
        workspace,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.search",
                        {"mode": "grep", "pattern": "EXTERNAL_SECRET_SENTINEL"},
                    ),
                ),
            ),
            ("search complete", ()),
        ),
    )
    (workspace / "linked.txt").symlink_to(outside)

    session, loop = app.open_chat_session("search safely", AutoApproveGateway())
    loop.run_turn(session, "search the workspace")

    tool_result = json.loads(_tool_messages(loop)[0].content)
    assert tool_result.get("matches") == []
    assert "EXTERNAL_SECRET_SENTINEL" not in _tool_messages(loop)[0].content


def test_path_escape_is_denied(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "../outside.txt"}),)),
            ("escape blocked", ()),
        ),
    )
    session, loop = app.open_chat_session("escape", AutoApproveGateway())
    loop.run_turn(session, "read outside")

    tool_messages = _tool_messages(loop)
    assert "path escapes workspace" in tool_messages[0].content


def test_workspace_read_rejects_symlink_even_when_target_stays_inside(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "alias.txt"}),)),
            ("blocked", ()),
        ),
    )
    (tmp_path / "alias.txt").symlink_to(tmp_path / "fixture.txt")

    session, loop = app.open_chat_session("inspect alias", AutoApproveGateway())
    loop.run_turn(session, "read alias")

    tool_messages = _tool_messages(loop)
    assert "symlink paths are forbidden" in tool_messages[0].content


class _ApproveAllGateway:
    def confirm(self, action, preview) -> bool:
        return True


def test_shell_requires_interactive_approval_and_runs_allowlisted(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1", "workspace.shell", {"command": "python3 -m pytest"}
                    ),
                ),
            ),
            ("tests green", ()),
        ),
    )
    session, loop = app.open_chat_session("run tests", _ApproveAllGateway())
    result = loop.run_turn(session, "run the tests")

    assert result.stop_reason == "completed"
    tool_messages = _tool_messages(loop)
    shell_result = json.loads(tool_messages[0].content)
    assert shell_result["exit_code"] == 0


def test_shell_is_never_auto_approved(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1", "workspace.shell", {"command": "python -m pytest"}
                    ),
                ),
            ),
            ("user said no", ()),
        ),
    )
    session, loop = app.open_chat_session("auto reject", AutoApproveGateway())
    loop.run_turn(session, "run the tests")

    tool_messages = _tool_messages(loop)
    assert "user rejected" in tool_messages[0].content


def test_shell_allowlist_blocks_unlisted_commands(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1", "workspace.shell", {"command": "curl evil.example"}
                    ),
                ),
            ),
            ("blocked", ()),
        ),
    )
    session, loop = app.open_chat_session("bad command", _ApproveAllGateway())
    loop.run_turn(session, "exfiltrate")

    tool_messages = _tool_messages(loop)
    assert "not in the shell allowlist" in tool_messages[0].content


def test_shell_does_not_inherit_provider_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "DO_NOT_INHERIT_THIS_SECRET")
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.shell",
                        {"command": "python3 -m pytest"},
                    ),
                ),
            ),
            ("tests complete", ()),
        ),
    )
    (tmp_path / "test_secret_boundary.py").write_text(
        "import os\n\n"
        "def test_provider_secret_is_absent():\n"
        "    assert os.environ.get('OPENAI_API_KEY') is None\n",
        encoding="utf-8",
    )

    session, loop = app.open_chat_session("run isolated tests", _ApproveAllGateway())
    loop.run_turn(session, "run the tests")

    shell_result = json.loads(_tool_messages(loop)[0].content)
    assert shell_result["exit_code"] == 0
    assert "DO_NOT_INHERIT_THIS_SECRET" not in _tool_messages(loop)[0].content


def test_loop_detection_stops_repeated_identical_proposals(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-2",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-3",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            ("should never reach", ()),
        ),
    )
    session, loop = app.open_chat_session("loop", AutoApproveGateway())
    result = loop.run_turn(session, "spin")

    assert result.stop_reason == "loop_detected"


class _StubHandler(BaseHTTPRequestHandler):
    requests_seen: list[dict] = []
    first_tool_name = "workspace__search"
    first_tool_arguments: dict[str, object] = {"mode": "ls"}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests_seen.append(body)
        if len(type(self).requests_seen) == 1:
            payload = {
                "id": "cmpl-1",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": type(self).first_tool_name,
                                        "arguments": json.dumps(
                                            type(self).first_tool_arguments
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                },
            }
        else:
            payload = {
                "id": "cmpl-2",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "CLI-DONE"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            }
        if body.get("stream"):
            # E1: the runtime asks for SSE via complete_streaming; a real
            # OpenAI-compatible endpoint answers with text/event-stream.
            first = payload["choices"][0]
            if first["message"].get("tool_calls"):
                tool_call = first["message"]["tool_calls"][0]
                deltas = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": tool_call["id"],
                                            "type": "function",
                                            "function": {
                                                "name": tool_call["function"]["name"]
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "function": {
                                                "arguments": tool_call["function"][
                                                    "arguments"
                                                ]
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": first["finish_reason"],
                            }
                        ]
                    },
                ]
            else:
                deltas = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": first["message"]["content"]},
                            }
                        ]
                    },
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": first["finish_reason"],
                            }
                        ]
                    },
                ]
            encoded = (
                "".join(f"data: {json.dumps(delta)}\n\n" for delta in deltas).encode(
                    "utf-8"
                )
                + b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture()
def stub_provider():
    _StubHandler.requests_seen = []
    _StubHandler.first_tool_name = "workspace__search"
    _StubHandler.first_tool_arguments = {"mode": "ls"}
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)


def _cli_env(stub_url: str) -> dict[str, str]:
    env = dict(os.environ)
    env["AGENT_OS_PROVIDER_BASE_URL"] = stub_url
    env["AGENT_OS_PROVIDER_MODEL"] = "stub-model"
    env["OPENAI_API_KEY"] = "stub-key"
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(repo_root),
            str(repo_root / "src"),
            str(repo_root / "packages" / "contracts" / "src"),
            str(repo_root / "packages" / "os_core" / "src"),
        ]
    )
    return env


@pytest.fixture()
def cli_daemon(
    tmp_path: Path,
    stub_provider: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Path, None, None]:
    env = _cli_env(stub_provider)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    database = tmp_path / "agent-os.sqlite3"
    app = AgentOSApplication(database=database, workspace=tmp_path)
    assert app.provider_configured
    token = "cli-daemon-test-token"
    server = build_server(app, "127.0.0.1", 0, local_token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    descriptor_path = tmp_path / "runtime.json"
    descriptor_path.write_text(
        json.dumps(
            {
                "protocol_version": "1.1",
                "pid": os.getpid(),
                "boot_id": "boot:cli-daemon-test",
                "host": "127.0.0.1",
                "port": server.server_address[1],
                "bearer_token": token,
                "database_path": str(database),
                "workspace_path": str(tmp_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    try:
        yield descriptor_path
    finally:
        server.shutdown()
        server.server_close()


def test_cli_chat_prompt_mode_end_to_end(
    tmp_path: Path, stub_provider: str, cli_daemon: Path
) -> None:
    _prepare_workspace(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--descriptor",
            str(cli_daemon),
            "chat",
            "-p",
            "list the files",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=_cli_env(stub_provider),
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert "CLI-DONE" in completed.stdout
    assert len(_StubHandler.requests_seen) == 2
    second_request = _StubHandler.requests_seen[1]
    roles = [message["role"] for message in second_request["messages"]]
    assert "tool" in roles
    tool_message = next(
        message for message in second_request["messages"] if message["role"] == "tool"
    )
    assert tool_message["tool_call_id"] == "call_1"
    tools = {
        tool["function"]["name"]: tool["function"]["parameters"]
        for tool in _StubHandler.requests_seen[0]["tools"]
    }
    assert tools["workspace__read"] == {
        "type": "object",
        "properties": {"path": {"type": "string", "minLength": 1}},
        "required": ["path"],
        "additionalProperties": False,
    }
    assert tools["workspace__edit"]["required"] == [
        "path",
        "old_string",
        "new_string",
    ]
    assert tools["workspace__search"]["properties"]["mode"]["enum"] == [
        "ls",
        "glob",
        "grep",
    ]


def test_cli_prompt_mode_denies_edit_without_interactive_approval(
    tmp_path: Path, stub_provider: str, cli_daemon: Path
) -> None:
    _prepare_workspace(tmp_path)
    _StubHandler.first_tool_name = "workspace__edit"
    _StubHandler.first_tool_arguments = {
        "path": "fixture.txt",
        "old_string": "stable",
        "new_string": "silently-mutated",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--descriptor",
            str(cli_daemon),
            "chat",
            "-p",
            "change the fixture",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=_cli_env(stub_provider),
        cwd=tmp_path,
    )

    assert completed.returncode != 0, completed.stdout
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert "approval required" in completed.stdout
    assert len(_StubHandler.requests_seen) == 1


def test_cli_chat_repl_smoke(
    tmp_path: Path, stub_provider: str, cli_daemon: Path
) -> None:
    _prepare_workspace(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--descriptor",
            str(cli_daemon),
            "chat",
        ],
        input="list the files\n/exit\n",
        capture_output=True,
        text=True,
        timeout=120,
        env=_cli_env(stub_provider),
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert "chat session started" in completed.stdout
    assert "CLI-DONE" in completed.stdout


def test_cli_interrupt_at_prompt_records_run_correction(
    tmp_path: Path, stub_provider: str, cli_daemon: Path
) -> None:
    _prepare_workspace(tmp_path)
    database = tmp_path / "agent-os.sqlite3"
    env = _cli_env(stub_provider)
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--descriptor",
            str(cli_daemon),
            "chat",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert process.stdout is not None
    banner = process.stdout.readline()
    assert "chat session started" in banner
    instructions = process.stdout.readline()
    assert "type /exit" in instructions
    prompt = process.stdout.read(len("you> "))
    assert prompt == "you> "

    process.send_signal(signal.SIGINT)
    stdout, stderr = process.communicate(timeout=20)

    assert process.returncode == 0, stderr
    app = AgentOSApplication(database=database, workspace=tmp_path)
    task_ids = app.store.list_task_ids()
    assert len(task_ids) == 1
    events = _event_types(app, task_ids[0])
    assert TaskEventType.CORRECTION_WRITTEN in events
    assert "correction-halted" in stdout


def test_chat_session_seals_configuration_and_receipts_provider_calls(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.read", {"path": "fixture.txt"}),)),
            ("read complete", ()),
        ),
    )

    session, loop = app.open_chat_session("inspect", AutoApproveGateway())
    result = loop.run_turn(session, "read the fixture")

    assert result.stop_reason == "completed"
    aggregate = app.tasks.get_task(session.task_id)
    assert aggregate.configuration_snapshot is not None
    assert aggregate.run is not None
    assert (
        aggregate.run.configuration_snapshot_id
        == aggregate.configuration_snapshot.snapshot_id
    )
    provider_events = [
        event
        for event in app.tasks._event_store.read(session.task_id)
        if event.event_type is TaskEventType.PROVIDER_RESPONDED
    ]
    assert len(provider_events) == 2
    assert all(
        "provider_execution_receipt" in event.decoded_payload()
        for event in provider_events
    )
    envelope_events = [
        event.decoded_payload()
        for event in app.tasks._event_store.read(session.task_id)
        if event.event_type is TaskEventType.CANDIDATES_GENERATED
    ]
    assert len(envelope_events) == 1
    assert set(envelope_events[0]["envelope"]["allowed_capability_ids"]) == {
        "session.todo_write",
        "workspace.read",
        "workspace.search",
        "workspace.edit",
        "workspace.apply_patch",
        "workspace.run_tests",
        "workspace.shell",
    }


def test_session_and_turn_identity_contracts_are_closed() -> None:
    contracts = import_module("agent_os_contracts")
    assert hasattr(contracts, "SessionRef")
    assert hasattr(contracts, "TurnId")
    session_ref_type = getattr(contracts, "SessionRef")
    turn_id_type = getattr(contracts, "TurnId")

    session = session_ref_type(
        session_id="session-1",
        task_id="task-1",
        run_id="run-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )
    turn = turn_id_type(turn_id="turn-1", session_id=session.session_id)

    assert session.model_dump() == {
        "schema_version": "1.0",
        "session_id": "session-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
    }
    assert turn.model_dump() == {
        "schema_version": "1.0",
        "turn_id": "turn-1",
        "session_id": "session-1",
    }
    with pytest.raises(Exception):
        session_ref_type(
            session_id="",
            task_id="task-1",
            run_id="run-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
        )


# --- Review-required-change coverage (review-interim.md RC1-RC6) ---


def _assert_tool_blocks_closed(messages) -> None:
    """Every ASSISTANT tool_call has exactly one matching TOOL reply later."""
    open_calls: list[str] = []
    answered: list[str] = []
    for message in messages:
        if message.role is ProviderMessageRole.ASSISTANT:
            open_calls.extend(call.tool_call_id for call in message.tool_calls)
        elif message.role is ProviderMessageRole.TOOL:
            assert message.tool_call_id in open_calls, (
                f"TOOL reply {message.tool_call_id} has no preceding tool_call"
            )
            answered.append(message.tool_call_id)
    assert sorted(open_calls) == sorted(answered), (
        f"dangling tool_calls: {sorted(set(open_calls) - set(answered))}"
    )


def test_session_recovers_after_unauthorized_proposal_stop(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-bad", "system.exec", {"cmd": "rm -rf /"}),)),
            ("recovered", ()),
        ),
    )
    session, loop = app.open_chat_session("evil", AutoApproveGateway())
    first = loop.run_turn(session, "do something")
    assert first.stop_reason == "unauthorized_proposal"

    second = loop.run_turn(session, "are you still there?")
    assert second.stop_reason == "completed"
    assert second.text == "recovered"
    _assert_tool_blocks_closed(loop.history)
    provider = app.provider
    assert isinstance(provider, DeterministicProvider)
    _assert_tool_blocks_closed(provider.requests[-1].messages)


def test_session_recovers_after_loop_detected_stop(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-2",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-3",
                        "workspace.search",
                        {"mode": "glob", "pattern": "*.txt"},
                    ),
                ),
            ),
            ("recovered", ()),
        ),
    )
    session, loop = app.open_chat_session("loop", AutoApproveGateway())
    first = loop.run_turn(session, "spin")
    assert first.stop_reason == "loop_detected"

    second = loop.run_turn(session, "stop spinning")
    assert second.stop_reason == "completed"
    _assert_tool_blocks_closed(loop.history)


def test_trailing_proposals_get_error_replies_on_stop(tmp_path: Path) -> None:
    first = _proposal(
        "call-1", "workspace.search", {"mode": "glob", "pattern": "*.txt"}
    )
    repeated = _proposal(
        "call-2", "workspace.search", {"mode": "glob", "pattern": "*.txt"}
    )
    trailing = _proposal("call-3", "workspace.read", {"path": "fixture.txt"})
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (first,)),
            ("", (repeated, trailing)),
            ("recovered", ()),
        ),
    )
    session, loop = app.open_chat_session(
        "loop",
        AutoApproveGateway(),
        loop_config=AgentLoopConfig(loop_detection_threshold=2),
    )
    result = loop.run_turn(session, "spin")
    assert result.stop_reason == "loop_detected"

    tool_messages = _tool_messages(loop)
    trailing_reply = next(
        message for message in tool_messages if message.tool_call_id == "call-3"
    )
    assert "not executed: loop_detected" in trailing_reply.content
    _assert_tool_blocks_closed(loop.history)

    second = loop.run_turn(session, "again")
    assert second.stop_reason == "completed"


class _DenyAllGateway:
    def confirm(self, action, preview) -> bool:
        return False


def test_approval_denial_is_recorded_as_durable_event(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "fixed",
                        },
                    ),
                ),
            ),
            ("denied", ()),
        ),
    )
    session, loop = app.open_chat_session("deny edit", _DenyAllGateway())
    loop.run_turn(session, "edit the fixture")

    events = app.tasks._event_store.read(session.task_id)
    approval_events = [
        event for event in events if event.event_type is TaskEventType.APPROVAL_RECORDED
    ]
    assert len(approval_events) == 1
    approval = approval_events[0].decoded_payload()["approval"]
    assert approval["disposition"] == "REJECT"
    proposed = [
        event for event in events if event.event_type is TaskEventType.ACTION_PROPOSED
    ]
    action = ActionContract.model_validate(proposed[-1].decoded_payload()["action"])
    assert approval["action_digest"] == action.action_digest()
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    tool_messages = _tool_messages(loop)
    assert "user rejected" in tool_messages[0].content


def test_grants_track_spec_tiers_and_unset_tier_inherits(tmp_path: Path) -> None:
    app = _chat_app(tmp_path)
    # The composition envelope intentionally tracks declared spec tiers, and
    # the kernel floors under-declared callers against the same spec.
    assert app.grants["workspace.edit"].max_risk_tier == 2
    assert app.grants["workspace.shell"].max_risk_tier == 3
    session, loop = app.open_chat_session("tiers", AutoApproveGateway())

    # A graph-style tier-0 (unset) action inherits the spec tier: tier-2 edit
    # is admitted by the tier-2 grant...
    edit_action = loop._actions.build_action(
        task_id=session.task_id,
        run_id=session.run_id,
        node_id="unset-tier-edit",
        capability_id="workspace.edit",
        principal=app.principal,
        args={"path": "fixture.txt", "old_string": "a", "new_string": "b"},
        expected=session.expected,
        envelope_id=session.envelope_id,
        risk_tier=0,
    )
    edit_decision = app.policy.decide(
        edit_action,
        PolicyInput(
            principal=app.principal,
            grant=app.grants["workspace.edit"],
            capability=app.sandbox.specs().get("workspace.edit"),
        ),
    )
    assert edit_decision.verdict is PolicyVerdict.ALLOW

    # ...while a tier-0 shell action escalates to approval instead of running
    # silently (finding 1: enforcement now lives in the kernel, not callers).
    shell_action = loop._actions.build_action(
        task_id=session.task_id,
        run_id=session.run_id,
        node_id="unset-tier-shell",
        capability_id="workspace.shell",
        principal=app.principal,
        args={"command": "pytest"},
        expected=session.expected,
        envelope_id=session.envelope_id,
        risk_tier=0,
    )
    shell_decision = app.policy.decide(
        shell_action,
        PolicyInput(
            principal=app.principal,
            grant=app.grants["workspace.shell"],
            capability=app.sandbox.specs().get("workspace.shell"),
        ),
    )
    assert shell_decision.verdict is PolicyVerdict.ESCALATE
    assert "APPROVAL_REQUIRED" in shell_decision.reason_codes


def test_kernel_denies_underdeclared_risk_tier(tmp_path: Path) -> None:
    app = _chat_app(tmp_path)
    session, loop = app.open_chat_session("floor", AutoApproveGateway())
    action = loop._actions.build_action(
        task_id=session.task_id,
        run_id=session.run_id,
        node_id="underdeclared",
        capability_id="workspace.edit",
        principal=app.principal,
        args={"path": "fixture.txt", "old_string": "a", "new_string": "b"},
        expected=session.expected,
        envelope_id=session.envelope_id,
        risk_tier=1,
    )
    elevated_grant = app.grants["workspace.edit"].model_copy(
        update={"max_risk_tier": 3}
    )
    decision = app.policy.decide(
        action,
        PolicyInput(
            principal=app.principal,
            grant=elevated_grant,
            capability=app.sandbox.specs().get("workspace.edit"),
        ),
    )
    assert decision.verdict is PolicyVerdict.DENY
    assert "RISK_TIER_UNDERDECLARED" in decision.reason_codes


def test_tier3_action_without_approval_escalates(tmp_path: Path) -> None:
    app = _chat_app(tmp_path)
    session, loop = app.open_chat_session("escalate", AutoApproveGateway())
    action = loop._actions.build_action(
        task_id=session.task_id,
        run_id=session.run_id,
        node_id="shell-no-approval",
        capability_id="workspace.shell",
        principal=app.principal,
        args={"command": "pytest"},
        expected=session.expected,
        envelope_id=session.envelope_id,
        risk_tier=3,
    )
    elevated_grant = app.grants["workspace.shell"].model_copy(
        update={"max_risk_tier": 3}
    )
    decision = app.policy.decide(
        action,
        PolicyInput(
            principal=app.principal,
            grant=elevated_grant,
            capability=app.sandbox.specs().get("workspace.shell"),
        ),
    )
    assert decision.verdict is PolicyVerdict.ESCALATE
    assert "APPROVAL_REQUIRED" in decision.reason_codes


def test_max_steps_stop(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=tuple(
            ("", (_proposal(f"call-{index}", "workspace.search", {"mode": "ls"}),))
            for index in range(5)
        ),
    )
    session, loop = app.open_chat_session(
        "steps",
        AutoApproveGateway(),
        loop_config=AgentLoopConfig(max_steps_per_turn=2),
    )
    result = loop.run_turn(session, "keep searching")
    assert result.stop_reason == "max_steps"
    assert result.steps == 2


def test_budget_exceeded_stop(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.search", {"mode": "ls"}),)),
            ("done", ()),
        ),
    )
    session, loop = app.open_chat_session(
        "budget",
        AutoApproveGateway(),
        loop_config=AgentLoopConfig(max_turn_tokens=5),
    )
    result = loop.run_turn(session, "hello")
    assert result.stop_reason == "budget_exceeded"


class _FailingProvider:
    def __init__(self, binding) -> None:
        self._binding = binding
        self.calls = 0

    @property
    def invocation_binding(self):
        return self._binding

    def complete(self, request):
        self.calls += 1
        from datetime import datetime, timezone

        return ProviderFailure(
            failure_id="failure-test",
            request_id=request.request_id,
            code=ProviderErrorCode.UNAVAILABLE,
            retryable=True,
            safe_message="provider is down",
            occurred_at=datetime.now(timezone.utc),
        )

    def complete_streaming(
        self, request, *, on_text_delta=None, on_reasoning_delta=None
    ):
        return self.complete(request)


def test_provider_retry_exhaustion_stops_turn(tmp_path: Path) -> None:
    app = _chat_app(tmp_path)
    failing = _FailingProvider(app.provider.invocation_binding)
    app.provider = cast(Any, failing)
    session, loop = app.open_chat_session(
        "retry",
        AutoApproveGateway(),
        loop_config=AgentLoopConfig(max_provider_retries=2),
    )
    result = loop.run_turn(session, "go")
    assert result.stop_reason.startswith("provider_failure")
    assert failing.calls == 3


def test_trimmed_history_keeps_tool_blocks_atomic(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=tuple(
            (
                "",
                (
                    _proposal(
                        f"call-{index}",
                        "workspace.search",
                        {"mode": "glob", "pattern": f"*.ext{index}"},
                    ),
                ),
            )
            for index in range(6)
        )
        + (("final answer", ()),),
    )
    session, loop = app.open_chat_session(
        "trim",
        AutoApproveGateway(),
        loop_config=AgentLoopConfig(max_steps_per_turn=10, max_context_chars=1200),
    )
    result = loop.run_turn(session, "x" * 300)
    assert result.stop_reason == "completed"

    provider = app.provider
    assert isinstance(provider, DeterministicProvider)
    trimmed = provider.requests[-1].messages
    assert trimmed[0].role is ProviderMessageRole.SYSTEM
    assert len(trimmed) < len(loop.history)
    _assert_tool_blocks_closed(trimmed)


def _proposed_actions(app: AgentOSApplication, task_id: str):
    from agent_os_contracts import ActionContract

    return [
        ActionContract.model_validate(event.decoded_payload()["action"])
        for event in app.tasks._event_store.read(task_id)
        if event.event_type is TaskEventType.ACTION_PROPOSED
    ]


def test_agent_loop_multi_file_effects_compensate_in_reverse_order(
    tmp_path: Path,
) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            (
                "",
                (
                    _proposal(
                        "call-1",
                        "workspace.edit",
                        {
                            "path": "fixture.txt",
                            "old_string": "stable",
                            "new_string": "first",
                        },
                    ),
                ),
            ),
            (
                "",
                (
                    _proposal(
                        "call-2",
                        "workspace.edit",
                        {
                            "path": "second.txt",
                            "old_string": "before",
                            "new_string": "second",
                        },
                    ),
                ),
            ),
            ("edits complete", ()),
        ),
    )
    (tmp_path / "second.txt").write_text("before\n", encoding="utf-8")
    session, loop = app.open_chat_session("edit two files", AutoApproveGateway())

    result = loop.run_turn(session, "make both edits")
    assert result.stop_reason == "completed"
    edit_actions = [
        action
        for action in _proposed_actions(app, session.task_id)
        if action.capability_id == "workspace.edit"
    ]
    app.tasks.update_run_status(
        session.task_id,
        RunStatus.RUNNING,
        event_type=TaskEventType.RUN_RESUMED,
    )
    app.tasks.update_run_status(
        session.task_id,
        RunStatus.FAILED,
        event_type=TaskEventType.RUN_FAILED,
    )

    compensated = app.compensate_task(session.task_id)

    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "stable\n"
    assert (tmp_path / "second.txt").read_text(encoding="utf-8") == "before\n"
    completed = [
        record
        for record in compensated.compensations
        if record.status.value == "COMPENSATED"
    ]
    assert [record.node_id for record in completed] == [
        edit_actions[1].node_id,
        edit_actions[0].node_id,
    ]
