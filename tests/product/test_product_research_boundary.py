from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOTS = (
    REPO_ROOT / "packages" / "contracts" / "src",
    REPO_ROOT / "packages" / "os_core" / "src",
)
FORBIDDEN_IMPORT_ROOTS = {"aac", "adapters", "domain_packs", "experiments"}


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_product_packages_do_not_import_research_or_domain_modules() -> None:
    product_files = tuple(
        path
        for root in PRODUCT_ROOTS
        for path in root.rglob("*.py")
    )
    assert product_files

    for path in product_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        forbidden = _imported_roots(tree) & FORBIDDEN_IMPORT_ROOTS
        assert not forbidden, f"{path}: forbidden imports {sorted(forbidden)}"
