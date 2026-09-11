"""M2 D2 frozen boundary: textual is a UI-only extra.

- packages/contracts and packages/os_core must never import textual
  (provider, policy, event store included);
- the TUI layer (apps/cli/tui_*) must reach the runtime only through the
  typed surface protocol (agent_os_contracts + apps.cli.surface_client),
  never through os_core internals.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SUBSTRATE_PACKAGES = (
    REPO_ROOT / "packages" / "contracts" / "src",
    REPO_ROOT / "packages" / "os_core" / "src",
)

TUI_MODULES = (
    REPO_ROOT / "apps" / "cli" / "tui_controller.py",
    REPO_ROOT / "apps" / "cli" / "tui_app.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_substrate_never_imports_textual() -> None:
    offenders: list[str] = []
    for package in SUBSTRATE_PACKAGES:
        for path in package.rglob("*.py"):
            if "textual" in _imports(path):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_tui_reaches_runtime_only_via_surface_protocol() -> None:
    offenders: list[str] = []
    for path in TUI_MODULES:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in {"agent_os_core", "sqlglot"}:
                        offenders.append(f"{path.name}: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in {"agent_os_core", "sqlglot"}:
                    offenders.append(f"{path.name}: {node.module}")
                if node.module.startswith("apps.") and node.module not in {
                    "apps.cli.surface_client",
                    "apps.cli.tui_controller",
                }:
                    offenders.append(f"{path.name}: {node.module}")
    assert offenders == []
