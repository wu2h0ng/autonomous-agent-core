"""Dataset node-id resolution against a checked-out task repo (ADR-0056).

SWE-bench-style datasets carry f2p/p2p test ids in three styles (see
``.agent_runs/selfdev-2/dataset/acquisition-report.md``):

- pytest style: ``tests/test_x.py::TestY::test_z`` or ``test_mod.py::test_z``
  — already admission-ready;
- unittest style: ``test_z (dotted.module.ClassName)`` (django/requests/
  sphinx rows);
- bare-name style: ``test_Identity`` — a bare test function name (sympy
  rows).

The admission contract (ADR-0056 decision 6) only accepts allowlisted
pytest node ids, so conversion happens BEFORE admission and is VERIFIED
against the repo checked out at the task's base commit: the emitted id must
point at a real file (and, for unittest style, at a real class and method
inside it). Anything that cannot be resolved to exactly one verified pytest
node id fails closed with BenchmarkTaskValidationError
(BENCHMARK_NODE_ID_UNRESOLVED), so the candidate task never enters the
selection pool. All matching is deterministic: repo files are enumerated in
sorted order, hidden directories (.git, .venv, ...) are pruned, and tail
matches prefer fewest path components, then lexicographic order.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from agent_os_contracts import (
    BenchmarkTaskValidationError,
    is_valid_benchmark_node_id,
)


BENCHMARK_NODE_ID_UNRESOLVED = "BENCHMARK_NODE_ID_UNRESOLVED"

_UNITTEST_ID_PATTERN = re.compile(
    r"(?P<method>[A-Za-z_][A-Za-z0-9_]*) "
    r"\((?P<dotted>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\)"
)
_BARE_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def resolve_benchmark_node_id(raw_id: str, *, repo_root: Path) -> str:
    """Resolve one dataset f2p/p2p id to a verified pytest node id.

    pytest-style input is validated against the admission allowlist and
    returned unchanged. unittest-style input is mapped to the module file
    under repo_root (direct dotted path, package __init__, then a
    deterministic last-two-segments tail search) and emitted as
    ``<relpath>::ClassName::test_method`` only if the file contains both
    the class and the method. A bare name is emitted as
    ``<relpath>::test_name`` only if exactly one test-path file under
    repo_root defines it. Every other outcome fails closed.
    """

    if not isinstance(raw_id, str) or not raw_id:
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            "benchmark node id must be a non-empty string",
        )
    if is_valid_benchmark_node_id(raw_id):
        return raw_id
    if "::" in raw_id:
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"pytest-style node id failed admission validation: {raw_id!r}",
        )
    unittest_match = _UNITTEST_ID_PATTERN.fullmatch(raw_id)
    if unittest_match is not None:
        resolved = _resolve_unittest_id(
            unittest_match.group("method"),
            unittest_match.group("dotted"),
            raw_id=raw_id,
            repo_root=repo_root,
        )
    elif _BARE_NAME_PATTERN.fullmatch(raw_id) is not None:
        resolved = _resolve_bare_name_id(raw_id, repo_root=repo_root)
    else:
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"benchmark node id matches no known dataset style: {raw_id!r}",
        )
    if not is_valid_benchmark_node_id(resolved):
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"resolved node id failed admission validation: {resolved!r} "
            f"(from {raw_id!r})",
        )
    return resolved


def resolve_benchmark_node_ids(
    raw_ids: tuple[str, ...], *, repo_root: Path
) -> tuple[str, ...]:
    """Resolve dataset ids preserving order; fail closed on any bad output."""

    resolved = tuple(
        resolve_benchmark_node_id(raw_id, repo_root=repo_root)
        for raw_id in raw_ids
    )
    for node_id in resolved:
        if not is_valid_benchmark_node_id(node_id):
            raise BenchmarkTaskValidationError(
                BENCHMARK_NODE_ID_UNRESOLVED,
                "resolved node id failed admission validation: "
                f"{node_id!r}",
            )
    return resolved


def _resolve_unittest_id(
    method: str,
    dotted: str,
    *,
    raw_id: str,
    repo_root: Path,
) -> str:
    segments = dotted.split(".")
    if len(segments) < 2:
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"unittest-style id needs a module and a class: {raw_id!r}",
        )
    class_name = segments[-1]
    module_file = _locate_module_file(
        segments[:-1], raw_id=raw_id, repo_root=repo_root
    )
    text = module_file.read_text(encoding="utf-8", errors="replace")
    if (
        re.search(
            rf"^\s*class {re.escape(class_name)}\b", text, re.MULTILINE
        )
        is None
    ):
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"class {class_name!r} not found in {module_file} "
            f"for {raw_id!r}",
        )
    if (
        re.search(rf"^\s*def {re.escape(method)}\b", text, re.MULTILINE)
        is None
    ):
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"method {method!r} not found in {module_file} for {raw_id!r}",
        )
    relpath = module_file.relative_to(repo_root).as_posix()
    return f"{relpath}::{class_name}::{method}"


def _locate_module_file(
    module_segments: list[str], *, raw_id: str, repo_root: Path
) -> Path:
    module_rel = "/".join(module_segments)
    direct = repo_root / (module_rel + ".py")
    if direct.is_file():
        return direct
    package_init = repo_root / module_rel / "__init__.py"
    if package_init.is_file():
        return package_init
    tail = tuple(module_segments[-2:])
    matches = [
        path
        for path in _iter_repo_python_files(repo_root)
        if _path_tail_matches(path.relative_to(repo_root), tail)
    ]
    if not matches:
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"module file not found under {repo_root} for {raw_id!r}",
        )
    matches.sort(
        key=lambda path: (
            len(path.relative_to(repo_root).parts),
            path.relative_to(repo_root).as_posix(),
        )
    )
    return matches[0]


def _path_tail_matches(relpath: Path, tail: tuple[str, ...]) -> bool:
    parts = relpath.parts
    if len(parts) < len(tail) or relpath.suffix != ".py":
        return False
    if len(tail) == 1:
        return parts[-1] == tail[0] + ".py"
    return parts[-2] == tail[0] and parts[-1] == tail[1] + ".py"


def _resolve_bare_name_id(raw_id: str, *, repo_root: Path) -> str:
    pattern = re.compile(rf"^def {re.escape(raw_id)}\b", re.MULTILINE)
    matches: list[Path] = []
    for path in _iter_repo_python_files(repo_root):
        relpath = path.relative_to(repo_root)
        if "test" not in relpath.as_posix():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text) is not None:
            matches.append(path)
    if len(matches) != 1:
        raise BenchmarkTaskValidationError(
            BENCHMARK_NODE_ID_UNRESOLVED,
            f"bare test name {raw_id!r} matched {len(matches)} candidate "
            f"files under {repo_root} (exactly one required)",
        )
    relpath = matches[0].relative_to(repo_root).as_posix()
    return f"{relpath}::{raw_id}"


def _iter_repo_python_files(repo_root: Path) -> list[Path]:
    """All .py files under repo_root, sorted; hidden dirs (.git/.venv) pruned."""

    if not repo_root.is_dir():
        return []
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [
            name for name in sorted(dirnames) if not name.startswith(".")
        ]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                files.append(Path(dirpath) / filename)
    return sorted(
        files, key=lambda path: path.relative_to(repo_root).as_posix()
    )
