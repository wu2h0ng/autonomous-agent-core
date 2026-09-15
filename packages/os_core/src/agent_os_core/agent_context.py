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
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Fail closed: an unreadable or non-UTF-8 AGENTS.md is ignored, never
        # allowed to abort session open.
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    truncated = len(raw) > max_chars
    content = raw[:max_chars] if truncated else raw
    rel = path.relative_to(root).as_posix()
    return AgentsMarkdownContext(
        path=rel, sha256=digest, content=content, truncated=truncated
    )


def agents_markdown_system_section(ctx: AgentsMarkdownContext) -> str:
    return f"\n\n# Project AGENTS.md (sha256={ctx.sha256})\n{ctx.content}"


def _read_layer(
    path: Path, root: Path, *, max_chars: int
) -> AgentsMarkdownContext | None:
    """Fail-closed read of one instruction file (shared by root and nested)."""

    if path.is_symlink():
        return None
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    truncated = len(raw) > max_chars
    return AgentsMarkdownContext(
        path=path.relative_to(root).as_posix(),
        sha256=digest,
        content=raw[:max_chars] if truncated else raw,
        truncated=truncated,
    )


def discover_agents_markdown_layers(
    workspace: Path,
    *,
    max_layers: int = 8,
    max_chars_per_file: int = 12000,
    max_total_chars: int = 24000,
) -> tuple[AgentsMarkdownContext, ...]:
    """Discover project instruction files as ordered layers (M1 S3).

    Deterministic and bounded: the workspace-root instruction file first, then nested
    ``AGENTS.md``/``CLAUDE.md`` files (sorted by path, ``.git``/hidden dirs skipped),
    capped by layer count and total characters. Each layer keeps its own ``sha256``
    (change digest) so a content change is detectable. Fail-closed per layer: a
    symlink, out-of-workspace, unreadable or non-UTF-8 file is skipped silently.
    """

    root = Path(workspace).resolve()
    layers: list[AgentsMarkdownContext] = []
    seen: set[Path] = set()

    def _pick(directory: Path) -> Path | None:
        for name in ("AGENTS.md", "CLAUDE.md"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
        for entry in sorted(directory.iterdir()):
            if entry.is_file() and entry.name.lower() in {"agents.md", "claude.md"}:
                return entry
        return None

    ordered: list[Path] = []
    root_file = _pick(root)
    if root_file is not None:
        ordered.append(root_file)
    for candidate_dir in sorted(
        p for p in root.rglob("*") if p.is_dir() and not _is_hidden_dir(p, root)
    ):
        nested = _pick(candidate_dir)
        if nested is not None:
            ordered.append(nested)

    total = 0
    for path in ordered:
        if len(layers) >= max_layers:
            break
        key = path.resolve()
        if key in seen:
            continue
        remaining = max_total_chars - total
        if remaining <= 0:
            break
        context = _read_layer(path, root, max_chars=min(max_chars_per_file, remaining))
        if context is None:
            continue
        seen.add(key)
        layers.append(context)
        total += len(context.content)
    return tuple(layers)


def _is_hidden_dir(path: Path, root: Path) -> bool:
    if path == root:
        return False
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def layered_agents_markdown_system_section(
    layers: tuple[AgentsMarkdownContext, ...],
) -> str:
    """Render ordered layers; the root layer keeps the legacy single-layer header."""

    if not layers:
        return ""
    rendered = agents_markdown_system_section(layers[0])
    for layer in layers[1:]:
        rendered += (
            f"\n\n# Nested AGENTS.md (path={layer.path}, sha256={layer.sha256})\n"
            f"{layer.content}"
        )
    return rendered


def agent_context_status_payload(ctx: AgentsMarkdownContext | None) -> dict[str, object] | None:
    if ctx is None:
        return None
    return {"path": ctx.path, "sha256": ctx.sha256, "truncated": ctx.truncated}
