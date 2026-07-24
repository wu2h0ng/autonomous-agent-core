"""Durable Mandate terminal session transcript for resume."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSION_FILENAME = "terminal_session.json"


@dataclass
class TerminalSessionTurn:
    role: str
    content: str


@dataclass
class TerminalSessionState:
    schema_version: str = "terminal-session.v1"
    goal: str | None = None
    repo_root: str | None = None
    mandate_id: str | None = None
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    turns: list[TerminalSessionTurn] = field(default_factory=list)
    tool_invocations: int = 0
    patches_applied: int = 0
    continuation_cycles: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "goal": self.goal,
            "repo_root": self.repo_root,
            "mandate_id": self.mandate_id,
            "updated_at": self.updated_at,
            "turns": [asdict(turn) for turn in self.turns],
            "tool_invocations": self.tool_invocations,
            "patches_applied": self.patches_applied,
            "continuation_cycles": self.continuation_cycles,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TerminalSessionState":
        turns = [
            TerminalSessionTurn(role=str(item.get("role", "")), content=str(item.get("content", "")))
            for item in raw.get("turns", ())
            if isinstance(item, dict)
        ]
        return cls(
            schema_version=str(raw.get("schema_version", "terminal-session.v1")),
            goal=raw.get("goal"),
            repo_root=raw.get("repo_root"),
            mandate_id=raw.get("mandate_id"),
            updated_at=str(raw.get("updated_at") or datetime.now(timezone.utc).isoformat()),
            turns=turns,
            tool_invocations=int(raw.get("tool_invocations", 0) or 0),
            patches_applied=int(raw.get("patches_applied", 0) or 0),
            continuation_cycles=int(raw.get("continuation_cycles", 0) or 0),
        )


def session_path(workspace: Path) -> Path:
    return Path(workspace) / ".agent_os" / SESSION_FILENAME


def save_terminal_session(workspace: Path, state: TerminalSessionState) -> Path:
    path = session_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now(timezone.utc).isoformat()
    path.write_text(
        json.dumps(state.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_terminal_session(workspace: Path) -> TerminalSessionState | None:
    path = session_path(workspace)
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return TerminalSessionState.from_dict(raw)
