#!/usr/bin/env python3
"""Anti-stub linter: reject skeleton-only additions without tests.

The linter scans Python source files for:

- Function/method bodies that are only ``pass``, ``...``, ``raise NotImplementedError``,
  or ``return NotImplemented``.
- Classes whose methods are all stubs and which have no class-level assignments.
- New/changed modules that do not have a corresponding ``test_*.py`` file.

By default only files changed against ``HEAD`` are inspected, so legacy code is
not grandfathered in.  Use ``--all`` to scan the entire source tree for stubs
(but not untested-module warnings).
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path


# Exception names that count as a stub when raised alone.
_STUB_EXCEPTIONS = frozenset({"NotImplementedError"})


def _is_docstring_node(node: ast.AST) -> bool:
    """Return True for a standalone string literal (Python 3.7+ docstring)."""
    if not isinstance(node, ast.Expr):
        return False
    value = node.value
    return isinstance(value, ast.Constant) and isinstance(value.value, str)


def _is_notimplemented_return(node: ast.AST) -> bool:
    """Return True for ``return NotImplemented``."""
    if not isinstance(node, ast.Return):
        return False
    value = node.value
    if value is None:
        return False
    if isinstance(value, ast.Name) and value.id == "NotImplemented":
        return True
    return isinstance(value, ast.Constant) and value.value is NotImplemented


def _is_empty_body_node(node: ast.AST) -> bool:
    """Return True for ``pass`` or standalone ``...``."""
    if isinstance(node, ast.Pass):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    )


def _is_stub_raise(node: ast.AST) -> bool:
    """Return True for ``raise NotImplementedError`` or ``raise NotImplementedError(...)``."""
    if not isinstance(node, ast.Raise):
        return False
    exc = node.exc
    if exc is None:
        return False
    if isinstance(exc, ast.Name) and exc.id in _STUB_EXCEPTIONS:
        return True
    if isinstance(exc, ast.Call):
        func = exc.func
        if isinstance(func, ast.Name) and func.id in _STUB_EXCEPTIONS:
            return True
    return False


def is_stub_body(body: list[ast.stmt]) -> bool:
    """Return True when a function/method body is effectively a stub."""
    meaningful = [node for node in body if not _is_docstring_node(node)]
    if not meaningful:
        return True
    if len(meaningful) > 1:
        return False
    node = meaningful[0]
    if _is_empty_body_node(node):
        return True
    if _is_stub_raise(node):
        return True
    if _is_notimplemented_return(node):
        return True
    return False


def _is_protocol_class(node: ast.ClassDef) -> bool:
    """Return True when the class is a typing.Protocol (directly or indirectly)."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
        if isinstance(base, ast.Subscript):
            inner = base.value
            if isinstance(inner, ast.Name) and inner.id == "Protocol":
                return True
            if isinstance(inner, ast.Attribute) and inner.attr == "Protocol":
                return True
    return False


def _is_abc_class(node: ast.ClassDef) -> bool:
    """Return True when the class inherits from abc.ABC (directly or indirectly)."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "ABC":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "ABC":
            return True
    return False


def _find_stubs_in_body(
    path: Path,
    body: list[ast.stmt],
    inside_protocol: bool = False,
) -> list[tuple[Path, str]]:
    """Recursively find stubs in a module/class body."""
    issues: list[tuple[Path, str]] = []
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not inside_protocol and is_stub_body(node.body):
                issues.append((path, f"stub function/method: {node.name}"))
        elif isinstance(node, ast.ClassDef):
            is_protocol = inside_protocol or _is_protocol_class(node) or _is_abc_class(node)
            issues.extend(_find_stubs_in_body(path, node.body, is_protocol))
            if not is_protocol:
                methods = [
                    n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                if methods and all(is_stub_body(m.body) for m in methods):
                    non_method = [
                        n
                        for n in node.body
                        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Expr))
                    ]
                    if not non_method:
                        issues.append((path, f"stub class: {node.name}"))
    return issues


def find_stubs(path: Path) -> list[tuple[Path, str]]:
    """Return stub issues found in a single Python file."""
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [(path, f"cannot read file: {exc}")]

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [(path, f"syntax error: {exc}")]

    return _find_stubs_in_body(path, tree.body)


def _is_under_dir(file_path: Path, directory: Path) -> bool:
    """Return True when ``file_path`` is inside ``directory`` (or equal)."""
    try:
        file_path.relative_to(directory)
        return True
    except ValueError:
        return False


def _collect_source_files(dirs: list[str], root: Path) -> list[Path]:
    files: list[Path] = []
    for dirname in dirs:
        path = root / dirname
        if path.exists():
            files.extend(path.rglob("*.py"))
    return files


def _collect_test_files(dirs: list[str], root: Path) -> set[str]:
    names: set[str] = set()
    for dirname in dirs:
        path = root / dirname
        if path.exists():
            for p in path.rglob("test_*.py"):
                names.add(p.stem)
    return names


def _changed_files(root: Path) -> list[Path]:
    """Files added, copied, or modified against HEAD plus untracked Python files."""
    files: list[Path] = []

    def run_git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=root,
        )
        return result.stdout

    tracked = run_git("diff", "--name-only", "--diff-filter=ACM", "HEAD")
    files.extend(root / f for f in tracked.splitlines() if f.endswith(".py"))

    untracked = run_git("ls-files", "--others", "--exclude-standard")
    files.extend(root / f for f in untracked.splitlines() if f.endswith(".py"))

    return [f for f in files if f.exists()]


def _has_test_file(source: Path, test_basenames: set[str]) -> bool:
    if source.name == "__init__.py":
        return True
    # Modules with a leading underscore (e.g. ``_metric_aliases.py``) map to
    # ``test_metric_aliases.py`` without the leading underscore.
    stem = source.stem.lstrip("_")
    return f"test_{stem}" in test_basenames


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject skeleton-only additions without tests.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan all source files for stubs (legacy code is not checked for missing tests).",
    )
    parser.add_argument(
        "--source-dirs",
        nargs="+",
        default=["packages", "apps", "action_connectors", "providers", "scripts"],
        help="Directories containing product source code and tooling scripts.",
    )
    parser.add_argument(
        "--test-dirs",
        nargs="+",
        default=["tests"],
        help="Directories containing test files.",
    )
    args = parser.parse_args(argv)

    if repo_root is None:
        script_path = Path(__file__).resolve()
        repo_root = script_path.parents[1]

    if args.all:
        source_files = _collect_source_files(args.source_dirs, repo_root)
        check_untested = False
    else:
        changed = _changed_files(repo_root)
        source_files = [
            f
            for f in changed
            if f.exists() and any(_is_under_dir(f, repo_root / d) for d in args.source_dirs)
        ]
        check_untested = True

    test_basenames = _collect_test_files(args.test_dirs, repo_root)

    issues: list[tuple[Path, str]] = []
    for source in source_files:
        if not source.exists():
            continue
        issues.extend(find_stubs(source))
        if check_untested and not _has_test_file(source, test_basenames):
            issues.append((source, "new/changed module lacks corresponding test file"))

    if issues:
        print("Anti-stub linter found skeleton-only additions:\n")
        for path, reason in issues:
            rel = path.relative_to(repo_root)
            print(f"  {rel}: {reason}")
        print(f"\nTotal issues: {len(issues)}")
        return 1

    print("Anti-stub linter passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
