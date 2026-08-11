"""Regression guard for the production frontend container health contract."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "apps" / "workspace" / "frontend" / "Dockerfile"


class FrontendDockerfileHealthcheckTest(unittest.TestCase):
    def test_runtime_healthcheck_uses_ipv4_loopback(self) -> None:
        content = DOCKERFILE.read_text(encoding="utf-8")
        runner = content.split("FROM base AS runner", maxsplit=1)[1]
        healthchecks = re.findall(
            r"(?ms)^HEALTHCHECK\b.*?(?=^[A-Z][A-Z0-9_]*(?:[ \t]|$)|\Z)",
            runner,
        )

        self.assertEqual(1, len(healthchecks), "runner must define one HEALTHCHECK")
        healthcheck = healthchecks[0]
        self.assertIn("http://127.0.0.1:3000/", healthcheck)
        self.assertNotIn("http://localhost:3000/", healthcheck)


if __name__ == "__main__":
    unittest.main()
