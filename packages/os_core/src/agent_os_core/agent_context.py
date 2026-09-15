"""Workspace agent-context discovery for Agent CLI."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

# Heavy/VCS directories pruned during traversal (never scanned for instructions).
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)
_MAX_BYTES_PER_FILE = 131072  # hard read cap per instruction file (128 KiB)


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
    """Fail-closed, bounded read of one instruction file (root or nested)."""

    if path.is_symlink():
        return None
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    try:
        # Bounded read: never load an unbounded file into memory. A file larger than
        # the hard cap is refused (fail closed), not truncated from a full read.
        with path.open("rb") as handle:
            data = handle.read(_MAX_BYTES_PER_FILE + 1)
    except OSError:
        return None
    if len(data) > _MAX_BYTES_PER_FILE:
        return None
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    truncated = len(raw) > max_chars
    return AgentsMarkdownContext(
        path=path.relative_to(root).as_posix(),
        sha256=digest,
        content=raw[:max_chars] if truncated else raw,
        truncated=truncated,
    )


def _pick(directory: Path) -> Path | None:
    for name in ("AGENTS.md", "CLAUDE.md"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.is_file() and entry.name.lower() in {"agents.md", "claude.md"}:
            return entry
    return None


def discover_agents_markdown_layers(
    workspace: Path,
    *,
    max_layers: int = 8,
    max_chars_per_file: int = 12000,
    max_total_chars: int = 24000,
    max_dirs: int = 2000,
) -> tuple[AgentsMarkdownContext, ...]:
    """Discover project instruction files as ordered layers (M1 S3).

    Deterministic and bounded: the workspace-root instruction file first, then nested
    ``AGENTS.md``/``CLAUDE.md`` files in sorted directory order. Traversal prunes heavy
    and hidden directories (``.git`` etc.) and stops after ``max_dirs`` directories;
    layers are capped by count and total characters, and each file read is byte-capped.
    Each layer keeps its own ``sha256`` change digest. Fail-closed per layer: a symlink,
    out-of-workspace, unreadable, non-UTF-8 or oversized file is skipped silently.
    """

    root = Path(workspace).resolve()
    ordered: list[Path] = []
    root_file = _pick(root)
    if root_file is not None:
        ordered.append(root_file)

    scanned = 0
    for current, dirs, _files in os.walk(root):
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in _SKIP_DIRS and not name.startswith(".")
        )
        if Path(current) == root:
            continue
        scanned += 1
        if scanned > max_dirs:
            break
        nested = _pick(Path(current))
        if nested is not None:
            ordered.append(nested)

    layers: list[AgentsMarkdownContext] = []
    seen: set[tuple[int, int]] = set()
    total = 0
    for path in ordered:
        if len(layers) >= max_layers:
            break
        try:
            stat = path.stat()
        except OSError:
            continue
        key = (stat.st_dev, stat.st_ino)  # dedupe repeats, incl. hardlinks
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


def _layer_header(layer: AgentsMarkdownContext) -> str:
    label = "CLAUDE.md" if layer.path.rsplit("/", 1)[-1].lower() == "claude.md" else "AGENTS.md"
    if "/" in layer.path:
        return f"# Nested {label} (path={layer.path}, sha256={layer.sha256})"
    return f"# Project {label} (sha256={layer.sha256})"


def layered_agents_markdown_system_section(
    layers: tuple[AgentsMarkdownContext, ...],
) -> str:
    """Render ordered layers with correct root vs nested provenance."""

    if not layers:
        return ""
    rendered = f"\n\n{_layer_header(layers[0])}\n{layers[0].content}"
    for layer in layers[1:]:
        rendered += f"\n\n{_layer_header(layer)}\n{layer.content}"
    return rendered


def agent_context_status_payload(ctx: AgentsMarkdownContext | None) -> dict[str, object] | None:
    if ctx is None:
        return None
    return {"path": ctx.path, "sha256": ctx.sha256, "truncated": ctx.truncated}
