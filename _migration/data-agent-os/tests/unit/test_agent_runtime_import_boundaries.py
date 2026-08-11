from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_IMPORTS = {
    "crewai",
    "langchain",
    "langchain_community",
    "langchain_core",
    "langgraph",
    "openai_agents",
}
RUNTIME_PATHS = (
    ROOT / "packages" / "os_core" / "src",
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "persistence" / "src",
    ROOT / "packages" / "sdk" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
)


class AgentRuntimeImportBoundaryTest(unittest.TestCase):
    def test_product_core_does_not_import_external_agent_frameworks(self) -> None:
        violations: list[str] = []
        for root in RUNTIME_PATHS:
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [alias.name.split(".")[0] for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module.split(".")[0]]
                    else:
                        continue
                    forbidden = sorted(FORBIDDEN_IMPORTS.intersection(names))
                    if forbidden:
                        violations.append(
                            f"{path.relative_to(ROOT)} imports {', '.join(forbidden)}"
                        )

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
