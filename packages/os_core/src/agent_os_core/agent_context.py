"""Workspace agent-context discovery for Agent CLI."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentsMarkdownContext:
    path: str
    sha256: str
    content: str
    truncated: bool


def _resolve_agents_markdown_path(workspace: Path) -> Path | None:
    root = Path(workspace).resolve()
    primary = root / "AGENTS.md"
    if primary.is_file():
        return primary
    for entry in root.iterdir():
        if entry.is_file() and entry.name.lower() == "agents.md":
            return entry
    return None


def discover_agents_markdown(
    workspace: Path, *, max_chars: int = 12000
) -> AgentsMarkdownContext | None:
    """Discover workspace-root AGENTS.md and return truncated context.

    Fail closed (returns ``None``) when the file is a symlink or resolves
    outside the workspace. Missing file is not an error.
    """
    root = Path(workspace).resolve()
    path = _resolve_agents_markdown_path(root)
    if path is None:
        return None
    if path.is_symlink():
        return None
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    raw = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    truncated = len(raw) > max_chars
    content = raw[:max_chars] if truncated else raw
    rel = path.relative_to(root).as_posix()
    return AgentsMarkdownContext(
        path=rel, sha256=digest, content=content, truncated=truncated
    )


def agents_markdown_system_section(ctx: AgentsMarkdownContext) -> str:
    return f"\n\n# Project AGENTS.md (sha256={ctx.sha256})\n{ctx.content}"


def agent_context_status_payload(ctx: AgentsMarkdownContext | None) -> dict[str, object] | None:
    if ctx is None:
        return None
    return {"path": ctx.path, "sha256": ctx.sha256, "truncated": ctx.truncated}
