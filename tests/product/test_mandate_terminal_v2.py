"""TERMINAL-2: glob, unified diff, schemas, session resume."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from agent_os_core.capability import CapabilityDenied, WorkspaceSandbox
from agent_os_core.mandate_repl import MandateRepl, SequencedProvider, make_tool_response
from agent_os_core.mandate_terminal import ensure_local_mandate_session
from agent_os_core.provider import DeterministicProvider, OpenAICompatibleProvider
from agent_os_core.terminal_session import load_terminal_session
from agent_os_core.terminal_tool_schemas import tool_parameters_for
from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderProfile,
    ProviderRequest,
    ProviderMessage,
    ProviderMessageRole,
)
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

NOW = datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)


def test_glob_lists_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x=1\n", encoding="utf-8")
    (repo / "b.txt").write_text("y\n", encoding="utf-8")
    out = WorkspaceSandbox(repo)._dispatch("workspace.glob", {"pattern": "*.py"}, "k")
    assert out["match_count"] == 1
    assert out["paths"] == ["a.py"]


def test_unified_diff_applies_hunk(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\nworld\n", encoding="utf-8")
    diff = """--- a/hello.txt
+++ b/hello.txt
@@ -1,2 +1,2 @@
 hello
-world
+world!
"""
    out = WorkspaceSandbox(repo)._dispatch(
        "workspace.apply_patch", {"diff": diff}, "key:diff"
    )
    assert out["diff_files"] == 1
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello\nworld!\n"


def test_tool_schema_for_glob_is_structured() -> None:
    schema = tool_parameters_for("workspace.glob")
    assert schema["required"] == ["pattern"]
    assert "additionalProperties" in schema


def test_provider_emits_terminal_schemas(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    class FakeResp:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "id": "r1",
                    "choices": [
                        {
                            "message": {"content": "ok", "tool_calls": []},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_opener(req, timeout=0):  # noqa: ANN001
        captured["body"] = json.loads(req.data.decode())
        return FakeResp()

    now = NOW
    credential = CredentialRef(
        credential_ref_id="credential:test",
        owner_principal_id="user:founder",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        provider_id="openai-compatible",
        resolver_key="OPENAI_API_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from agent_os_core.provider import EnvCredentialBroker

    provider = OpenAICompatibleProvider(
        base_url="https://example.invalid/v1",
        model="gpt-test",
        credential=credential,
        credentials=EnvCredentialBroker(),
        timeout_seconds=5,
        provider_profile=ProviderProfile(
            profile_id="provider-profile:test",
            provider_id="openai-compatible",
            model_id="gpt-test",
            endpoint_class="openai-compatible",
            credential_ref_id=credential.credential_ref_id,
            capabilities=("chat",),
            max_context_tokens=1000,
            request_timeout_seconds=5,
            created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        ),
    )
    provider._opener = fake_opener  # type: ignore[method-assign]
    req = ProviderRequest(
        request_id=f"req:{uuid4()}",
        task_id="task:t",
        run_id="run:r",
        provider_profile_id="provider-profile:test",
        messages=(
            ProviderMessage(role=ProviderMessageRole.USER, content="hi"),
        ),
        allowed_capability_ids=("workspace.glob", "workspace.read"),
        timeout_seconds=5,
        created_at=now,
    )
    provider.complete(req)
    tools = captured["body"]["tools"]
    names = {item["function"]["name"] for item in tools}
    assert "workspace__glob" in names
    glob_tool = next(item for item in tools if item["function"]["name"] == "workspace__glob")
    assert glob_tool["function"]["parameters"]["required"] == ["pattern"]


def test_session_autosave_and_resume(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    database = tmp_path / "db.sqlite3"
    repo = tmp_path / "repo"
    workspace.mkdir()
    repo.mkdir()
    ensure_local_mandate_session(
        workspace=workspace, database=database, evaluated_at=NOW
    )
    provider = SequencedProvider([make_tool_response(request_id="r1", text="hello")])
    lines = iter(["ping", "/quit"])
    MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(lines),
        stdout=io.StringIO(),
        clock=lambda: NOW,
        repo_root=repo,
        tools_enabled=False,
    ).run()
    saved = load_terminal_session(workspace)
    assert saved is not None
    assert any(turn.content == "ping" for turn in saved.turns)

    provider2 = SequencedProvider([make_tool_response(request_id="r2", text="resumed")])
    out = io.StringIO()
    lines2 = iter(["/quit"])
    MandateRepl(
        workspace=workspace,
        provider=provider2,
        input_fn=lambda _p: next(lines2),
        stdout=out,
        clock=lambda: NOW,
        repo_root=repo,
        tools_enabled=False,
        resume_session=True,
    ).run()
    assert "[resume] loaded" in out.getvalue()
