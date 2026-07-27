from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from importlib import import_module
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from agent_os_contracts import ProviderMessageRole, ProviderToolProposal, TaskEventType
from agent_os_core import AutoApproveGateway, DeterministicProvider

from apps.api_server.app import AgentOSApplication


def _proposal(call_id: str, capability_id: str, arguments: dict) -> ProviderToolProposal:
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
        message
        for message in loop.history
        if message.role is ProviderMessageRole.TOOL
    ]


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
        "def test_fixture():\n"
        "    assert open('fixture.txt').read() == 'fixed\\n'\n",
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
        scripted=(
            ("", (_proposal("call-1", "system.exec", {"cmd": "rm -rf /"}),)),
        ),
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
    app.correction.correct("capability", "workspace.read", "test halt")
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
            ("", (_proposal("call-1", "workspace.search", {"mode": "glob", "pattern": "*.txt"}),)),
            ("", (_proposal("call-2", "workspace.search", {"mode": "grep", "pattern": "stable"}),)),
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


def test_shell_requires_interactive_approval_and_runs_allowlisted(tmp_path: Path) -> None:
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (_proposal("call-1", "workspace.shell", {"command": "python3 -m pytest"}),)),
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
            ("", (_proposal("call-1", "workspace.shell", {"command": "python -m pytest"}),)),
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
            ("", (_proposal("call-1", "workspace.shell", {"command": "curl evil.example"}),)),
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
    repeated = _proposal("call-x", "workspace.search", {"mode": "glob", "pattern": "*.txt"})
    app = _chat_app(
        tmp_path,
        scripted=(
            ("", (repeated,)),
            ("", (repeated,)),
            ("", (repeated,)),
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

    def _write_sse(self, lines: list[str]) -> None:
        body = "".join(f"data: {line}\n\n" for line in lines) + "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).requests_seen.append(body)
        stream = bool(body.get("stream"))
        if len(type(self).requests_seen) == 1:
            if stream:
                tool_args = json.dumps(type(self).first_tool_arguments)
                self._write_sse(
                    [
                        json.dumps(
                            {
                                "id": "cmpl-1",
                                "choices": [
                                    {
                                        "delta": {
                                            "tool_calls": [
                                                {
                                                    "index": 0,
                                                    "id": "call_1",
                                                    "function": {
                                                        "name": type(self).first_tool_name,
                                                        "arguments": tool_args,
                                                    },
                                                }
                                            ]
                                        }
                                    }
                                ],
                            }
                        ),
                        json.dumps(
                            {
                                "id": "cmpl-1",
                                "choices": [{"finish_reason": "tool_calls"}],
                            }
                        ),
                    ]
                )
                return
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
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        else:
            if stream:
                self._write_sse(
                    [
                        json.dumps(
                            {
                                "id": "cmpl-2",
                                "choices": [{"delta": {"content": "CLI-DONE"}}],
                            }
                        ),
                        json.dumps(
                            {
                                "id": "cmpl-2",
                                "choices": [{"finish_reason": "stop"}],
                            }
                        ),
                    ]
                )
                return
            payload = {
                "id": "cmpl-2",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "CLI-DONE"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }
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


def test_cli_chat_prompt_mode_end_to_end(tmp_path: Path, stub_provider: str) -> None:
    _prepare_workspace(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--database",
            str(tmp_path / "agent-os.sqlite3"),
            "--workspace",
            str(tmp_path),
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


def test_cli_prompt_mode_auto_approves_tier2_edit(
    tmp_path: Path, stub_provider: str
) -> None:
    _prepare_workspace(tmp_path)
    _StubHandler.first_tool_name = "workspace__edit"
    _StubHandler.first_tool_arguments = {
        "path": "fixture.txt",
        "old_string": "stable",
        "new_string": "auto-approved",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--database",
            str(tmp_path / "agent-os.sqlite3"),
            "--workspace",
            str(tmp_path),
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

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "fixture.txt").read_text(encoding="utf-8") == "auto-approved\n"


def test_cli_prompt_mode_still_denies_tier3_shell(
    tmp_path: Path, stub_provider: str
) -> None:
    _prepare_workspace(tmp_path)
    _StubHandler.first_tool_name = "workspace__shell"
    _StubHandler.first_tool_arguments = {"command": "git status"}

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--database",
            str(tmp_path / "agent-os.sqlite3"),
            "--workspace",
            str(tmp_path),
            "agent",
            "-p",
            "run git status",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=_cli_env(stub_provider),
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    second_request = _StubHandler.requests_seen[1]
    tool_message = next(
        message for message in second_request["messages"] if message["role"] == "tool"
    )
    assert "user rejected" in tool_message["content"]


def test_cli_chat_repl_smoke(tmp_path: Path, stub_provider: str) -> None:
    _prepare_workspace(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "apps.cli",
            "--database",
            str(tmp_path / "agent-os.sqlite3"),
            "--workspace",
            str(tmp_path),
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
    tmp_path: Path, stub_provider: str
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
            "--database",
            str(database),
            "--workspace",
            str(tmp_path),
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
    assert set(
        envelope_events[0]["envelope"]["allowed_capability_ids"]
    ) == {
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
