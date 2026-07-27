"""Durable terminal session persistence for Agent CLI resume."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_os_contracts import ProviderMessage, ProviderMessageRole

SESSION_FILENAME = "terminal_session.json"
SCHEMA_VERSION = "agent-cli-session.v1"


class TerminalSessionError(ValueError):
    """Fail-closed terminal session load/save error."""


@dataclass(frozen=True)
class TerminalSessionRecord:
    schema_version: str
    mandate_id: str
    task_id: str
    run_id: str
    session_id: str
    envelope_id: str
    goal: str
    repo_root: str
    database: str
    messages: tuple[dict[str, Any], ...]
    saved_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mandate_id": self.mandate_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "envelope_id": self.envelope_id,
            "goal": self.goal,
            "repo_root": self.repo_root,
            "database": self.database,
            "messages": list(self.messages),
            "saved_at": self.saved_at,
        }


def session_path(workspace: Path) -> Path:
    return Path(workspace) / ".agent_os" / SESSION_FILENAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def message_to_dict(message: ProviderMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message.role.value,
        "content": message.content,
    }
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "tool_call_id": call.tool_call_id,
                "capability_id": call.capability_id,
                "arguments_json": call.arguments_json,
            }
            for call in message.tool_calls
        ]
    return payload


def message_from_dict(raw: dict[str, Any]) -> ProviderMessage:
    role = ProviderMessageRole(str(raw["role"]))
    content = str(raw.get("content", ""))
    tool_call_id = raw.get("tool_call_id")
    tool_calls_raw = raw.get("tool_calls") or ()
    from agent_os_contracts import ProviderToolCall

    tool_calls = tuple(
        ProviderToolCall(
            tool_call_id=str(item["tool_call_id"]),
            capability_id=str(item["capability_id"]),
            arguments_json=str(item["arguments_json"]),
        )
        for item in tool_calls_raw
    )
    return ProviderMessage(
        role=role,
        content=content,
        tool_call_id=str(tool_call_id) if tool_call_id else None,
        tool_calls=tool_calls,
    )


def messages_from_history(history: tuple[ProviderMessage, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(message_to_dict(message) for message in history)


def history_from_messages(
    messages: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[ProviderMessage]:
    return [message_from_dict(item) for item in messages]


def save_terminal_session(
    *,
    workspace: Path,
    mandate_id: str,
    task_id: str,
    run_id: str,
    session_id: str,
    envelope_id: str,
    goal: str,
    repo_root: Path,
    database: Path,
    messages: tuple[ProviderMessage, ...],
) -> TerminalSessionRecord:
    record = TerminalSessionRecord(
        schema_version=SCHEMA_VERSION,
        mandate_id=mandate_id,
        task_id=task_id,
        run_id=run_id,
        session_id=session_id,
        envelope_id=envelope_id,
        goal=goal,
        repo_root=str(Path(repo_root).resolve()),
        database=str(Path(database).resolve()),
        messages=messages_from_history(messages),
        saved_at=_utc_now_iso(),
    )
    path = session_path(Path(workspace))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def load_terminal_session(workspace: Path) -> TerminalSessionRecord:
    path = session_path(Path(workspace))
    if not path.is_file():
        raise TerminalSessionError(f"terminal session missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    schema = str(raw.get("schema_version") or "")
    if schema != SCHEMA_VERSION:
        raise TerminalSessionError(f"unsupported session schema: {schema!r}")
    required = (
        "mandate_id",
        "task_id",
        "run_id",
        "session_id",
        "envelope_id",
        "goal",
        "repo_root",
        "database",
        "messages",
        "saved_at",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise TerminalSessionError(f"terminal session incomplete: {missing}")
    messages = raw.get("messages")
    if not isinstance(messages, list):
        raise TerminalSessionError("terminal session messages must be a list")
    database = str(raw["database"]).strip()
    if not database:
        raise TerminalSessionError("terminal session database binding is empty")
    return TerminalSessionRecord(
        schema_version=schema,
        mandate_id=str(raw["mandate_id"]),
        task_id=str(raw["task_id"]),
        run_id=str(raw["run_id"]),
        session_id=str(raw["session_id"]),
        envelope_id=str(raw["envelope_id"]),
        goal=str(raw["goal"]),
        repo_root=str(raw["repo_root"]),
        database=database,
        messages=tuple(messages),
        saved_at=str(raw["saved_at"]),
    )
