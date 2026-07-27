from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
)
from agent_os_core import (
    AutoApproveGateway,
    DeterministicProvider,
    EnvCredentialBroker,
    OpenAICompatibleProvider,
    run_agent_cli,
)
from agent_os_core.agent_loop import AgentLoop, AgentLoopConfig

from apps.api_server.app import AgentOSApplication


def _prepare_workspace(root: Path) -> None:
    (root / "fixture.txt").write_text("stable\n", encoding="utf-8")


def _agent_app(root: Path, *, text: str = "streamed assistant reply") -> AgentOSApplication:
    _prepare_workspace(root)
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        text=text,
        invocation_binding=app.provider.invocation_binding,
    )
    app.provider_configured = True
    return app


def _user_request(**overrides: object) -> ProviderRequest:
    base = {
        "request_id": "request-chunk",
        "task_id": "task-chunk",
        "run_id": "run-chunk",
        "provider_profile_id": "profile-chunk",
        "messages": (
            ProviderMessage(role=ProviderMessageRole.USER, content="hello"),
        ),
        "allowed_capability_ids": (),
        "timeout_seconds": 30,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return ProviderRequest(**base)  # type: ignore[arg-type]


def test_deterministic_provider_emits_chunked_deltas() -> None:
    provider = DeterministicProvider(text="hello streaming world")
    request = _user_request()
    deltas: list[str] = []
    response = provider.complete_streaming(request, on_text_delta=deltas.append)
    assert len(deltas) > 1
    assert "".join(deltas) == "hello streaming world"
    assert response.text == "hello streaming world"


def test_agent_loop_collects_deltas_on_no_tool_turn(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, text="loop delta text")
    session, loop = app.open_chat_session("stream test", AutoApproveGateway())
    deltas: list[str] = []
    loop = AgentLoop(
        tasks=app.tasks,
        provider=app.provider,
        provider_profile=app.provider_profile,
        policy=app.policy,
        correction=app.correction,
        sandbox=app.sandbox,
        grants={
            capability_id: app.grants[capability_id]
            for capability_id in (
                "workspace.read",
                "workspace.search",
                "workspace.edit",
                "workspace.apply_patch",
                "workspace.run_tests",
                "workspace.shell",
            )
        },
        principal=app.principal,
        gateway=AutoApproveGateway(),
        config=AgentLoopConfig(stream=True),
        on_text_delta=deltas.append,
    )
    result = loop.run_turn(session, "say hello")
    assert result.stop_reason == "completed"
    assert result.text == "loop delta text"
    assert len(deltas) > 1
    assert "".join(deltas) == "loop delta text"


class _FakeSSEStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = iter(lines)

    def readline(self) -> bytes:
        try:
            return next(self._lines)
        except StopIteration:
            return b""

    def __enter__(self) -> _FakeSSEStream:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _streaming_opener(lines: list[bytes]):
    def opener(_request: object, *, timeout: int) -> _FakeSSEStream:
        del timeout
        return _FakeSSEStream(lines)

    return opener


def test_openai_compatible_provider_parses_sse_deltas_and_tool_calls() -> None:
    now = datetime.now(timezone.utc)
    credential = CredentialRef(
        credential_ref_id="credential-stream",
        owner_principal_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        provider_id="openai-compatible",
        resolver_key="AGENT_OS_TEST_STREAM_SECRET",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    sse_lines = [
        b'data: {"id":"resp-sse","choices":[{"delta":{"content":"Hel"}}]}\n',
        b'data: {"id":"resp-sse","choices":[{"delta":{"content":"lo"}}]}\n',
        b'data: {"id":"resp-sse","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"workspace__read","arguments":"{\\"path\\":\\"fixture.txt\\"}"}}]}}]}\n',
        b'data: {"id":"resp-sse","choices":[{"finish_reason":"tool_calls"}]}\n',
        b"data: [DONE]\n",
    ]
    import os

    old = os.environ.get("AGENT_OS_TEST_STREAM_SECRET")
    os.environ["AGENT_OS_TEST_STREAM_SECRET"] = "stream-secret"
    try:
        provider = OpenAICompatibleProvider(
            base_url="http://fake.local",
            model="test-model",
            credential=credential,
            credentials=EnvCredentialBroker(),
            opener=_streaming_opener(sse_lines),
        )
        request = _user_request(
            request_id="request-sse",
            task_id="task-sse",
            run_id="run-sse",
            provider_profile_id="profile-sse",
            allowed_capability_ids=("workspace.read",),
        )
        deltas: list[str] = []
        response = provider.complete_streaming(request, on_text_delta=deltas.append)
    finally:
        if old is None:
            os.environ.pop("AGENT_OS_TEST_STREAM_SECRET", None)
        else:
            os.environ["AGENT_OS_TEST_STREAM_SECRET"] = old

    assert deltas == ["Hel", "lo"]
    assert response.text == "Hello"
    assert len(response.tool_proposals) == 1
    proposal = response.tool_proposals[0]
    assert proposal.capability_id == "workspace.read"
    assert json.loads(proposal.arguments_json) == {"path": "fixture.txt"}


def test_agent_cli_repl_streams_assistant_text(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, text="assistant streamed line")
    stdin = StringIO("hello\n/exit\n")
    stdout = StringIO()
    run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="stream repl",
        gateway=AutoApproveGateway(),
        offline=True,
        input_stream=stdin,
        output_stream=stdout,
    )
    output = stdout.getvalue()
    assert "assistant streamed line" in output
    first_you = output.index("you> ")
    assert output.index("assistant streamed line") > first_you


def test_agent_cli_no_stream_prints_full_response_once(tmp_path: Path) -> None:
    app = _agent_app(tmp_path, text="non-stream reply")
    result = run_agent_cli(
        app=app,
        workspace=tmp_path,
        database=tmp_path / "agent-os.sqlite3",
        goal="no stream",
        gateway=AutoApproveGateway(),
        prompt="hello",
        offline=True,
        stream=False,
    )
    assert result.exit_code == 0
    assert result.last_text == "non-stream reply"
