from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DevCiBootstrapTest(unittest.TestCase):
    def test_makefile_exposes_bootstrap_and_full_local_ci_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertRegex(makefile, r"(?m)^bootstrap-dev:")
        self.assertRegex(makefile, r"(?m)^ci-local-full:")
        self.assertIn('".[dev,http,postgres]"', makefile)
        self.assertIn("agent_os_api.openapi_contract --check", makefile)
        self.assertIn("importlib.util.find_spec", makefile)
        self.assertNotIn("raise SystemExit", makefile)

    def test_project_extras_keep_runtime_core_dependency_free(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("fastapi>=0.110.0", pyproject)
        self.assertIn("httpx>=0.27.0", pyproject)
        self.assertIn("sqlalchemy>=2.0", pyproject)
        self.assertIn("psycopg[binary]>=3.1", pyproject)
        self.assertIn("dependencies = []", pyproject)

    def test_readme_documents_local_full_ci_without_claiming_release(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("make bootstrap-dev", readme)
        self.assertIn("make ci-local-full", readme)
        self.assertIn("Postgres-backed integration tests", readme)
        self.assertIn("does not publish, release, or push", readme)


if __name__ == "__main__":
    unittest.main()
