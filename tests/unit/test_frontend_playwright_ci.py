"""Frontend Playwright E2E CI gate (ADR-0013 workstream F)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "apps" / "workspace" / "frontend"


class FrontendPlaywrightCITest(unittest.TestCase):
    def test_playwright_config_and_e2e_specs_exist(self) -> None:
        self.assertTrue((FRONTEND / "playwright.config.ts").is_file())
        self.assertTrue((FRONTEND / "e2e" / "workspace.smoke.spec.ts").is_file())
        self.assertTrue((FRONTEND / "e2e" / "workspace.api-loop.spec.ts").is_file())
        self.assertTrue((FRONTEND / "e2e" / "fixtures" / "api-loop-mocks.ts").is_file())

    def test_package_json_declares_e2e_script(self) -> None:
        pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
        self.assertIn("test:e2e", pkg.get("scripts", {}))
        self.assertIn("@playwright/test", pkg.get("devDependencies", {}))

    def test_makefile_declares_frontend_e2e_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("frontend-e2e-check", makefile)
        self.assertIn("frontend-e2e", makefile)


if __name__ == "__main__":
    unittest.main()
