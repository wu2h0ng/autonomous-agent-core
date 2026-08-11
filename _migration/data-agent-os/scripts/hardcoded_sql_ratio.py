"""Measure the ratio of hard-coded SQL to verified/config SQL templates.

The data-product compilation path must source SQL from reviewable domain-pack
contracts (``metrics.json`` / ``sql_templates.json``) rather than from string
literals embedded in source code. This script counts:

- ``verified_sql``: SQL strings in ``domain_packs/*/metrics.json``
  ``verified_queries`` and in ``domain_packs/*/sql_templates.json``.
- ``hardcoded_sql``: SQL-like string literals in production Python source files
  under ``packages/``, ``apps/``, and ``action_connectors/``, excluding tests,
  Alembic migrations, persistence schema definitions, and docstrings.

The ratio ``hardcoded / (hardcoded + verified)`` must stay at or below the
configured threshold (default 30%). If the ratio is exceeded, the script exits
non-zero so CI can fail closed.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

SQL_LEAD_RE = re.compile(
    r"^\s*(SELECT|WITH|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\s+",
    re.IGNORECASE,
)
SQL_BODY_RE = re.compile(
    r"\b(FROM|JOIN|WHERE|GROUP\s+BY|ORDER\s+BY|LIMIT|VALUES|SET|TABLE|COLUMN)\b",
    re.IGNORECASE,
)

DEFAULT_THRESHOLD = 0.30

EXCLUDED_SOURCE_SUBSTRINGS = (
    "/tests/",
    "/alembic/",
    "packages/persistence/src/agent_os_persistence/schema.py",
    "packages/persistence/src/agent_os_persistence/__init__.py",
)


def _is_sql(text: str) -> bool:
    text = text.strip()
    return bool(SQL_LEAD_RE.match(text)) and bool(SQL_BODY_RE.search(text))


def _is_excluded_source(path: Path) -> bool:
    text = str(path)
    return any(sub in text for sub in EXCLUDED_SOURCE_SUBSTRINGS)


def _docstring_value_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _extract_hardcoded_sql(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    docstring_ids = _docstring_value_ids(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_ids:
                continue
            candidate = node.value.strip()
            if _is_sql(candidate):
                found.append(candidate)
    return found


def _extract_verified_sql(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []

    found: list[str] = []

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ("sql", "query") and isinstance(value, str) and _is_sql(value):
                    found.append(value.strip())
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return found


def measure(root: Path) -> dict[str, object]:
    verified_sql: list[str] = []
    hardcoded_sql: list[str] = []
    hardcoded_files: list[tuple[str, int]] = []

    domain_packs = root / "domain_packs"
    if domain_packs.exists():
        for metrics_json in sorted(domain_packs.rglob("metrics.json")):
            verified_sql.extend(_extract_verified_sql(metrics_json))
        for templates_json in sorted(domain_packs.rglob("sql_templates.json")):
            verified_sql.extend(_extract_verified_sql(templates_json))

    source_roots = (root / "packages", root / "apps", root / "action_connectors")
    for source_root in source_roots:
        if not source_root.exists():
            continue
        for py_file in sorted(source_root.rglob("*.py")):
            if _is_excluded_source(py_file):
                continue
            found = _extract_hardcoded_sql(py_file)
            if found:
                hardcoded_sql.extend(found)
                hardcoded_files.append((str(py_file.relative_to(root)), len(found)))

    total = len(hardcoded_sql) + len(verified_sql)
    ratio = len(hardcoded_sql) / total if total else 0.0

    return {
        "verified_sql_count": len(verified_sql),
        "hardcoded_sql_count": len(hardcoded_sql),
        "total_sql_count": total,
        "ratio": ratio,
        "hardcoded_files": hardcoded_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure hard-coded SQL ratio in the data-product path."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root to measure (default: current directory).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Maximum allowed hard-coded ratio (default: {DEFAULT_THRESHOLD}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    args = parser.parse_args(argv)

    result = measure(args.root)
    ratio = result["ratio"]
    passed = ratio <= args.threshold

    if args.json:
        output = {
            "verified_sql_count": result["verified_sql_count"],
            "hardcoded_sql_count": result["hardcoded_sql_count"],
            "total_sql_count": result["total_sql_count"],
            "ratio": round(ratio, 4),
            "threshold": args.threshold,
            "passed": passed,
            "hardcoded_files": [
                {"path": path, "count": count} for path, count in result["hardcoded_files"]
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Verified/config SQL templates: {result['verified_sql_count']}")
        print(f"Hard-coded SQL in production source: {result['hardcoded_sql_count']}")
        print(f"Total SQL templates counted: {result['total_sql_count']}")
        print(f"Hard-coded ratio: {ratio:.1%}")
        print(f"Threshold: {args.threshold:.1%}")
        if result["hardcoded_files"]:
            print("Production files containing hard-coded SQL:")
            for path, count in result["hardcoded_files"]:
                print(f"  {path}: {count}")
        print(f"Result: {'PASS' if passed else 'FAIL'}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
