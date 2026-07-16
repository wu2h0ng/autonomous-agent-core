"""Fail-closed R-STATE preregistration input resolution.

This is a non-writing preflight used before review-digest or freeze-lock work.
Historical inputs are rejected even when they enter through a glob alongside a
newer candidate.  This module never grants freeze authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


class FreezeInputViolation(RuntimeError):
    """A retired or explicitly inactive artifact reached prereg resolution."""


def _metadata(path: Path) -> tuple[str, bool | None]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        value = json.loads(text)
        if not isinstance(value, dict):
            raise FreezeInputViolation(f"prereg input is not an object: {path}")
        status = str(value.get("status", ""))
        active = value.get("active_freeze_input")
        if active is None and isinstance(value.get("retirement"), dict):
            active = value["retirement"].get("active_freeze_input")
        return status, active if isinstance(active, bool) else None
    status = ""
    active: bool | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("status:") and not status:
            status = line.split(":", 1)[1].strip().strip("'\"")
        if line.startswith("active_freeze_input:"):
            token = line.split(":", 1)[1].strip().lower()
            active = token == "true" if token in {"true", "false"} else None
    return status, active


def resolve_active_prereg_inputs(
    workspace_root: Path,
    *,
    explicit_paths: Iterable[Path] = (),
    glob_patterns: Iterable[str] = (),
) -> tuple[Path, ...]:
    """Resolve exact inputs after rejecting every retired/inactive match.

    All glob matches are inspected before any candidate is returned.  This
    prevents a caller from selecting the newest match while silently ignoring
    a retired legacy artifact in the same resolution set.
    """

    root = workspace_root.resolve()
    resolved: set[Path] = set()
    for path in explicit_paths:
        candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
        resolved.add(candidate)
    for pattern in glob_patterns:
        resolved.update(path.resolve() for path in root.glob(pattern) if path.is_file())
    if not resolved:
        raise FreezeInputViolation("no preregistration input resolved")
    for path in sorted(resolved):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise FreezeInputViolation(f"prereg input escapes workspace: {path}") from exc
        if not path.is_file():
            raise FreezeInputViolation(f"prereg input missing: {path}")
        status, active = _metadata(path)
        if status == "RETIRED_HISTORY_ONLY":
            raise FreezeInputViolation(f"RETIRED_HISTORY_ONLY input rejected: {path}")
        if active is False:
            raise FreezeInputViolation(f"active_freeze_input=false rejected: {path}")
    return tuple(sorted(resolved))
